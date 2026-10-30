from datetime import date

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from transport.models import TravelRecord
from transport.serializers import TravelRecordSerializer
from transport.services import (
    derive_payment_types,
    local_month_range,
    monthly_comparison,
    monthly_history,
    monthly_summary,
    next_direction,
)


def parse_month(raw) -> date:
    """Interpreta ?month=YYYY-MM (o YYYY-MM-DD) y devuelve el primer día del mes.

    Si el valor falta o es inválido, usa el mes actual (zona Córdoba).
    """
    if not raw:
        return timezone.localdate().replace(day=1)
    try:
        return date.fromisoformat(raw).replace(day=1)
    except ValueError:
        try:  # aceptar también "YYYY-MM"
            return date.fromisoformat(f"{raw}-01").replace(day=1)
        except ValueError:
            return timezone.localdate().replace(day=1)


def parse_months(raw, default: int = 6) -> int:
    """Interpreta ?months=N acotado a 1..24 (default 6)."""
    try:
        return max(1, min(int(raw), 24))
    except (TypeError, ValueError):
        return default


class TravelViewSet(viewsets.ModelViewSet):
    """API de viajes: historial con filtros, alta con defaults, edición y anulado.

    - ``POST`` acepta ``occurred_at``/``amount``/``direction`` opcionales
      (defaults: ahora, tarifa vigente, dirección sugerida) y responde
      **409** si hay un viaje de la misma dirección hace menos de 60 s
      (doble toque), salvo ``?force=true``.
    - La anulación es ``PATCH {"status": "VOIDED"}`` (no se borra nada y no
      se implementa DELETE).
    - ``payment_type`` es de solo lectura y se deriva por mes calendario;
      ``?payment_type=`` filtra sobre ese valor derivado.
    """

    serializer_class = TravelRecordSerializer
    queryset = TravelRecord.objects.all()

    def get_queryset(self):
        qs = TravelRecord.objects.all()
        params = self.request.query_params
        month = params.get("month")
        if month:
            start, end = local_month_range(parse_month(month))
            qs = qs.filter(occurred_at__gte=start, occurred_at__lt=end)
        record_status = params.get("status")
        if record_status in TravelRecord.Status.values:
            qs = qs.filter(status=record_status)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        # ?force=true omite la validación de doble toque en el alta.
        context["force"] = self.request.query_params.get("force") in ("true", "1")
        payment_types = getattr(self, "_payment_types", None)
        if payment_types is not None:
            context["payment_types"] = payment_types
        return context

    def list(self, request, *args, **kwargs):
        """Lista paginada; ``?payment_type=`` filtra el tipo DERIVADO."""
        queryset = self.filter_queryset(self.get_queryset())
        records = list(queryset)
        # La derivación se hace sobre el conjunto completo, no por página.
        self._payment_types = derive_payment_types(records)
        wanted = request.query_params.get("payment_type")
        if wanted in TravelRecord.PaymentType.values:
            records = [
                r for r in records if self._payment_types.get(r.pk) == wanted
            ]
        page = self.paginate_queryset(records)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        # Regla de negocio: no se borran viajes, se anulan.
        return Response(
            {"detail": "No se pueden eliminar viajes. Use PATCH para anularlos."},
            status=405,
        )

    @action(detail=False, methods=["get"], url_path="next-direction")
    def next_direction(self, request):
        """GET /api/travels/next-direction/: dirección sugerida (IDA/VUELTA)."""
        return Response({"direction": next_direction()})

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        """GET /api/travels/summary/?month=YYYY-MM (por defecto: mes actual)."""
        month = parse_month(request.query_params.get("month"))
        return Response(monthly_summary(month))

    @action(detail=False, methods=["get"], url_path="monthly-history")
    def monthly_history(self, request):
        """GET /api/travels/monthly-history/?months=6"""
        return Response(monthly_history(parse_months(request.query_params.get("months"))))

    @action(detail=False, methods=["get"], url_path="monthly-comparison")
    def monthly_comparison(self, request):
        """GET /api/travels/monthly-comparison/?months=6 (forma clásica)."""
        return Response(
            monthly_comparison(parse_months(request.query_params.get("months")))
        )
