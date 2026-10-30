"""Settings reestructurado: valores con vigencia, plantillas y feriados.

- Agrega los campos nuevos de Settings (max_daily_minutes, min_block_minutes,
  carry_over_deficit, forgotten_checkout_threshold_minutes, monthly_salary,
  hide_amounts) y los modelos SettingValue, WeekdayTemplate y Holiday.
- Migra los valores del singleton (weekly_target_minutes/monthly_trip_limit)
  a SettingValue con effective_from 2000-01-01 (cubre todo el historial).
- Crea las 7 plantillas de días: PREFERRED los días preferidos del
  singleton, OFF los fines de semana y RESERVE el resto.
- Al final quita del singleton los campos que migraron.
"""
from datetime import date, time

from django.db import migrations, models

import core.models


def seed_setting_values_and_templates(apps, schema_editor):
    SettingValue = apps.get_model("core", "SettingValue")
    WeekdayTemplate = apps.get_model("core", "WeekdayTemplate")
    Settings = apps.get_model("core", "Settings")

    cfg = Settings.objects.filter(pk=1).first()
    weekly_target = cfg.weekly_target_minutes if cfg else 1200
    trip_limit = cfg.monthly_trip_limit if cfg else 20
    preferred = set(cfg.preferred_workdays if cfg else [0, 1, 2, 3])

    effective_from = date(2000, 1, 1)
    SettingValue.objects.get_or_create(
        key="WEEKLY_TARGET_MINUTES",
        effective_from=effective_from,
        defaults={"value": weekly_target},
    )
    SettingValue.objects.get_or_create(
        key="MONTHLY_TRIP_LIMIT",
        effective_from=effective_from,
        defaults={"value": trip_limit},
    )

    for weekday in range(7):
        if weekday in preferred:
            kind = "PREFERRED"
        elif weekday >= 5:  # sábado y domingo
            kind = "OFF"
        else:
            kind = "RESERVE"
        WeekdayTemplate.objects.get_or_create(
            weekday=weekday,
            defaults={
                "kind": kind,
                "start_time": time(9, 0),
                "default_minutes": None,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        # 1) Campos nuevos del singleton.
        migrations.AddField(
            model_name="settings",
            name="carry_over_deficit",
            field=models.BooleanField(
                default=False,
                help_text="Arrastre del déficit entre semanas (guardado para próximos cambios).",
            ),
        ),
        migrations.AddField(
            model_name="settings",
            name="forgotten_checkout_threshold_minutes",
            field=models.PositiveIntegerField(
                default=60,
                help_text="Umbral para avisar de jornadas abiertas que se olvidaron de cerrar.",
            ),
        ),
        migrations.AddField(
            model_name="settings",
            name="hide_amounts",
            field=models.BooleanField(
                default=False,
                help_text="Ocultar importes en dinero en las pantallas.",
            ),
        ),
        migrations.AddField(
            model_name="settings",
            name="max_daily_minutes",
            field=models.PositiveIntegerField(
                default=420,
                help_text="Máximo de minutos propuestos para una jornada.",
            ),
        ),
        migrations.AddField(
            model_name="settings",
            name="min_block_minutes",
            field=models.PositiveIntegerField(
                default=60,
                help_text="Duración mínima de un bloque planificado.",
            ),
        ),
        migrations.AddField(
            model_name="settings",
            name="monthly_salary",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text="Salario mensual de la pasantía en ARS (opcional).",
                max_digits=12,
                null=True,
            ),
        ),
        # 2) Modelos nuevos.
        migrations.CreateModel(
            name="SettingValue",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(choices=[("WEEKLY_TARGET_MINUTES", "Objetivo semanal (minutos)"), ("MONTHLY_TRIP_LIMIT", "Cupo mensual de viajes")], max_length=64)),
                ("value", models.PositiveIntegerField()),
                ("effective_from", models.DateField()),
            ],
            options={
                "verbose_name": "Valor con vigencia",
                "verbose_name_plural": "Valores con vigencia",
                "ordering": ["key", "-effective_from"],
            },
        ),
        migrations.CreateModel(
            name="WeekdayTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("weekday", models.IntegerField(choices=[(0, "Lunes"), (1, "Martes"), (2, "Miércoles"), (3, "Jueves"), (4, "Viernes"), (5, "Sábado"), (6, "Domingo")], help_text="0 = lunes .. 6 = domingo.", unique=True)),
                ("kind", models.CharField(choices=[("PREFERRED", "Preferido"), ("RESERVE", "De reserva"), ("OFF", "Libre")], default="OFF", max_length=10)),
                ("start_time", models.TimeField(default=time(9, 0))),
                ("default_minutes", models.PositiveIntegerField(blank=True, help_text="Vacío = objetivo semanal vigente / días PREFERRED.", null=True)),
            ],
            options={
                "verbose_name": "Plantilla de día",
                "verbose_name_plural": "Plantillas de días",
                "ordering": ["weekday"],
            },
        ),
        migrations.CreateModel(
            name="Holiday",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("name", models.CharField(max_length=120)),
                ("kind", models.CharField(choices=[("NATIONAL", "Nacional"), ("BRIDGE", "Puente"), ("PERSONAL", "Personal")], default="NATIONAL", max_length=10)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Feriado",
                "verbose_name_plural": "Feriados",
                "ordering": ["date", "name"],
            },
        ),
        migrations.AddConstraint(
            model_name="settingvalue",
            constraint=models.UniqueConstraint(fields=("key", "effective_from"), name="unique_setting_value_per_key_and_date"),
        ),
        migrations.AddConstraint(
            model_name="holiday",
            constraint=models.UniqueConstraint(fields=("date", "name"), name="unique_holiday_date_and_name"),
        ),
        # 3) Datos: migra el singleton a SettingValue y crea las plantillas.
        migrations.RunPython(
            seed_setting_values_and_templates, migrations.RunPython.noop
        ),
        # 4) Campos que migraron a SettingValue / WeekdayTemplate.
        migrations.RemoveField(
            model_name="settings", name="daily_target_minutes"
        ),
        migrations.RemoveField(
            model_name="settings", name="monthly_trip_limit"
        ),
        migrations.RemoveField(
            model_name="settings", name="preferred_workdays"
        ),
        migrations.RemoveField(
            model_name="settings", name="weekly_target_minutes"
        ),
    ]
