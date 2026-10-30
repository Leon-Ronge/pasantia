"""Acceso a datos para el motor puro (``work.services.engine``).

Acá vive todo lo que toca la base de datos y el reloj: el motor nunca lo
hace. La regla es simple: ``state`` arma los inputs (dataclasses), el
motor calcula y ``state`` empaqueta el resultado. Sin lógica de negocio
duplicada: horas y planificador salen del MISMO cálculo (``build_week``).
"""
from datetime import date, datetime, timedelta

from django.utils import timezone

from core.models import SETTING_WEEKLY_TARGET_MINUTES, Settings, Holiday, WeekdayTemplate
from core.services import get_setting
from work.models import WorkPlan, WorkSession
from work.services import engine
from work.services.time_utils import current_week_start, week_start_of


def load_templates() -> dict[int, engine.TemplateInput]:
    return {
        t.weekday: engine.TemplateInput(
            weekday=t.weekday,
            kind=t.kind,
            start_time=t.start_time,
            default_minutes=t.default_minutes,
        )
        for t in WeekdayTemplate.objects.all()
    }


def load_exceptions(week_start: date) -> dict[date, engine.ExceptionInput]:
    end = week_start + timedelta(days=7)
    return {
        p.work_date: engine.ExceptionInput(
            work_date=p.work_date,
            planned_start=p.planned_start,
            planned_minutes=p.planned_minutes,
            is_locked=p.is_locked,
            is_available=p.is_available,
        )
        for p in WorkPlan.objects.filter(work_date__gte=week_start, work_date__lt=end)
    }


def load_holidays(week_start: date) -> dict[date, str]:
    end = week_start + timedelta(days=7)
    return {
        h.date: h.name
        for h in Holiday.objects.filter(date__gte=week_start, date__lt=end)
    }


def load_sessions(week_start: date) -> list[engine.SessionInput]:
    """Jornadas de la semana + la jornada abierta aunque caiga fuera.

    La abierta se incluye siempre para que el motor detecte una jornada
    olvidada del día anterior (incluso si ese día pertenece a la semana
    previa).
    """
    end = week_start + timedelta(days=7)
    qs = WorkSession.objects.filter(work_date__gte=week_start, work_date__lt=end)
    open_session = WorkSession.objects.filter(
        status=WorkSession.Status.IN_PROGRESS
    ).first()
    rows = list(qs)
    if open_session is not None and open_session.work_date < week_start:
        rows.append(open_session)
    return [
        engine.SessionInput(
            id=s.id,
            work_date=s.work_date,
            start_at=s.start_at,
            end_at=s.end_at,
            snoozed_until=s.snoozed_until,
        )
        for s in rows
    ]


def build_week_input(
    week_start: date | None = None,
    now: datetime | None = None,
    include_deficit: bool = True,
) -> engine.WeekInput:
    """Arma todos los inputs de la semana desde la base de datos.

    ``include_deficit=False`` evita el cálculo recursivo del déficit
    (lo usan las funciones que alimentan ese mismo cálculo).
    """
    start = week_start_of(week_start or current_week_start())
    #: `now` en hora LOCAL (Córdoba): el motor emite las salidas en esa zona.
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    cfg = Settings.load()
    return engine.WeekInput(
        week_start=start,
        today=today,
        now=now,
        target_minutes=get_setting(SETTING_WEEKLY_TARGET_MINUTES, start),
        sessions=load_sessions(start),
        exceptions=load_exceptions(start),
        templates=load_templates(),
        holidays=load_holidays(start),
        max_daily_minutes=cfg.max_daily_minutes,
        min_block_minutes=cfg.min_block_minutes,
        carry_over_deficit=cfg.carry_over_deficit,
        opening_deficit_minutes=opening_deficit_for(start)
        if (include_deficit and cfg.carry_over_deficit)
        else 0,
        forgotten_threshold_minutes=cfg.forgotten_checkout_threshold_minutes,
    )


def week_state(week: date | None = None) -> dict:
    """Vista semanal completa: horas + plan + hoy (un solo cálculo)."""
    return engine.build_week(build_week_input(week))


def today_state() -> dict:
    """Estado de hoy para /api/today/ (reutiliza el cálculo semanal)."""
    return week_state()["today"]


def worked_minutes_for_week(week_start: date) -> int:
    """Minutos efectivos de la semana (motor: pendientes acotados)."""
    data = build_week_input(week_start, include_deficit=False)
    week_days = {data.week_start + timedelta(days=i) for i in range(7)}
    return sum(
        engine.effective_minutes(data, s)
        for s in data.sessions
        if s.work_date in week_days
    )


def opening_deficit_for(week_start: date) -> int:
    """Déficit acumulado al comenzar la semana (mismo modelo que antes):
    cada semana usa su objetivo vigente y el saldo nunca queda negativo."""
    start = week_start_of(week_start)
    first = WorkSession.objects.order_by("work_date").first()
    if first is None:
        return 0
    cursor = week_start_of(first.work_date)
    deficit = 0
    while cursor < start:
        target = get_setting(SETTING_WEEKLY_TARGET_MINUTES, cursor)
        delta = worked_minutes_for_week(cursor) - target
        deficit = max(0, deficit - delta)
        cursor += timedelta(days=7)
    return deficit


def weekly_balance(week_start: date | None = None, target: int | None = None) -> dict:
    """Balance de la semana (lo consume el Dashboard).

    Mantiene la misma forma que el servicio viejo para no romper al
    frontend, pero los minutos salen del motor (una sola lógica).
    """
    start = week_start_of(week_start or current_week_start())
    if target is None:
        target = get_setting(SETTING_WEEKLY_TARGET_MINUTES, start)
    end = start + timedelta(days=7)
    worked = worked_minutes_for_week(start)
    opening = opening_deficit_for(start)
    delta = worked - target
    closing = max(0, opening - delta)
    today = timezone.localdate()
    is_open = today < end
    return {
        "week_start": start.isoformat(),
        "week_end": (end - timedelta(days=1)).isoformat(),
        "worked_minutes": worked,
        "weekly_target_minutes": target,
        "weekly_delta": delta,
        "opening_deficit_minutes": opening,
        "closing_deficit_minutes": closing,
        "remaining_minutes": max(0, target - worked),
        "progress_ratio": round(min(1.0, worked / target), 4) if target else 0.0,
        "is_open": is_open,
        "deficit_kind": "projected" if is_open else "definitive",
    }


def monthly_summary(month: date) -> dict:
    """Horas por semana y total del mes (para /api/hours/monthly-summary/)."""
    first = month.replace(day=1)
    if first.month == 12:
        next_month = date(first.year + 1, 1, 1)
    else:
        next_month = date(first.year, first.month + 1, 1)

    weeks: set[date] = set()
    for s in WorkSession.objects.filter(
        work_date__gte=first, work_date__lt=next_month
    ).values_list("work_date", flat=True):
        weeks.add(week_start_of(s))
    today = timezone.localdate()
    if first <= today < next_month:
        weeks.add(week_start_of(today))

    result = []
    total = 0
    for week in sorted(weeks):
        worked = worked_minutes_for_week(week)
        total += worked
        result.append(
            {
                "week_start": week.isoformat(),
                "week_end": (week + timedelta(days=6)).isoformat(),
                "worked_minutes": worked,
                "target_minutes": get_setting(SETTING_WEEKLY_TARGET_MINUTES, week),
            }
        )
    return {
        "month": first.strftime("%Y-%m"),
        "weeks": result,
        "total_worked_minutes": total,
        "total_target_minutes": sum(w["target_minutes"] for w in result),
    }


def suggest_next_shift(week_start: date | None = None) -> dict | None:
    """Próxima jornada para el Dashboard: el primer día con plan.

    Salida compatible con el formato viejo: {date, planned_start,
    planned_minutes, source}.
    """
    state = week_state(week_start)
    today = timezone.localdate()
    for day in state["days"]:
        if day["planned_minutes"] is None or day["planned_start"] is None:
            continue
        if day["date"] < today.isoformat():
            continue
        if day["status"] in (engine.DAY_HOLIDAY, engine.DAY_OFF, engine.DAY_MISSED):
            continue
        if day["status"] in (engine.DAY_DONE, engine.DAY_PENDING):
            continue
        source = "plan" if day["is_manual"] else "sugerido"
        return {
            "date": day["date"],
            "planned_start": day["planned_start"],
            "planned_minutes": day["planned_minutes"],
            "source": source,
        }
    return None
