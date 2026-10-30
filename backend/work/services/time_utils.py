"""Utilidades de fechas: semana laboral lunes → domingo (hora local)."""
from datetime import date, timedelta

from django.utils import timezone


def week_start_of(day: date) -> date:
    """Lunes de la semana a la que pertenece `day` (lunes=0)."""
    return day - timedelta(days=day.weekday())


def week_bounds(day: date) -> tuple[date, date]:
    """(lunes inclusive, lunes siguiente exclusive) de la semana de `day`."""
    start = week_start_of(day)
    return start, start + timedelta(days=7)


def current_week_start() -> date:
    """Lunes de la semana en curso (hora configurada por Django: Córdoba)."""
    return week_start_of(timezone.localdate())


def add_days(day: date, days: int) -> date:
    return day + timedelta(days=days)
