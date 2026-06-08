from rest_framework import viewsets

from .models import Gasto
from .serializers import GastoSerializer


class GastoViewSet(viewsets.ModelViewSet):
    """
    CRUD de gastos do usuário. Filtros opcionais por `mes_referencia`,
    `categoria`, `cartao` e `forma_pagamento` — a visão do mês é a consulta
    central do sistema.
    """

    serializer_class = GastoSerializer

    def get_queryset(self):
        qs = (
            Gasto.objects.filter(usuario=self.request.user)
            .select_related("categoria", "subcategoria", "cartao", "vinculo")
            .prefetch_related("tags")
        )
        params = self.request.query_params
        if mes := params.get("mes_referencia"):
            qs = qs.filter(mes_referencia=mes)
        if categoria := params.get("categoria"):
            qs = qs.filter(categoria_id=categoria)
        if cartao := params.get("cartao"):
            qs = qs.filter(cartao_id=cartao)
        if forma := params.get("forma_pagamento"):
            qs = qs.filter(forma_pagamento=forma)
        return qs
