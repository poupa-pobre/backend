from datetime import timedelta

from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.categorias.models import Categoria
from apps.gastos.models import Gasto
from apps.receitas.models import Receita

from .models import MovimentacaoDetectada
from .pix import identificar_banco, parsear_notificacao
from .serializers import (
    ConfirmarMovimentacaoSerializer,
    MovimentacaoDetectadaSerializer,
    ReceberNotificacaoSerializer,
)


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
