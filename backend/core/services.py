"""Servicios de configuración con vigencia temporal.

Reglas:
- ``get_setting(key, date)`` devuelve el valor vigente: la fila de
  ``SettingValue`` con el mayor ``effective_from`` menor o igual a esa
  fecha. Si no hay filas, devuelve el valor por defecto de la clave.
- Los cambios de valor crean filas nuevas (nunca se edita el historial).
- La duración diaria de un día de ``WeekdayTemplate`` se deriva del
  objetivo semanal vigente dividido la cantidad de días PREFERRED
  (minutos enteros), salvo que la plantilla tenga ``default_minutes``.
"""
from datetime import date

from django.utils import timezone

from core.models import (
    DEFAULT_SETTING_VALUES,
    SettingValue,
    WeekdayTemplate,
)


def get_setting(key: str, when: date | None = None) -> int:
    """Valor vigente de `key` para la fecha `when` (default: hoy)."""
    when = when or timezone.localdate()
    row = (
        SettingValue.objects.filter(key=key, effective_from__lte=when)
        .order_by("-effective_from")
        .first()
    )
    if row is not None:
        return row.value
    return DEFAULT_SETTING_VALUES[key]


def effective_from_for(key: str, when: date | None = None) -> date | None:
    """``effective_from`` del valor vigente (para mostrar en la API)."""
    when = when or timezone.localdate()
    row = (
        SettingValue.objects.filter(key=key, effective_from__lte=when)
        .order_by("-effective_from")
        .first()
    )
    return row.effective_from if row else None


def set_setting(key: str, value: int, effective_from: date) -> SettingValue:
    """Crea (o ajusta) la fila vigente desde `effective_from`.

    No toca las filas anteriores: solo se agrega/actualiza la fila con
    esa fecha de vigencia.
    """
    row, _created = SettingValue.objects.update_or_create(
        key=key,
        effective_from=effective_from,
        defaults={"value": value},
    )
    return row


def weekday_templates() -> list[WeekdayTemplate]:
    """Las 7 plantillas de días ordenadas de lunes a domingo."""
    return list(WeekdayTemplate.objects.order_by("weekday"))


def preferred_weekdays() -> list[int]:
    """Días marcados como PREFERRED (0 = lunes)."""
    return [t.weekday for t in weekday_templates() if t.kind == WeekdayTemplate.Kind.PREFERRED]


def count_plannable_days(templates: list[WeekdayTemplate] | None = None) -> int:
    """Cantidad de días PREFERRED + RESERVE (los OFF no se planifican)."""
    templates = templates if templates is not None else weekday_templates()
    return sum(
        1
        for t in templates
        if t.kind in (WeekdayTemplate.Kind.PREFERRED, WeekdayTemplate.Kind.RESERVE)
    )


def preferred_count(templates: list[WeekdayTemplate] | None = None) -> int:
    """Cantidad de días PREFERRED."""
    templates = templates if templates is not None else weekday_templates()
    return sum(1 for t in templates if t.kind == WeekdayTemplate.Kind.PREFERRED)


def daily_minutes_for(
    template: WeekdayTemplate,
    weekly_target: int | None = None,
    preferred_days: int | None = None,
) -> int | None:
    """Duración efectiva de un día de plantilla (minutos enteros).

    - default_minutes definido → ese valor.
    - Vacío → objetivo semanal / cantidad de días PREFERRED.
    - Días OFF → None (no se planifican).
    """
    if template.kind == WeekdayTemplate.Kind.OFF:
        return None
    if template.default_minutes is not None:
        return template.default_minutes
    if weekly_target is None:
        weekly_target = get_setting("WEEKLY_TARGET_MINUTES")
    if preferred_days is None:
        preferred_days = preferred_count()
    if preferred_days == 0:
        return 0
    return weekly_target // preferred_days
