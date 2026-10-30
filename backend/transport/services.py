"""Reglas de negocio del módulo de transporte.

Reglas:
- La empresa proporciona N viajes por mes calendario (SettingValue
  MONTHLY_TRIP_LIMIT: cada mes usa el cupo vigente para el día 1 de ese mes).
- ``payment_type`` es DERIVADO, no se guarda: dentro de cada mes calendario
  (zona Córdoba) los viajes ACTIVE ordenados por ``(occurred_at, id)``; los
  primeros N son COMPANY y el resto PERSONAL. Así, anular un viaje o cargar
  uno con fecha anterior recalcula todo solo, y cambiar el cupo no altera
  meses pasados.
- Los viajes VOIDED no computan en ningún cálculo ni consumen cupo.
- El saldo restante del beneficio nunca puede ser negativo.
- El porcentaje sobre el sueldo es ``null`` si no hay salario cargado.
"""
from calendar import month_abbr
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

from core.models import SETTING_MONTHLY_TRIP_LIMIT, Settings
from core.services import get_setting
from transport.models import TravelRecord

ZERO = Decimal("0.00")


def month_bounds(month: date) -> tuple[date, date]:
    """(primer día inclusive, primer día del mes siguiente exclusive)."""
    first = month.replace(day=1)
    if first.month == 12:
        last = date(first.year + 1, 1, 1)
    else:
        last = date(first.year, first.month + 1, 1)
    return first, last


def local_date(value: datetime) -> date:
    """Fecha local (zona configurada) de un datetime almacenado en UTC."""
    if timezone.is_aware(value):
        return timezone.localtime(value).date()
    return value.date()  # defensivo: solo si llegara un datetime naive


def month_key(value: datetime) -> date:
    """Primer día del mes calendario (zona Córdoba) que contiene `value`."""
    return local_date(value).replace(day=1)


def local_month_range(first: date) -> tuple[datetime, datetime]:
    """Instantes aware [inicio, fin) del mes que empieza en `first`.

    Para filtrar ``occurred_at`` por mes calendario local (la columna está en
    UTC, así que comparar contra fechas crudas sería incorrecto).
    """
    start_day, _end_day = month_bounds(first)
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(start_day, time.min), tz)
    end = timezone.make_aware(datetime.combine(_end_day, time.min), tz)
    return start, end


def derive_payment_types(records) -> dict[int, str]:
    """Asigna COMPANY/PERSONAL por mes calendario (derived, no persistido).

    - Los cupos se asignan solo entre los viajes ACTIVE de cada mes,
      ordenados por ``(occurred_at, id)``: los primeros N son COMPANY.
    - Los VOIDED se muestran ordenados junto a los activos de su mes para
      indicar de qué tipo eran (no consumen cupo ni alteran la asignación).
    """
    groups: dict[date, list] = {}
    for record in records:
        groups.setdefault(month_key(record.occurred_at), []).append(record)

    mapping: dict[int, str] = {}
    for first, items in groups.items():
        limit = get_setting(SETTING_MONTHLY_TRIP_LIMIT, first)
        active = sorted(
            (r for r in items if r.is_active),
            key=lambda r: (r.occurred_at, r.pk),
        )
        for index, record in enumerate(active):
            mapping[record.pk] = (
                TravelRecord.PaymentType.COMPANY
                if index < limit
                else TravelRecord.PaymentType.PERSONAL
            )
        for record in (r for r in items if not r.is_active):
            ordered = sorted(
                active + [record], key=lambda r: (r.occurred_at, r.pk)
            )
            position = next(
                i for i, r in enumerate(ordered) if r.pk == record.pk
            )
            mapping[record.pk] = (
                TravelRecord.PaymentType.COMPANY
                if position < limit
                else TravelRecord.PaymentType.PERSONAL
            )
    return mapping


def payment_type_of(record: TravelRecord) -> str:
    """Tipo derivado de un registro puntual (para el detalle de un viaje)."""
    start, end = local_month_range(month_key(record.occurred_at))
    siblings = list(
        TravelRecord.objects.filter(
            status=TravelRecord.Status.ACTIVE,
            occurred_at__gte=start,
            occurred_at__lt=end,
        )
    )
    if not any(s.pk == record.pk for s in siblings):
        siblings = siblings + [record]
    return derive_payment_types(siblings)[record.pk]


def next_direction() -> str:
    """Dirección sugerida para el próximo viaje (GET /api/travels/next-direction/).

    - Último viaje ACTIVE de hoy → dirección opuesta (ida/vuelta alternadas).
    - Último viaje de un día anterior o sin viajes → IDA.
    """
    last = (
        TravelRecord.objects.filter(status=TravelRecord.Status.ACTIVE)
        .order_by("-occurred_at", "-id")
        .first()
    )
    if last is None:
        return TravelRecord.Direction.IDA
    if local_date(last.occurred_at) == timezone.localdate():
        if last.direction == TravelRecord.Direction.IDA:
            return TravelRecord.Direction.VUELTA
        return TravelRecord.Direction.IDA
    return TravelRecord.Direction.IDA


def salary_percentage(out_of_pocket: Decimal) -> float | None:
    """Gasto propio como porcentaje del salario mensual (null sin sueldo)."""
    salary = Settings.load().monthly_salary
    if salary is None or salary <= 0:
        return None
    value = (out_of_pocket / salary * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(value)


def _split_company_personal(records: list) -> tuple[list, list]:
    """Divide los viajes (ya ordenados y solo ACTIVE) según el cupo del mes."""
    first = month_key(records[0].occurred_at)
    limit = get_setting(SETTING_MONTHLY_TRIP_LIMIT, first)
    return records[:limit], records[limit:]


def monthly_summary(month: date) -> dict:
    """Resumen mensual (GET /api/travels/summary/?month=YYYY-MM).

    - used_company / remaining_company: viajes que consumen el beneficio y
      saldo restante (nunca negativo) según el cupo vigente de ese mes.
    - company_value: importe de los viajes cubiertos.
    - out_of_pocket_value: importe de los PERSONAL (los que pagué yo).
    - total_value: todos los viajes ACTIVE del mes.
    - salary_percentage: out_of_pocket_value / salario mensual × 100
      (null si no hay sueldo cargado).
    """
    first, _last = month_bounds(month)
    start, end = local_month_range(first)
    records = list(
        TravelRecord.objects.filter(
            status=TravelRecord.Status.ACTIVE,
            occurred_at__gte=start,
            occurred_at__lt=end,
        ).order_by("occurred_at", "id")
    )
    limit = get_setting(SETTING_MONTHLY_TRIP_LIMIT, first)
    company, personal = records[:limit], records[limit:]
    company_value = sum((r.amount for r in company), ZERO)
    out_of_pocket = sum((r.amount for r in personal), ZERO)
    return {
        "month": first.strftime("%Y-%m"),
        "used_company": len(company),
        "remaining_company": max(0, limit - len(company)),
        "limit": limit,
        "personal_count": len(personal),
        "total_count": len(records),
        "total_value": company_value + out_of_pocket,
        "company_value": company_value,
        "out_of_pocket_value": out_of_pocket,
        "salary_percentage": salary_percentage(out_of_pocket),
    }


def monthly_history(months: int = 6) -> list[dict]:
    """Historial mensual (GET /api/travels/monthly-history/?months=6).

    Un registro por mes con viajes ACTIVE, en orden cronológico, de los
    últimos `months` meses con registros: idas/vueltas, company/personal,
    importes, porcentaje sobre el sueldo y cupo vigente de ese mes.
    """
    months = max(1, min(months, 24))
    records = list(
        TravelRecord.objects.filter(status=TravelRecord.Status.ACTIVE).order_by(
            "occurred_at", "id"
        )
    )
    groups: dict[date, list] = {}
    for record in records:
        groups.setdefault(month_key(record.occurred_at), []).append(record)

    result: list[dict] = []
    for first in sorted(groups):
        items = groups[first]
        company, personal = _split_company_personal(items)
        company_value = sum((r.amount for r in company), ZERO)
        out_of_pocket = sum((r.amount for r in personal), ZERO)
        result.append(
            {
                "month": first.strftime("%Y-%m"),
                "ida_count": sum(
                    1 for r in items if r.direction == TravelRecord.Direction.IDA
                ),
                "vuelta_count": sum(
                    1 for r in items if r.direction == TravelRecord.Direction.VUELTA
                ),
                "company_count": len(company),
                "personal_count": len(personal),
                "total_value": company_value + out_of_pocket,
                "out_of_pocket_value": out_of_pocket,
                "salary_percentage": salary_percentage(out_of_pocket),
                "limit": get_setting(SETTING_MONTHLY_TRIP_LIMIT, first),
            }
        )
    return result[-months:]


def monthly_comparison(months: int = 6) -> list[dict]:
    """Comparación mensual (forma clásica, endpoint /monthly-comparison/).

    Se calcula desde el historial con los tipos derivados; conserva las
    claves históricas de la comparación.
    """
    result = []
    for item in monthly_history(months):
        year, month_number = item["month"].split("-")
        month_number = int(month_number)
        company_amount = item["total_value"] - item["out_of_pocket_value"]
        result.append(
            {
                "month": item["month"],
                "month_label": f"{month_number} {month_abbr[month_number]} {year}",
                "company_count": item["company_count"],
                "company_amount": company_amount,
                "personal_count": item["personal_count"],
                "personal_amount": item["out_of_pocket_value"],
            }
        )
    return result
