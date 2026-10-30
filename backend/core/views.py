from datetime import date

from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Holiday, Settings
from core.serializers import HolidaySerializer, SettingsSerializer
from transport.services import monthly_summary
from work.services.sessions import get_open_session, session_to_dict
from work.services.state import suggest_next_shift, weekly_balance
from work.services.time_utils import current_week_start


class SettingsView(APIView):
    """GET /api/settings/ y PATCH /api/settings/ (configuración combinada).

    Lee y actualiza el singleton + los valores con vigencia (objetivo
    semanal y cupo de viajes) + las plantillas de días en un solo request.
    """

    def get(self, request):
        return Response(SettingsSerializer(Settings.load()).data)

    def patch(self, request):
        serializer = SettingsSerializer(
            Settings.load(), data=request.data, partial=True
        )
        try:
            serializer.is_valid(raise_exception=True)
        except ValidationError as exc:
            # 422: el objetivo semanal no entra en el máximo diario.
            detail = exc.detail
            errors = detail if isinstance(detail, dict) else {}
            for field_errors in errors.values():
                for error in field_errors if isinstance(field_errors, list) else [field_errors]:
                    if getattr(error, "code", None) == "not_feasible":
                        return Response({"detail": str(error)}, status=422)
            raise
        serializer.save()
        return Response(serializer.data)


class DashboardView(APIView):
    """GET /api/dashboard/: agregado del Dashboard principal.

    Resumen de la semana actual (horas, objetivo, déficit), déficit
    acumulado, próxima jornada planificada / sugerida y el resumen de
    transporte del mes en curso. Todo derivado de datos reales.
    """

    def get(self, request):
        week_start = current_week_start()
        balance = weekly_balance(week_start)
        open_session = get_open_session()

        month = date.today().replace(day=1)
        transport = monthly_summary(month)

        data = {
            "week_start": week_start.isoformat(),
            "weekly_target_minutes": balance["weekly_target_minutes"],
            "worked_minutes": balance["worked_minutes"],
            "remaining_minutes": balance["remaining_minutes"],
            "weekly_delta": balance["weekly_delta"],
            "opening_deficit_minutes": balance["opening_deficit_minutes"],
            "accumulated_deficit_minutes": balance["opening_deficit_minutes"],
            "closing_deficit_minutes": balance["closing_deficit_minutes"],
            "deficit_kind": balance["deficit_kind"],
            "progress_ratio": balance["progress_ratio"],
            "open_session": session_to_dict(open_session) if open_session else None,
            "next_shift": suggest_next_shift(week_start),
            "transport": transport,
        }
        return Response(data)


class HolidayViewSet(viewsets.ModelViewSet):
    """CRUD de feriados: /api/holidays/ (todos editables y eliminables).

    Carga masiva: `python manage.py import_holidays <año>` (ver comando).
    """

    serializer_class = HolidaySerializer
    queryset = Holiday.objects.all()

    def get_queryset(self):
        qs = Holiday.objects.all()
        year = self.request.query_params.get("year")
        if year:
            try:
                qs = qs.filter(date__year=int(year))
            except (TypeError, ValueError):
                pass
        return qs

    def create(self, request, *args, **kwargs):
        """POST: acepta también year/month/day además de `date`."""
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        if "date" not in data and {"year", "month", "day"} <= set(data):
            try:
                data["date"] = date(
                    int(data["year"]), int(data["month"]), int(data["day"])
                ).isoformat()
            except (TypeError, ValueError):
                return Response(
                    {"date": ["Fecha inválida: usá date=YYYY-MM-DD."]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="import", url_name="import")
    def import_year(self, request):
        """POST /api/holidays/import/ {year}: importa el año desde la API pública.

        Reutiliza el comando `import_holidays`; respeta los feriados
        PERSONAL y actualiza los existentes. Devuelve el total de
        feriados del año quedaron guardados.
        """
        raw = request.data.get("year")
        try:
            year = int(raw)
        except (TypeError, ValueError):
            return Response(
                {"year": ["Ingresá un año válido (p. ej. 2026)."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not 2000 <= year <= 2100:
            return Response(
                {"year": ["El año debe estar entre 2000 y 2100."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            call_command("import_holidays", str(year))
        except CommandError as exc:
            return Response(
                {"detail": str(exc), "code": "IMPORT_FAILED"},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except Exception as exc:  # red caída o fuente inalcanzable
            return Response(
                {
                    "detail": f"No se pudo consultar la fuente de feriados: {exc}",
                    "code": "IMPORT_SOURCE_ERROR",
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        total = Holiday.objects.filter(date__year=year).count()
        return Response({"year": year, "count": total})
