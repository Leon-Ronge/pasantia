from datetime import date, time

from django.db import models

#: Lunes = 0 ... Domingo = 6 (misma convención que datetime.date.weekday()).
WEEKDAY_CHOICES = [
    (0, "Lunes"),
    (1, "Martes"),
    (2, "Miércoles"),
    (3, "Jueves"),
    (4, "Viernes"),
    (5, "Sábado"),
    (6, "Domingo"),
]


def default_preferred_workdays():
    """Días de referencia iniciales: lunes a jueves.

    Ya no se usa en ningún modelo (los días viven en ``WeekdayTemplate``);
    se mantiene porque la migración inicial ``0001_initial`` la referencia.
    """
    return [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# Valores con vigencia (SettingValue)
# ---------------------------------------------------------------------------
#: Claves configurables con vigencia temporal.
SETTING_WEEKLY_TARGET_MINUTES = "WEEKLY_TARGET_MINUTES"
SETTING_MONTHLY_TRIP_LIMIT = "MONTHLY_TRIP_LIMIT"
SETTING_KEY_CHOICES = [
    (SETTING_WEEKLY_TARGET_MINUTES, "Objetivo semanal (minutos)"),
    (SETTING_MONTHLY_TRIP_LIMIT, "Cupo mensual de viajes"),
]

#: Fecha lo suficientemente vieja como para cubrir todo el historial.
INITIAL_EFFECTIVE_FROM = date(2000, 1, 1)

#: Valores por defecto si no existe ninguna fila vigente.
DEFAULT_SETTING_VALUES = {
    SETTING_WEEKLY_TARGET_MINUTES: 1200,
    SETTING_MONTHLY_TRIP_LIMIT: 20,
}


class Settings(models.Model):
    """Configuración global de la aplicación (registro único, pk=1).

    Es singleton porque la app es de uso personal y no distingue usuarios.
    El registro se crea perezosamente con ``Settings.load()``.

    El objetivo semanal y el cupo mensual de viajes NO viven acá: tienen
    vigencia temporal y se guardan en ``SettingValue`` (ver
    ``core.services.get_setting``).
    """

    SINGLETON_PK = 1

    max_daily_minutes = models.PositiveIntegerField(
        default=420,
        help_text="Máximo de minutos propuestos para una jornada.",
    )
    min_block_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Duración mínima de un bloque planificado.",
    )
    carry_over_deficit = models.BooleanField(
        default=False,
        help_text="Arrastre del déficit entre semanas (guardado para próximos cambios).",
    )
    forgotten_checkout_threshold_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Umbral para avisar de jornadas abiertas que se olvidaron de cerrar.",
    )
    current_fare = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Tarifa vigente del colectivo en ARS. Solo afecta viajes nuevos.",
    )
    monthly_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Salario mensual de la pasantía en ARS (opcional).",
    )
    hide_amounts = models.BooleanField(
        default=False,
        help_text="Ocultar importes en dinero en las pantallas.",
    )
    timezone = models.CharField(max_length=64, default="America/Argentina/Cordoba")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración"
        verbose_name_plural = "Configuración"

    def __str__(self):
        return "Configuración"

    @classmethod
    def load(cls) -> "Settings":
        """Devuelve el registro singleton, creándolo con valores por defecto."""
        obj, _created = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return obj


class SettingValue(models.Model):
    """Valor de una clave con vigencia temporal.

    El valor vigente para una fecha es el de mayor ``effective_from``
    menor o igual a esa fecha. Los cambios crean filas nuevas: el
    historial nunca se toca.
    """

    key = models.CharField(max_length=64, choices=SETTING_KEY_CHOICES)
    value = models.PositiveIntegerField()
    effective_from = models.DateField()

    class Meta:
        ordering = ["key", "-effective_from"]
        verbose_name = "Valor con vigencia"
        verbose_name_plural = "Valores con vigencia"
        constraints = [
            models.UniqueConstraint(
                fields=["key", "effective_from"],
                name="unique_setting_value_per_key_and_date",
            )
        ]

    def __str__(self):
        return f"{self.key} = {self.value} desde {self.effective_from}"

    @classmethod
    def seed_initial(cls):
        """Crea los valores iniciales si no existen (no pisa existentes)."""
        for key, value in DEFAULT_SETTING_VALUES.items():
            cls.objects.get_or_create(
                key=key,
                effective_from=INITIAL_EFFECTIVE_FROM,
                defaults={"value": value},
            )


class WeekdayTemplate(models.Model):
    """Plantilla de un día de la semana (7 filas: lunes a domingo).

    - kind PREFERRED: días que prioriza el planificador.
    - kind RESERVE: días de relleno si los preferidos no alcanzan.
    - kind OFF: días que nunca se planifican.
    - default_minutes vacío significa «objetivo semanal vigente /
      cantidad de días PREFERRED», en minutos enteros (se expone
      resuelto en ``resolved_minutes``).
    """

    class Kind(models.TextChoices):
        PREFERRED = "PREFERRED", "Preferido"
        RESERVE = "RESERVE", "De reserva"
        OFF = "OFF", "Libre"

    weekday = models.IntegerField(
        choices=WEEKDAY_CHOICES, unique=True, help_text="0 = lunes .. 6 = domingo."
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OFF)
    start_time = models.TimeField(default=time(9, 0))
    default_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Vacío = objetivo semanal vigente / días PREFERRED.",
    )

    class Meta:
        ordering = ["weekday"]
        verbose_name = "Plantilla de día"
        verbose_name_plural = "Plantillas de días"

    def __str__(self):
        return f"{self.get_weekday_display()} ({self.kind})"

    @classmethod
    def seed_initial(cls):
        """Crea las 7 plantillas iniciales si no existen.

        Lun–jue PREFERRED 09:00, vie RESERVE 09:00, sáb y dom OFF;
        default_minutes vacío en todos (duración derivada).
        """
        initial_kind = {
            0: cls.Kind.PREFERRED,
            1: cls.Kind.PREFERRED,
            2: cls.Kind.PREFERRED,
            3: cls.Kind.PREFERRED,
            4: cls.Kind.RESERVE,
            5: cls.Kind.OFF,
            6: cls.Kind.OFF,
        }
        for weekday, kind in initial_kind.items():
            cls.objects.get_or_create(
                weekday=weekday,
                defaults={"kind": kind, "start_time": time(9, 0), "default_minutes": None},
            )

    @property
    def resolved_minutes(self) -> int | None:
        """Duración efectiva del día (ver ``core.services.daily_minutes_for``)."""
        from core.services import daily_minutes_for

        return daily_minutes_for(self)


class Holiday(models.Model):
    """Día feriado (nacional, puente o personal). CRUD completo."""

    class Kind(models.TextChoices):
        NATIONAL = "NATIONAL", "Nacional"
        BRIDGE = "BRIDGE", "Puente"
        PERSONAL = "PERSONAL", "Personal"

    date = models.DateField()
    name = models.CharField(max_length=120)
    kind = models.CharField(
        max_length=10, choices=Kind.choices, default=Kind.NATIONAL
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "name"]
        verbose_name = "Feriado"
        verbose_name_plural = "Feriados"
        constraints = [
            models.UniqueConstraint(
                fields=["date", "name"], name="unique_holiday_date_and_name"
            )
        ]

    def __str__(self):
        return f"{self.date} · {self.name}"
