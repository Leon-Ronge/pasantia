"""Operaciones sobre jornadas reales (WorkSession).

Reglas clave:
- Solo puede existir una jornada abierta a la vez (constraint en la base
  y validación amable en la API).
- La duración siempre se deriva de start_at/end_at (ver WorkSession.save).
- Cerrar usa la hora del servidor salvo que se pida una manual, y esa
  hora manual debe ser válida: posterior a la entrada, no futura y del
  mismo día local de la jornada.
- Una jornada que olvidaron cerrar (ver ``engine.checkout_confirmation``)
  bloquea abrir otra hasta confirmar el cierre (409).
"""
from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.models import Settings
from work.exceptions import Conflict, NeedsConfirmation
from work.models import WorkSession
from work.services import engine, state
from work.services.time_utils import week_start_of

#: Tolerancia para relojes desfasados al validar "no futuros".
FUTURE_TOLERANCE_SECONDS = 300


def get_open_session() -> WorkSession | None:
    """Devuelve la jornada abierta actual (o None)."""
    return WorkSession.objects.filter(status=WorkSession.Status.IN_PROGRESS).first()


def open_session_exists(exclude_id: int | None = None) -> bool:
    qs = WorkSession.objects.filter(status=WorkSession.Status.IN_PROGRESS)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def elapsed_minutes(session: WorkSession) -> int:
    """Minutos transcurridos de una jornada en curso."""
    if not session.is_open:
        return session.worked_minutes
    delta = timezone.now() - session.start_at
    return max(0, int(delta.total_seconds() // 60))


def session_to_dict(session: WorkSession | None) -> dict | None:
    from work.serializers import WorkSessionSerializer

    if session is None:
        return None
    return WorkSessionSerializer(session).data


def pending_confirmation(session: WorkSession | None) -> dict | None:
    """Confirmación de cierre olvidado de una jornada (o None).

    Usa el motor puro: los mismos criterios que /api/today/ y /api/week/.
    """
    if session is None:
        return None
    data = state.build_week_input(week_start_of(session.work_date))
    return engine.checkout_confirmation(
        data,
        engine.SessionInput(
            id=session.id,
            work_date=session.work_date,
            start_at=session.start_at,
            end_at=session.end_at,
            snoozed_until=session.snoozed_until,
        ),
    )


def check_in(start_at: datetime | None = None, notes: str = "") -> WorkSession:
    """Abre la jornada de hoy (hora del servidor por defecto).

    - 409 si ya hay una jornada abierta (mensaje distinto si necesita
      confirmación de cierre).
    - 400 si hoy ya tiene jornada registrada.
    """
    now = timezone.now()
    open_session = get_open_session()
    if open_session is not None:
        pending = pending_confirmation(open_session)
        if pending is not None:
            if pending["scope"] == engine.SCOPE_PREVIOUS_DAY:
                message = (
                    "Hay una jornada sin cerrar del "
                    f"{pending['work_date']}. Cerrala (o confirmala) antes "
                    "de registrar una nueva."
                )
            else:
                message = (
                    "La jornada de hoy sigue abierta y ya pasó su salida "
                    f"prevista ({pending['planned_end'][:16].replace('T', ' ')}). "
                    "Cerrala o usá «Sigo trabajando» antes de abrir otra."
                )
            raise Conflict({"detail": message, "code": "PENDING_CONFIRMATION"})
        raise Conflict(
            {
                "detail": "Ya hay una jornada en curso. Cerrala antes de abrir otra.",
                "code": "OPEN_SESSION_EXISTS",
            }
        )

    start = start_at or now
    if start > now + timedelta(seconds=FUTURE_TOLERANCE_SECONDS):
        raise ValidationError({"start_at": "La hora de entrada no puede ser futura."})
    work_date = timezone.localtime(start).date()
    if work_date != timezone.localdate():
        raise ValidationError(
            {"start_at": "La entrada manual debe ser del día de hoy."}
        )
    if WorkSession.objects.filter(work_date=work_date).exists():
        raise ValidationError(
            {"start_at": "Ya hay una jornada registrada para hoy. Corregila desde Horas."}
        )
    return WorkSession.objects.create(start_at=start, notes=notes or "")


def check_out(
    end_at=None,
    session: WorkSession | None = None,
    confirm: bool = False,
) -> WorkSession:
    """Cierra la jornada abierta (o la indicada).

    - 409 si no hay jornada abierta.
    - 400 si la salida es anterior o igual a la entrada, es futura o es
      de otro día local.
    - 422 NEEDS_CONFIRMATION si la duración supera el máximo diario
      (acepta reintento con confirm=True).
    """
    session = session or get_open_session()
    if session is None or not session.is_open:
        raise Conflict(
            {
                "detail": "No hay ninguna jornada en curso para cerrar.",
                "code": "NO_OPEN_SESSION",
            }
        )

    now = timezone.now()
    end = end_at or now
    if end <= session.start_at:
        raise ValidationError({"end_at": "La salida no puede ser anterior o igual a la entrada."})
    if end > now + timedelta(seconds=FUTURE_TOLERANCE_SECONDS):
        raise ValidationError({"end_at": "La hora de salida no puede ser futura."})
    if timezone.localtime(end).date() != session.work_date:
        raise ValidationError(
            {"end_at": "La salida debe ser del mismo día que la entrada."}
        )

    duration = int((end - session.start_at).total_seconds() // 60)
    max_daily = Settings.load().max_daily_minutes
    if duration > max_daily and not confirm:
        raise NeedsConfirmation(
            f"La jornada dura {duration} minutos y supera el máximo diario "
            f"de {max_daily}. Confirmá para guardarla igual.",
            code="DURATION_EXCEEDS_MAX",
        )

    session.end_at = end
    session.snoozed_until = None
    session.save()
    return session


def snooze(session: WorkSession | None = None) -> WorkSession:
    """«Sigo trabajando»: posterga la salida prevista 30 minutos.

    Solo aplica a jornadas de HOY; una del día anterior siempre requiere
    confirmación de cierre (409).
    """
    session = session or get_open_session()
    if session is None or not session.is_open:
        raise Conflict(
            {
                "detail": "No hay ninguna jornada en curso.",
                "code": "NO_OPEN_SESSION",
            }
        )
    if session.work_date < timezone.localdate():
        raise Conflict(
            {
                "detail": (
                    "Esta jornada es del día anterior: no se puede postergar. "
                    "Cerrala con la hora de salida real."
                ),
                "code": "SNOOZE_NOT_ALLOWED",
            }
        )
    session.snoozed_until = timezone.now() + timedelta(minutes=engine.SNOOZE_MINUTES)
    session.save(update_fields=["snoozed_until", "updated_at"])
    return session

