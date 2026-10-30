from datetime import time

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class WorkSession(models.Model):
    """Jornada real de pasantía.

    Estados:
    - IN_PROGRESS: jornada en curso (start_at definido, end_at vacío).
    - COMPLETED: jornada cerrada (start_at y end_at definidos).
    - PENDING: reservado para uso futuro; la API lo gestiona automáticamente.

    La duración (worked_minutes) se deriva SIEMPRE de las marcas de tiempo
    en save(): nunca se confía en un valor enviado por el cliente. Mientras
    la jornada está en curso, worked_minutes queda en 0 y el frontend muestra
    el tiempo transcurrido calculado con start_at.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        IN_PROGRESS = "IN_PROGRESS", "En curso"
        COMPLETED = "COMPLETED", "Completada"

    #: Una sola jornada por día laborable (derivada de la hora de entrada).
    work_date = models.DateField(unique=True)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField(null=True, blank=True)
    #: "Sigo trabajando": posibilita la salida prevista (snooze de 30 min).
    snoozed_until = models.DateTimeField(null=True, blank=True)
    worked_minutes = models.PositiveIntegerField(default=0)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.IN_PROGRESS
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-work_date", "-start_at"]
        verbose_name = "Jornada"
        verbose_name_plural = "Jornadas"
        constraints = [
            # Garantiza a nivel de base de datos que solo puede haber UNA
            # jornada abierta a la vez.
            models.UniqueConstraint(
                fields=["status"],
                condition=Q(status="IN_PROGRESS"),
                name="only_one_open_session",
            ),
        ]

    def __str__(self):
        return f"{self.work_date} {self.start_at:%H:%M} ({self.status})"

    def clean(self):
        from django.core.exceptions import ValidationError

        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "La salida no puede ser anterior a la entrada."})

    @property
    def is_open(self) -> bool:
        return self.status == self.Status.IN_PROGRESS

    def compute_worked_minutes(self) -> int:
        """Duración efectiva en minutos enteros, derivada de las marcas."""
        if self.start_at and self.end_at:
            delta = self.end_at - self.start_at
            return max(0, int(delta.total_seconds() // 60))
        return 0

    def save(self, *args, **kwargs):
        if self.start_at:
            # La fecha de la jornada se deriva de la entrada (hora local).
            self.work_date = timezone.localtime(self.start_at).date()
        if self.end_at:
            self.status = self.Status.COMPLETED
        elif self.start_at:
            self.status = self.Status.IN_PROGRESS
        self.worked_minutes = self.compute_worked_minutes()
        super().save(*args, **kwargs)


class WorkPlan(models.Model):
    """Jornada planificada (una fila por fecha de la semana laboral).

    - planned_minutes = 0 e is_available = False representan un día marcado
      como no disponible (el planificador nunca asigna horas ahí).
    - is_locked protege la jornada de la regeneración automática.
    - El plan se mantiene por completo separado del registro real
      (WorkSession); la comparación plan/real se hace en lectura.
    """

    work_date = models.DateField(unique=True)
    planned_start = models.TimeField(default=time(9, 0))
    planned_minutes = models.PositiveIntegerField(default=300)
    is_locked = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["work_date"]
        verbose_name = "Jornada planificada"
        verbose_name_plural = "Jornadas planificadas"
        constraints = [
            models.CheckConstraint(
                condition=Q(planned_minutes__lte=1440),
                name="planned_minutes_max_1440",
            ),
        ]

    def __str__(self):
        return f"{self.work_date} {self.planned_start:%H:%M} ({self.planned_minutes} min)"
