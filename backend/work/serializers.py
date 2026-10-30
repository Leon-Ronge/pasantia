"""Serializadores de `work`.

Las jornadas se crean SOLO vía check-in (el viewset no expone create):
acá quedan la lectura y la corrección manual (PATCH).
"""
from rest_framework import serializers

from work.models import WorkPlan, WorkSession
from work.services.sessions import elapsed_minutes


class WorkSessionSerializer(serializers.ModelSerializer):
    """Jornada real. El estado y la duración los gestiona el backend.

    - elapsed_minutes: minutos transcurridos (en vivo) de una jornada
      abierta; para jornadas cerradas devuelve worked_minutes.
    """

    elapsed_minutes = serializers.SerializerMethodField()

    class Meta:
        model = WorkSession
        fields = [
            "id",
            "work_date",
            "start_at",
            "end_at",
            "snoozed_until",
            "worked_minutes",
            "elapsed_minutes",
            "notes",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "work_date",
            "snoozed_until",
            "worked_minutes",
            "status",
            "created_at",
            "updated_at",
        ]

    def get_elapsed_minutes(self, obj):
        return elapsed_minutes(obj)


class WorkSessionPatchSerializer(serializers.ModelSerializer):
    """Corrección manual de una jornada (PATCH /api/work-sessions/{id}/).

    Solo campos editables; la duración se rederiva de las marcas.
    """

    class Meta:
        model = WorkSession
        fields = ["start_at", "end_at", "notes"]

    def validate(self, attrs):
        start = attrs.get("start_at", self.instance.start_at)
        end = attrs.get("end_at", self.instance.end_at)
        if end is not None and end <= start:
            raise serializers.ValidationError(
                {"end_at": "La salida no puede ser anterior o igual a la entrada."}
            )
        return attrs


class WorkPlanSerializer(serializers.ModelSerializer):
    """Excepción manual de un día (WorkPlan).

    Se crea/edita por FECHA (upsert en la vista); is_locked protege la
    fila de cambios accidentales.
    """

    class Meta:
        model = WorkPlan
        fields = [
            "id",
            "work_date",
            "planned_start",
            "planned_minutes",
            "is_locked",
            "is_available",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "work_date", "created_at", "updated_at"]

    def validate(self, attrs):
        instance = self.instance
        is_available = attrs.get(
            "is_available", instance.is_available if instance else True
        )
        planned_minutes = attrs.get("planned_minutes")
        if planned_minutes is None:
            # Default: el horario existente; en un día nuevo, 300 (o 0 si
            # se marca como no disponible).
            planned_minutes = (
                instance.planned_minutes if instance else (300 if is_available else 0)
            )
            attrs["planned_minutes"] = planned_minutes
        if planned_minutes > 0 and not is_available:
            raise serializers.ValidationError(
                {"planned_minutes": "Un día no disponible no puede tener minutos planificados."}
            )
        if planned_minutes > 1440:
            raise serializers.ValidationError(
                {"planned_minutes": "Una jornada no puede superar 1440 minutos."}
            )
        return attrs
