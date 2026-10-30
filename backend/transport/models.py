from django.db import models


class TravelRecord(models.Model):
    """Registro de un viaje en colectivo.

    - ``occurred_at``: momento del viaje en zona America/Argentina/Cordoba
      (se almacena en UTC, como todo con USE_TZ).
    - ``direction``: IDA o VUELTA.
    - ``amount``: Decimal exacto copiado de la tarifa vigente al crear
      (nunca float); si cambia la tarifa, los registros históricos
      conservan su importe original.
    - ``payment_type`` NO se guarda: se deriva por mes calendario (ver
      ``transport.services.derive_payment_types``): los primeros N viajes
      ACTIVE ordenados por (occurred_at, id) son COMPANY y el resto
      PERSONAL, donde N es el cupo vigente de ese mes.
    - La anulación es lógica (status=VOIDED) para no perder el historial.
    """

    class Direction(models.TextChoices):
        IDA = "IDA", "Ida"
        VUELTA = "VUELTA", "Vuelta"

    class PaymentType(models.TextChoices):
        #: Derivado (solo lectura en la API), no es un campo guardado.
        COMPANY = "COMPANY", "Cubierto por la empresa"
        PERSONAL = "PERSONAL", "Pagado por mí"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Activo"
        VOIDED = "VOIDED", "Anulado"

    occurred_at = models.DateTimeField()
    direction = models.CharField(
        max_length=10, choices=Direction.choices, default=Direction.IDA
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        verbose_name = "Viaje"
        verbose_name_plural = "Viajes"
        indexes = [
            models.Index(
                fields=["occurred_at", "status"], name="transport_occurred_status_idx"
            ),
        ]

    def __str__(self):
        return f"{self.occurred_at:%Y-%m-%d %H:%M} {self.direction} ${self.amount}"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE
