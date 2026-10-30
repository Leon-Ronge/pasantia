"""Serializadores del módulo de viajes.

``payment_type`` es de solo lectura y se deriva por mes calendario (nunca se
recibe en la escritura); ``occurred_at``/``amount``/``direction`` son
opcionales al crear y tienen defaults documentados.
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException

from core.models import Settings
from transport.models import TravelRecord
from transport.services import (
    local_date,
    next_direction,
    payment_type_of,
)

#: Segundos mínimos entre dos viajes de la misma dirección (anti doble tap).
DOUBLE_TAP_SECONDS = 60


class DoubleTapError(APIException):
    """409: doble toque (dos viajes de la misma dirección en < 60 s)."""

    status_code = 409
    default_code = "double_tap"
    default_detail = (
        "Ya hay un viaje de esta misma dirección registrado hace menos de "
        f"{DOUBLE_TAP_SECONDS} segundos. Esperá un momento o repita la "
        "carga con ?force=true."
    )


class TravelRecordSerializer(serializers.ModelSerializer):
    #: Derivado por mes calendario (services.derive_payment_types): solo
    #: lectura, no se guarda en la base.
    payment_type = serializers.SerializerMethodField()

    class Meta:
        model = TravelRecord
        fields = [
            "id",
            "occurred_at",
            "direction",
            "amount",
            "payment_type",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "payment_type", "created_at", "updated_at"]
        extra_kwargs = {
            # Opcionales al crear: ahora / dirección sugerida / tarifa vigente.
            "occurred_at": {"required": False},
            "direction": {"required": False},
            "amount": {"required": False},
        }

    def get_payment_type(self, obj) -> str:
        mapping = self.context.get("payment_types")
        if mapping is not None and obj.pk in mapping:
            return mapping[obj.pk]
        return payment_type_of(obj)

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("El importe debe ser mayor a cero.")
        return value

    def validate_occurred_at(self, value):
        if local_date(value) > timezone.localdate():
            raise serializers.ValidationError(
                "El momento del viaje no puede ser futuro."
            )
        return value

    def create(self, validated_data):
        now = timezone.now()
        # Defaults de alta: ahora, dirección sugerida y tarifa vigente.
        validated_data.setdefault("occurred_at", now)
        validated_data.setdefault("direction", next_direction())
        if "amount" not in validated_data:
            fare = Settings.load().current_fare
            if fare <= 0:
                raise serializers.ValidationError(
                    {
                        "amount": "Configure la tarifa vigente en Ajustes o envíe un importe."
                    }
                )
            validated_data["amount"] = fare

        # Anti doble tap: 409 si hay un viaje ACTIVE de la misma dirección
        # registrado en los últimos 60 s (se salta con ?force=true).
        if not self.context.get("force"):
            recent = TravelRecord.objects.filter(
                status=TravelRecord.Status.ACTIVE,
                direction=validated_data["direction"],
                occurred_at__gte=now - timedelta(seconds=DOUBLE_TAP_SECONDS),
                occurred_at__lte=now,
            ).exists()
            if recent:
                raise DoubleTapError()

        return super().create(validated_data)
