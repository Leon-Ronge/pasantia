"""Serializadores de `core`.

El de Settings es compuesto: lee y actualiza en un solo request el
registro singleton + los valores con vigencia (SettingValue) + las
plantillas de días (WeekdayTemplate).
"""
from datetime import date, timedelta

from django.utils import timezone
from rest_framework import serializers

from core.models import (
    SETTING_MONTHLY_TRIP_LIMIT,
    SETTING_WEEKLY_TARGET_MINUTES,
    Holiday,
    Settings,
    WeekdayTemplate,
)
from core.services import (
    count_plannable_days,
    daily_minutes_for,
    effective_from_for,
    get_setting,
    set_setting,
)

#: Opciones de vigencia para el objetivo semanal.
APPLY_FROM_WEEK = ("this_week", "next_week")
#: Opciones de vigencia para el cupo mensual de viajes.
APPLY_FROM_MONTH = ("this_month", "next_month")


def week_start_of_today() -> date:
    """Lunes de la semana en curso (hora local configurada)."""
    return timezone.localdate() - timedelta(days=timezone.localdate().weekday())


def month_start_of_today() -> date:
    """Primer día del mes en curso."""
    return timezone.localdate().replace(day=1)


def apply_from_date(option: str, default: str) -> date:
    """Interpreta apply_from (this_week/next_week/this_month/next_month)."""
    option = option or default
    if option == "next_week":
        return week_start_of_today() + timedelta(days=7)
    if option == "this_month":
        return month_start_of_today()
    if option == "next_month":
        first = month_start_of_today()
        if first.month == 12:
            return date(first.year + 1, 1, 1)
        return date(first.year, first.month + 1, 1)
    # "this_week"
    return week_start_of_today()


def hours_label(minutes: int) -> str:
    """1200 → «20 h»; 2250 → «37,5 h»."""
    hours = minutes / 60
    text = f"{hours:g}".replace(".", ",")
    return f"{text} h"


class WeekdayTemplateSerializer(serializers.ModelSerializer):
    #: Duración efectiva calculada por el backend (null en días OFF sin
    #: default_minutes explícito). De solo lectura.
    resolved_minutes = serializers.SerializerMethodField()

    class Meta:
        model = WeekdayTemplate
        fields = ["weekday", "kind", "start_time", "default_minutes", "resolved_minutes"]

    def get_resolved_minutes(self, obj) -> int | None:
        target = self.context.get("weekly_target_minutes")
        preferred = self.context.get("preferred_days")
        return daily_minutes_for(obj, weekly_target=target, preferred_days=preferred)

    def validate_default_minutes(self, value):
        if value is not None and value <= 0:
            raise serializers.ValidationError(
                "La duración por defecto debe ser mayor a cero (o vacía para derivarla)."
            )
        return value


class SettingsSerializer(serializers.ModelSerializer):
    """Settings singleton + SettingValue vigente + plantillas de días.

    Campos de escritura adicionales:
    - weekly_target_minutes / monthly_trip_limit: se persisten como una
      fila NUEVA en SettingValue (el historial no se toca).
    - apply_from: vigencia del cambio
      ("this_week"/"next_week" para el objetivo semanal;
      "this_month"/"next_month" para el cupo de viajes).
    - weekday_templates: plantillas a actualizar (se identifican por
      weekday).
    """

    weekly_target_minutes = serializers.IntegerField(required=False)
    weekly_target_effective_from = serializers.DateField(read_only=True)
    monthly_trip_limit = serializers.IntegerField(required=False)
    monthly_trip_limit_effective_from = serializers.DateField(read_only=True)
    #: Plantillas a actualizar (parciales, identificadas por weekday).
    weekday_templates = serializers.ListField(
        child=serializers.DictField(), required=False, write_only=True
    )
    apply_from = serializers.CharField(required=False, write_only=True)

    class Meta:
        model = Settings
        fields = [
            "id",
            "max_daily_minutes",
            "min_block_minutes",
            "carry_over_deficit",
            "forgotten_checkout_threshold_minutes",
            "current_fare",
            "monthly_salary",
            "hide_amounts",
            "timezone",
            "updated_at",
            "weekly_target_minutes",
            "weekly_target_effective_from",
            "monthly_trip_limit",
            "monthly_trip_limit_effective_from",
            "weekday_templates",
            "apply_from",
        ]
        read_only_fields = ["id", "updated_at"]

    # ----------------------------------------------------------- validación
    def validate_max_daily_minutes(self, value):
        if value <= 0:
            raise serializers.ValidationError("El máximo diario debe ser mayor a cero.")
        return value

    def validate_min_block_minutes(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "El bloque mínimo debe ser mayor a cero."
            )
        return value

    def validate_forgotten_checkout_threshold_minutes(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "El umbral de jornada olvidada debe ser mayor a cero."
            )
        return value

    def validate_current_fare(self, value):
        if value < 0:
            raise serializers.ValidationError("La tarifa no puede ser negativa.")
        return value

    def validate_monthly_salary(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("El salario no puede ser negativo.")
        return value

    def validate_weekly_target_minutes(self, value):
        if value <= 0:
            raise serializers.ValidationError("El objetivo semanal debe ser mayor a cero.")
        return value

    def validate_monthly_trip_limit(self, value):
        if value <= 0:
            raise serializers.ValidationError("El límite mensual de viajes debe ser > 0.")
        return value

    def validate_weekday_templates(self, value):
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError(
                "Las plantillas deben ser una lista con los días a actualizar."
            )
        kind_field = serializers.ChoiceField(choices=WeekdayTemplate.Kind.choices)
        time_field = serializers.TimeField()
        minutes_field = serializers.IntegerField(min_value=1, allow_null=True)
        seen = set()
        for item in value:
            if not isinstance(item, dict):
                raise serializers.ValidationError("Cada plantilla debe ser un objeto.")
            try:
                weekday = int(item.get("weekday"))
            except (TypeError, ValueError):
                raise serializers.ValidationError(
                    "Cada plantilla necesita un weekday entre 0 (lunes) y 6 (domingo)."
                )
            if not 0 <= weekday <= 6:
                raise serializers.ValidationError(
                    "Cada plantilla necesita un weekday entre 0 (lunes) y 6 (domingo)."
                )
            if weekday in seen:
                raise serializers.ValidationError(
                    "No puede haber dos plantillas para el mismo día."
                )
            seen.add(weekday)
            try:
                if "kind" in item:
                    kind_field.run_validation(item["kind"])
                if "start_time" in item:
                    time_field.run_validation(item["start_time"])
                if "default_minutes" in item:
                    minutes_field.run_validation(item["default_minutes"])
            except serializers.ValidationError as exc:
                raise serializers.ValidationError(
                    f"Día {weekday}: {exc.detail[0] if exc.detail else 'dato inválido'}."
                )
        return value

    def validate_apply_from(self, value):
        allowed = APPLY_FROM_WEEK + APPLY_FROM_MONTH
        if value not in allowed:
            raise serializers.ValidationError(
                f"apply_from debe ser uno de: {', '.join(allowed)}."
            )
        return value

    def validate(self, attrs):
        """Valida la configuración RESULTANTE después del parche.

        Regla de factibilidad (respuesta 422 cuando no se cumple):
            max_daily_minutes * (días PREFERRED + RESERVE)
            >= objetivo semanal vigente
        """
        attrs = super().validate(attrs)

        # Estado resultante (en memoria) para validar antes de persistir.
        max_daily = attrs.get("max_daily_minutes", self.instance.max_daily_minutes)
        templates_in = attrs.get("weekday_templates")
        current_templates = WeekdayTemplate.objects.order_by("weekday")
        if templates_in is None:
            resulting = list(current_templates)
        else:
            by_weekday = {t.weekday: t for t in current_templates}
            resulting = []
            for item in templates_in:
                existing = by_weekday.get(int(item["weekday"]))
                if existing is None:
                    continue  # weekday inválido ya filtrado por validate
                for field in ("kind", "start_time", "default_minutes"):
                    if field in item:
                        setattr(existing, field, item[field])
                resulting.append(existing)
            for weekday, existing in by_weekday.items():
                if weekday not in {int(i["weekday"]) for i in templates_in}:
                    resulting.append(existing)
            resulting.sort(key=lambda t: t.weekday)

        plannable = count_plannable_days(resulting)
        target = attrs.get("weekly_target_minutes")
        if target is None:
            target = get_setting(SETTING_WEEKLY_TARGET_MINUTES)
        capacity = max_daily * plannable
        if plannable == 0 or capacity < target:
            raise serializers.ValidationError(
                {
                    "weekly_target_minutes": serializers.ErrorDetail(
                        f"Con {hours_label(target)} por semana necesitás subir el "
                        f"máximo diario o sumar días (hoy: {max_daily} min × "
                        f"{plannable} días = {capacity} min).",
                        code="not_feasible",
                    )
                }
            )
        return attrs

    # --------------------------------------------------------- persistencia
    def update(self, instance, validated_data):
        apply_from = validated_data.pop("apply_from", None) or ""
        templates_in = validated_data.pop("weekday_templates", None)
        new_weekly = validated_data.pop("weekly_target_minutes", None)
        new_limit = validated_data.pop("monthly_trip_limit", None)

        # 1) Campos simples del singleton.
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        # 2) Valores con vigencia: fila nueva, sin tocar el historial.
        today = timezone.localdate()
        if new_weekly is not None and new_weekly != get_setting(
            SETTING_WEEKLY_TARGET_MINUTES, today
        ):
            option = apply_from if apply_from in APPLY_FROM_WEEK else "this_week"
            set_setting(SETTING_WEEKLY_TARGET_MINUTES, new_weekly, apply_from_date(option, "this_week"))
        if new_limit is not None and new_limit != get_setting(
            SETTING_MONTHLY_TRIP_LIMIT, today
        ):
            option = apply_from if apply_from in APPLY_FROM_MONTH else "this_month"
            set_setting(SETTING_MONTHLY_TRIP_LIMIT, new_limit, apply_from_date(option, "this_month"))

        # 3) Plantillas de días (solo las enviadas, identificadas por weekday).
        if templates_in is not None:
            by_weekday = {t.weekday: t for t in WeekdayTemplate.objects.all()}
            for item in templates_in:
                existing = by_weekday.get(int(item["weekday"]))
                if existing is None:
                    continue
                for field in ("kind", "start_time", "default_minutes"):
                    if field in item:
                        setattr(existing, field, item[field])
                existing.save()

        return instance

    # --------------------------------------------------------- representación
    def to_representation(self, instance) -> dict:
        today = timezone.localdate()
        templates = list(WeekdayTemplate.objects.order_by("weekday"))
        target = get_setting(SETTING_WEEKLY_TARGET_MINUTES, today)
        preferred = sum(
            1 for t in templates if t.kind == WeekdayTemplate.Kind.PREFERRED
        )
        context = {
            "weekly_target_minutes": target,
            "preferred_days": preferred,
        }
        return {
            "id": instance.id,
            "max_daily_minutes": instance.max_daily_minutes,
            "min_block_minutes": instance.min_block_minutes,
            "carry_over_deficit": instance.carry_over_deficit,
            "forgotten_checkout_threshold_minutes": (
                instance.forgotten_checkout_threshold_minutes
            ),
            "current_fare": f"{instance.current_fare:.2f}",
            "monthly_salary": (
                None if instance.monthly_salary is None
                else f"{instance.monthly_salary:.2f}"
            ),
            "hide_amounts": instance.hide_amounts,
            "timezone": instance.timezone,
            "updated_at": instance.updated_at,
            "weekly_target_minutes": target,
            "weekly_target_effective_from": effective_from_for(
                SETTING_WEEKLY_TARGET_MINUTES, today
            ),
            "monthly_trip_limit": get_setting(SETTING_MONTHLY_TRIP_LIMIT, today),
            "monthly_trip_limit_effective_from": effective_from_for(
                SETTING_MONTHLY_TRIP_LIMIT, today
            ),
            "weekday_templates": WeekdayTemplateSerializer(
                templates, many=True, context=context
            ).data,
        }


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ["id", "date", "name", "kind", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("El nombre del feriado no puede estar vacío.")
        return value.strip()
