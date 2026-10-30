"""Endpoints de `work`: hoy, semana, resumen mensual, jornadas y planes.

La vista de horas y la del planificador salen del MISMO cálculo
(``work.services.state.week_state``): UN servicio de computo, cero
lógica duplicada.
"""
from datetime import date

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from work.models import WorkPlan, WorkSession
from work.serializers import WorkPlanSerializer, WorkSessionPatchSerializer, WorkSessionSerializer
from work.services import sessions as sessions_service
from work.services import state
from work.services.time_utils import current_week_start, week_start_of


def parse_date(raw, default: date | None = None) -> date:
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return default or timezone.localdate()


def parse_month_param(raw) -> date:
    """?month=YYYY-MM (o YYYY-MM-DD) → primer día del mes (default: actual)."""
    if not raw:
        return timezone.localdate().replace(day=1)
    try:
        return date.fromisoformat(raw).replace(day=1)
    except ValueError:
        try:
            return date.fromisoformat(f"{raw}-01").replace(day=1)
        except ValueError:
            return timezone.localdate().replace(day=1)


def parse_week_param(raw) -> date:
    """?date=YYYY-MM-DD → lunes de esa semana (default: semana actual)."""
    if not raw:
        return current_week_start()
    try:
        return week_start_of(date.fromisoformat(raw))
    except (TypeError, ValueError):
        return current_week_start()


def _parse_dt_param(raw, field: str):
    """ISO 8601 → datetime aware (hora local por defecto); None si vacío."""
    if not raw:
        return None
    from datetime import datetime

    from django.utils import timezone as tz
    from rest_framework.exceptions import ValidationError

    try:
        value = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        raise ValidationError({field: "Fecha inválida (usá ISO 8601)."})
    if value.tzinfo is None:
        value = tz.make_aware(value, tz.get_default_timezone())
    return value


class TodayView(APIView):
    """GET /api/today/: estado de hoy (entrada, salida prevista, restantes).

    Incluye ``needs_checkout_confirmation`` (null o con el detalle de la
    jornada que olvidaron cerrar).
    """

    def get(self, request):
        return Response(state.today_state())


class WeekView(APIView):
    """GET /api/week/?date=YYYY-MM-DD: horas + plan de la semana.

    Por día: estado, marcas reales, plan (automático o manual) y
    diferencia; más el resumen (trabajado, restante, objetivo vigente,
    proyección de fin y minutos sin programar).
    """

    def get(self, request):
        week = parse_week_param(request.query_params.get("date"))
        return Response(state.week_state(week))


class HoursMonthlySummaryView(APIView):
    """GET /api/hours/monthly-summary/?month=YYYY-MM: horas por semana."""

    def get(self, request):
        month = parse_month_param(request.query_params.get("month"))
        return Response(state.monthly_summary(month))


class WorkSessionViewSet(viewsets.ReadOnlyModelViewSet):
    """Jornadas reales: consulta y control de entrada/salida.

    - GET  /api/work-sessions/            → historial paginado (filtros)
    - GET  /api/work-sessions/current/    → jornada abierta (o null)
    - POST /api/work-sessions/check-in/   → abrir jornada (ahora, o start_at)
    - POST /api/work-sessions/check-out/  → cerrar la abierta (end_at opcional)
    - POST /api/work-sessions/{id}/check-out/ → cerrar una específica (end_at)
    - POST /api/work-sessions/{id}/snooze/    → «Sigo trabajando» (+30 min)
    - PATCH /api/work-sessions/{id}/      → corrección manual

    No expone create/destroy: las jornadas solo se abren con check-in
    (POST a la lista responde 405).
    """

    serializer_class = WorkSessionSerializer
    queryset = WorkSession.objects.all()
    # El POST a la lista responde 405 (ReadOnlyModelViewSet no mapea create):
    # las jornadas solo se abren con check-in.
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action == "partial_update":
            return WorkSessionPatchSerializer
        return WorkSessionSerializer

    def get_queryset(self):
        qs = WorkSession.objects.all()
        params = self.request.query_params
        if params.get("month"):
            first = parse_month_param(params["month"])
            if first.month == 12:
                last = date(first.year + 1, 1, 1)
            else:
                last = date(first.year, first.month + 1, 1)
            qs = qs.filter(work_date__gte=first, work_date__lt=last)
        if params.get("week_start"):
            try:
                start = week_start_of(date.fromisoformat(params["week_start"]))
                from datetime import timedelta

                qs = qs.filter(
                    work_date__gte=start, work_date__lt=start + timedelta(days=7)
                )
            except ValueError:
                pass
        if params.get("date"):
            qs = qs.filter(work_date=params["date"])
        if params.get("status") in WorkSession.Status.values:
            qs = qs.filter(status=params["status"])
        return qs

    def partial_update(self, request, *args, **kwargs):
        """PATCH: corrección manual (sin las restricciones del check-out)."""
        session = self.get_object()
        serializer = self.get_serializer(session, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()  # el modelo rederive work_minutes y el estado
        return Response(WorkSessionSerializer(session).data)

    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request):
        """GET /api/work-sessions/current/: la jornada abierta (o null)."""
        session = sessions_service.get_open_session()
        # Se envuelve en un objeto: `Response(None)` no genera body JSON.
        return Response({"session": WorkSessionSerializer(session).data if session else None})

    @action(detail=False, methods=["post"], url_path="check-in")
    def check_in(self, request):
        """POST /api/work-sessions/check-in/ {start_at?, notes?}

        Abre la jornada de hoy con la hora del servidor (o la manual).
        """
        start_at = _parse_dt_param(request.data.get("start_at"), "start_at")
        session = sessions_service.check_in(start_at=start_at, notes=request.data.get("notes", ""))
        return Response(WorkSessionSerializer(session).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="check-out")
    def check_out(self, request):
        """POST /api/work-sessions/check-out/ {end_at?, confirm?}"""
        return self._do_check_out(
            sessions_service.get_open_session(),
            request,
        )

    @action(detail=True, methods=["post"], url_path="check-out")
    def check_out_by_id(self, request, pk=None):
        """POST /api/work-sessions/{id}/check-out/ {end_at, confirm?}"""
        return self._do_check_out(self.get_object(), request)

    def _do_check_out(self, session, request):
        end_at = _parse_dt_param(request.data.get("end_at"), "end_at")
        confirm = str(request.data.get("confirm", "")).lower() in ("1", "true", "yes")
        closed = sessions_service.check_out(end_at=end_at, session=session, confirm=confirm)
        return Response(WorkSessionSerializer(closed).data)

    @action(detail=True, methods=["post"], url_path="snooze")
    def snooze(self, request, pk=None):
        """POST /api/work-sessions/{id}/snooze/: «Sigo trabajando» (+30 min)."""
        session = sessions_service.snooze(self.get_object())
        return Response(WorkSessionSerializer(session).data)


class WorkPlanViewSet(viewsets.ModelViewSet):
    """Excepciones manuales del planificador, identificadas por FECHA.

    - GET    /api/work-plans/?week_start=YYYY-MM-DD → excepciones de la semana
    - PATCH  /api/work-plans/{date}/   → upsert por fecha (horario manual,
      bloqueo, día no disponible)
    - DELETE /api/work-plans/{date}/   → vuelve a automático ese día
    - POST   /api/work-plans/reset/?week=YYYY-MM-DD → limpia la semana

    El plan automático NO se persiste: se calcula al vuelo en /api/week/.
    """

    serializer_class = WorkPlanSerializer
    queryset = WorkPlan.objects.all()
    lookup_field = "work_date"
    lookup_value_regex = "[0-9]{4}-[0-9]{2}-[0-9]{2}"
    http_method_names = ["get", "patch", "delete", "head", "options", "post"]

    def get_queryset(self):
        qs = WorkPlan.objects.all()
        raw_week = (
            self.request.query_params.get("week_start")
            or self.request.query_params.get("week")
        )
        if raw_week:
            try:
                start = week_start_of(date.fromisoformat(raw_week))
                from datetime import timedelta

                qs = qs.filter(
                    work_date__gte=start, work_date__lt=start + timedelta(days=7)
                )
            except ValueError:
                pass
        return qs

    def create(self, request, *args, **kwargs):
        """POST: no se crean planes por JSON crudo; usá PATCH por fecha."""
        return Response(
            {"detail": "Usá PATCH /api/work-plans/{fecha}/ para cargar un día."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def update(self, request, *args, **kwargs):
        """PATCH por fecha: crea el día si no existe (upsert)."""
        instance = WorkPlan.objects.filter(
            work_date=self.kwargs["work_date"]
        ).first()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if instance is None:
            serializer.save(work_date=date.fromisoformat(kwargs["work_date"]))
        else:
            serializer.save()
        status_code = status.HTTP_200_OK if instance else status.HTTP_201_CREATED
        return Response(serializer.data, status=status_code)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """DELETE por fecha: elimina la excepción (vuelve a automático)."""
        instance = WorkPlan.objects.filter(
            work_date=self.kwargs["work_date"]
        ).first()
        if instance is None:
            return Response(
                {"detail": "Ese día no tiene excepción manual."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if instance.is_locked:
            return Response(
                {"detail": "La jornada está bloqueada. Desbloqueala para eliminarla."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="reset")
    def reset(self, request):
        """POST /api/work-plans/reset/?week=YYYY-MM-DD: vuelve a automático."""
        from datetime import timedelta

        week = parse_week_param(
            request.query_params.get("week") or request.data.get("week")
        )
        deleted, _ = WorkPlan.objects.filter(
            work_date__gte=week, work_date__lt=week + timedelta(days=7)
        ).delete()
        return Response({"week_start": week.isoformat(), "deleted": deleted})
