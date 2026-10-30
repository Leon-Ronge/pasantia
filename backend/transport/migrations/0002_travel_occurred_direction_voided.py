"""TravelRecord: occurred_at + direction, payment_type pasa a ser derivado.

Conserva los datos existentes:
- ``direction``: todos los registros pasan a IDA (default del AddField).
- ``occurred_at``: se calcula desde ``travel_date`` a las 12:00 (hora de
  America/Argentina/Cordoba).
- ``status``: ANNULLED → VOIDED.
- Se elimina ``payment_type`` guardado (de ahora en más se deriva; el valor
  viejo ya no se necesita para ningún cálculo).

Reverso aproximado: los pasos de datos no se deshacen (RunPython.noop).
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import migrations, models

CORDOBA = ZoneInfo("America/Argentina/Cordoba")


def migrate_travels(apps, schema_editor):
    TravelRecord = apps.get_model("transport", "TravelRecord")
    for record in TravelRecord.objects.all().iterator():
        day = record.travel_date
        # Fecha antigua (date) → mediodía en zona Córdoba (aware, se guarda en UTC).
        record.occurred_at = datetime(
            day.year, day.month, day.day, 12, 0, tzinfo=CORDOBA
        )
        if record.status == "ANNULLED":
            record.status = "VOIDED"
        record.save(update_fields=["occurred_at", "status"])


class Migration(migrations.Migration):

    dependencies = [
        ("transport", "0001_initial"),
    ]

    operations = [
        # 1) Campos nuevos (occurred_at llega null=True hasta migrar los datos).
        migrations.AddField(
            model_name="travelrecord",
            name="direction",
            field=models.CharField(
                choices=[("IDA", "Ida"), ("VUELTA", "Vuelta")],
                default="IDA",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="travelrecord",
            name="occurred_at",
            field=models.DateTimeField(null=True),
        ),
        # 2) Datos existentes: fecha → mediodía Córdoba y ANNULLED → VOIDED.
        migrations.RunPython(migrate_travels, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="travelrecord",
            name="occurred_at",
            field=models.DateTimeField(),
        ),
        migrations.AlterField(
            model_name="travelrecord",
            name="status",
            field=models.CharField(
                choices=[("ACTIVE", "Activo"), ("VOIDED", "Anulado")],
                default="ACTIVE",
                max_length=10,
            ),
        ),
        # 3) Índice y orden por el nuevo campo de fecha.
        migrations.RemoveIndex(
            model_name="travelrecord", name="transport_t_travel__724e0f_idx"
        ),
        migrations.AddIndex(
            model_name="travelrecord",
            index=models.Index(
                fields=["occurred_at", "status"], name="transport_occurred_status_idx"
            ),
        ),
        migrations.AlterModelOptions(
            name="travelrecord",
            options={
                "ordering": ["-occurred_at", "-id"],
                "verbose_name": "Viaje",
                "verbose_name_plural": "Viajes",
            },
        ),
        # 4) payment_type deja de guardarse (se deriva en la API).
        migrations.RemoveField(
            model_name="travelrecord", name="payment_type"
        ),
        migrations.RemoveField(
            model_name="travelrecord", name="travel_date"
        ),
    ]
