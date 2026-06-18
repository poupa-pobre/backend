from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.cartoes.models import Cartao
from apps.categorias.models import Categoria
from apps.gastos.models import Gasto
from apps.receitas.models import Receita

from .models import Importacao, MovimentacaoDetectada
from .parsers import ArquivoInvalido, parsear
from .pix import identificar_banco, parsear_notificacao
from .serializers import (
    ConfirmarImportacaoSerializer,
    ConfirmarMovimentacaoSerializer,
    ImportacaoSerializer,
    MovimentacaoDetectadaSerializer,
    PreviaImportacaoSerializer,
    ReceberNotificacaoSerializer,
)
from .sugestao import eh_duplicata, sugerir_categoria


class MovimentacaoDetectadaViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Caixa de revisão das notificações de Pix (RF-110, detecção por notificação).

    `create` recebe a notificação crua do Android, parseia e guarda **pendente**
    (descarta o que não é Pix). `confirmar` vira Receita/Gasto; `ignorar` descarta.
    """

    serializer_class = MovimentacaoDetectadaSerializer

    def get_queryset(self):
        qs = MovimentacaoDetectada.objects.do_usuario(self.request.user)
        status_q = self.request.query_params.get("status", "pendente")
        if status_q != "todas":
            qs = qs.filter(status=status_q)
        return qs

    def create(self, request):
        """Recebe a notificação crua, aplica o portão de palavra-chave e guarda."""
        entrada = ReceberNotificacaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data

        info = parsear_notificacao(
            texto=dados["texto"], titulo=dados["titulo"], pacote=dados["pacote"]
        )
        if not info["tipo"]:
            # Não passou no portão: não é Pix → não guarda.
            return Response({"ignorada": True, "motivo": "nao_e_pix"})

        # Dedupe: mesma notificação reenviada em poucos minutos (o listener repete).
        recente = MovimentacaoDetectada.objects.do_usuario(request.user).filter(
            texto_bruto=info["texto"],
            created_at__gte=timezone.now() - timedelta(minutes=10),
        ).first()
        if recente:
            return Response(self.get_serializer(recente).data, status=status.HTTP_200_OK)

        mov = MovimentacaoDetectada.objects.create(
            usuario=request.user,
            tipo=info["tipo"],
            valor=info["valor"],
            contraparte=info["contraparte"],
            banco=identificar_banco(dados["pacote"]),
            pacote=dados["pacote"] or None,
            texto_bruto=info["texto"],
        )
        return Response(self.get_serializer(mov).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def confirmar(self, request, pk=None):
        """Confirma a detecção: cria a Receita (recebido) ou o Gasto (enviado)."""
        mov = self.get_object()
        if mov.status != MovimentacaoDetectada.Status.PENDENTE:
            return Response(
                {"detail": "Movimentação já resolvida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ajustes = ConfirmarMovimentacaoSerializer(data=request.data)
        ajustes.is_valid(raise_exception=True)
        dados = ajustes.validated_data

        valor = dados.get("valor") or mov.valor
        if valor is None:
            return Response(
                {"detail": "Informe o valor — não veio na notificação."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        hoje = timezone.localdate()

        if mov.tipo == MovimentacaoDetectada.Tipo.RECEBIDO:
            receita = Receita.objects.create(
                usuario=request.user,
                descricao=(f"Pix de {mov.contraparte}" if mov.contraparte else "Pix recebido"),
                valor=valor,
                data_prevista=hoje,
                data_real=hoje,  # já recebido
                tipo=dados.get("tipo_receita") or Receita.Tipo.OUTRO,
            )
            mov.receita = receita
        else:
            categoria = None
            if dados.get("categoria"):
                categoria = Categoria.objects.filter(
                    usuario=request.user, id=dados["categoria"]
                ).first()
            categoria = categoria or Categoria.objects.filter(
                usuario=request.user, ativa=True
            ).first()
            if categoria is None:
                return Response(
                    {"detail": "Você não tem categorias ativas."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            gasto = Gasto.objects.create(
                usuario=request.user,
                descricao=(f"Pix para {mov.contraparte}" if mov.contraparte else "Pix enviado"),
                valor=valor,
                data=hoje,
                categoria=categoria,
                forma_pagamento=Gasto.FormaPagamento.PIX,
            )
            mov.gasto = gasto

        mov.status = MovimentacaoDetectada.Status.CONFIRMADA
        mov.save(update_fields=["status", "gasto", "receita", "updated_at"])
        return Response(self.get_serializer(mov).data)

    @action(detail=True, methods=["post"])
    def ignorar(self, request, pk=None):
        mov = self.get_object()
        mov.status = MovimentacaoDetectada.Status.IGNORADA
        mov.save(update_fields=["status", "updated_at"])
        return Response(self.get_serializer(mov).data)


def _ler_conteudo(arquivo):
    """Lê o upload como texto, tolerando latin-1 (extratos de banco velhos)."""
    bruto = arquivo.read()
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("utf-8", errors="ignore")


class ImportacaoViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Importação de extrato OFX/CSV (RF-111).

    `previa` lê o arquivo e devolve as transações com categoria **sugerida** e a
    marca de **duplicata** (RN-110) — sem gravar nada. `confirmar` recebe a lista
    revisada e cria os `Gasto`/`Receita`, registrando a importação. `list` é o
    histórico de importações concluídas.
    """

    serializer_class = ImportacaoSerializer

    def get_queryset(self):
        return Importacao.objects.do_usuario(self.request.user)

    @action(detail=False, methods=["post"])
    def previa(self, request):
        entrada = PreviaImportacaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        arquivo = entrada.validated_data["arquivo"]
        formato = entrada.validated_data.get("formato") or ""
        if not formato and arquivo.name:
            formato = arquivo.name.rsplit(".", 1)[-1].lower()

        try:
            transacoes = parsear(_ler_conteudo(arquivo), formato)
        except ArquivoInvalido as e:
            raise ValidationError({"arquivo": str(e)})

        itens = []
        for t in transacoes:
            item = {
                "data": t["data"],
                "valor": t["valor"],
                "descricao": t["descricao"],
                "tipo": t["tipo"],
                "duplicata": eh_duplicata(request.user, t),
                "categoria_sugerida": (
                    sugerir_categoria(request.user, t["descricao"])
                    if t["tipo"] == "gasto"
                    else None
                ),
                "forma_sugerida": t.get("forma") if t["tipo"] == "gasto" else None,
            }
            itens.append(item)

        return Response({
            "formato": formato or "csv",
            "quantidade": len(itens),
            "transacoes": itens,
        })

    @action(detail=False, methods=["post"])
    def confirmar(self, request):
        entrada = ConfirmarImportacaoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        dados = entrada.validated_data
        transacoes = dados["transacoes"]
        if not transacoes:
            raise ValidationError({"transacoes": "Nenhuma transação para importar."})

        categoria_padrao = Categoria.objects.filter(
            usuario=request.user, ativa=True
        ).first()

        criados = {"gastos": 0, "receitas": 0}
        with transaction.atomic():
            for t in transacoes:
                if t["tipo"] == "gasto":
                    categoria = None
                    if t.get("categoria"):
                        categoria = Categoria.objects.filter(
                            usuario=request.user, id=t["categoria"]
                        ).first()
                    categoria = categoria or categoria_padrao
                    if categoria is None:
                        raise ValidationError(
                            {"transacoes": "Você não tem categorias ativas."}
                        )
                    cartao = None
                    forma = t.get("forma_pagamento") or Gasto.FormaPagamento.DEBITO
                    if forma == Gasto.FormaPagamento.CREDITO and t.get("cartao"):
                        cartao = Cartao.objects.filter(
                            usuario=request.user, id=t["cartao"]
                        ).first()
                    if forma == Gasto.FormaPagamento.CREDITO and cartao is None:
                        forma = Gasto.FormaPagamento.DEBITO  # sem cartão válido (RN-020)
                    Gasto.objects.create(
                        usuario=request.user,
                        descricao=t["descricao"],
                        valor=t["valor"],
                        data=t["data"],
                        categoria=categoria,
                        forma_pagamento=forma,
                        cartao=cartao,
                    )
                    criados["gastos"] += 1
                else:
                    Receita.objects.create(
                        usuario=request.user,
                        descricao=t["descricao"],
                        valor=t["valor"],
                        data_prevista=t["data"],
                        data_real=t["data"],  # extrato = já realizado
                        tipo=t.get("tipo_receita") or Receita.Tipo.OUTRO,
                    )
                    criados["receitas"] += 1

            registro = Importacao.objects.create(
                usuario=request.user,
                arquivo_nome=dados.get("arquivo_nome") or "extrato",
                formato=dados["formato"],
                quantidade_transacoes=len(transacoes),
            )

        return Response(
            {
                "importacao": self.get_serializer(registro).data,
                "criados": criados,
            },
            status=status.HTTP_201_CREATED,
        )
