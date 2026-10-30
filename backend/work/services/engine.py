"""Motor puro de cálculo de horas + planificador semanal.

Función pura: no toca la base de datos ni el reloj. Todo lo que necesita
entra por ``WeekInput`` (incluido ``now``, aware y en hora local), y el
resultado se devuelve como dict JSON-izable. Esto lo hace trivial de
testear (sin mocks de ORM) y elimina la duplicación entre el resumen de
horas y el planificador: UN solo servicio calcula ambas cosas.

Algoritmo (especificación §4):
    1. worked = minutos efectivos de las jornadas de la semana. Una
       jornada abierta cuenta los minutos transcurridos; si necesita
       confirmación (olvidaron cerrarla) cuenta solo hasta su salida
       prevista.
    2. remaining = max(0, objetivo vigente − worked − minutos de días
       manuales futuros). Los feriados NO reducen el objetivo.
    3. Candidatos: desde hoy (inclusive si hoy no tiene jornada) hasta el
       domingo, excluyendo feriados, días OFF y días no disponibles.
       Días pasados sin jornada quedan MISSED (no se replanifican).
    4. Asignación:
       a) días PREFERRED en orden cronológico con su duración estándar;
       b) si falta, días RESERVE con su duración estándar;
       c) ampliar días ya planificados hasta ``max_daily_minutes``
          (PREFERRED primero, luego RESERVE);
       d) un resto menor que ``min_block_minutes`` se absorbe ampliando
          un día ya planificado;
       e) lo que no entra se informa en ``unscheduled_minutes``.
    5. La salida prevista de una jornada en curso es su entrada real más
       los ``planned_minutes`` del día.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

#: Minutos que suma "Sigo trabajando" (snooze).
SNOOZE_MINUTES = 30

#: Ámbitos de la confirmación de cierre olvidado.
SCOPE_PREVIOUS_DAY = "PREVIOUS_DAY"
SCOPE_TODAY = "TODAY"

#: Estados posibles de un día en la vista semanal.
DAY_DONE = "DONE"
DAY_TODAY = "TODAY"
DAY_PLANNED = "PLANNED"
DAY_HOLIDAY = "HOLIDAY"
DAY_OFF = "OFF"
DAY_MISSED = "MISSED"
DAY_PENDING = "PENDING_CONFIRMATION"

#: Estados posibles de "hoy" en /api/today/.
TODAY_NOT_STARTED = "NOT_STARTED"
TODAY_IN_PROGRESS = "IN_PROGRESS"
TODAY_DONE = "DONE"

#: Tipos de plantilla de día.
KIND_PREFERRED = "PREFERRED"
KIND_RESERVE = "RESERVE"
KIND_OFF = "OFF"


@dataclass
class SessionInput:
    """Jornada real (cerrada o en curso) vista por el motor."""

    id: int
    work_date: date
    start_at: datetime
    end_at: datetime | None = None
    snoozed_until: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.end_at is None


@dataclass
class ExceptionInput:
    """Excepción manual de un día (WorkPlan): horario o disponibilidad."""

    work_date: date
    planned_start: time
    planned_minutes: int
    is_locked: bool = False
    is_available: bool = True


@dataclass
class TemplateInput:
    """Plantilla de un día de la semana (WeekdayTemplate)."""

    weekday: int  # lunes=0 ... domingo=6
    kind: str  # PREFERRED | RESERVE | OFF
    start_time: time
    default_minutes: int | None = None


@dataclass
class WeekInput:
    """Todo lo que el motor necesita para calcular una semana."""

    week_start: date  # lunes de la semana (inclusive)
    today: date
    now: datetime  # aware, hora local
    target_minutes: int
    sessions: list[SessionInput] = field(default_factory=list)
    exceptions: dict[date, ExceptionInput] = field(default_factory=dict)
    templates: dict[int, TemplateInput] = field(default_factory=dict)
    holidays: dict[date, str] = field(default_factory=dict)
    max_daily_minutes: int = 420
    min_block_minutes: int = 60
    carry_over_deficit: bool = False
    opening_deficit_minutes: int = 0
    forgotten_threshold_minutes: int = 60


def derived_standard_minutes(data: WeekInput) -> int:
    """Duración estándar de un día sin ``default_minutes``.

    Objetivo semanal dividido la cantidad de días PREFERRED (entero).
    """
    preferred = sum(
        1 for t in data.templates.values() if t.kind == KIND_PREFERRED
    )
    if preferred == 0:
        return data.target_minutes
    return data.target_minutes // preferred


def standard_slot(data: WeekInput, day: date) -> tuple[time, int]:
    """(hora de inicio, duración estándar) de un día, sin excepciones manuales."""
    template = data.templates.get(day.weekday())
    minutes = None
    if template is not None:
        minutes = template.default_minutes
    if not minutes:
        minutes = derived_standard_minutes(data)
    start_time = template.start_time if template else time(9, 0)
    return start_time, minutes


def day_slot(data: WeekInput, day: date) -> tuple[time, int]:
    """(hora de inicio, minutos) efectivos de un día: excepción > estándar."""
    exc = data.exceptions.get(day)
    if exc is not None and exc.is_available and exc.planned_minutes > 0:
        return exc.planned_start, exc.planned_minutes
    return standard_slot(data, day)


def planned_end_of(data: WeekInput, session: SessionInput) -> datetime:
    """Salida prevista: entrada real + minutos planificados del día."""
    _, minutes = day_slot(data, session.work_date)
    end = session.start_at + timedelta(minutes=minutes)
    if session.snoozed_until and session.snoozed_until > end:
        end = session.snoozed_until
    return end


def checkout_confirmation(data: WeekInput, session: SessionInput) -> dict | None:
    """Detecta una jornada abierta que olvidaron cerrar.

    - Jornada de un día anterior a hoy: siempre necesita confirmación.
    - Jornada de hoy: si ``now`` supera la salida prevista + el umbral
      configurado (o el postergado con "Sigo trabajando").
    """
    if not session.is_open:
        return None
    base_end = session.start_at + timedelta(
        minutes=day_slot(data, session.work_date)[1]
    )
    trigger_at = base_end + timedelta(minutes=data.forgotten_threshold_minutes)
    if session.snoozed_until and session.snoozed_until > trigger_at:
        trigger_at = session.snoozed_until
    if session.work_date < data.today:
        scope = SCOPE_PREVIOUS_DAY
    elif session.work_date == data.today and data.now > trigger_at:
        scope = SCOPE_TODAY
    else:
        return None
    planned_end = planned_end_of(data, session)
    tz = data.now.tzinfo
    return {
        "scope": scope,
        "session_id": session.id,
        "work_date": session.work_date.isoformat(),
        "started_at": _iso(session.start_at, tz),
        "planned_end": _iso(planned_end, tz),
        "suggested_end": _iso(planned_end, tz),
    }


def effective_minutes(data: WeekInput, session: SessionInput) -> int:
    """Minutos que cuentan de una jornada.

    Cerradas: su duración real. Abiertas: lo transcurrido; y si necesita
    confirmación, solo hasta la salida prevista (aún no es definitiva).
    """
    if not session.is_open:
        delta = session.end_at - session.start_at
        return max(0, int(delta.total_seconds() // 60))
    elapsed = max(0, int((data.now - session.start_at).total_seconds() // 60))
    if checkout_confirmation(data, session) is not None:
        cap = max(0, int((planned_end_of(data, session) - session.start_at).total_seconds() // 60))
        return min(elapsed, cap)
    return elapsed


def build_week(data: WeekInput) -> dict:
    """Calcula la vista completa de la semana (días + resumen + hoy)."""
    week_days = [data.week_start + timedelta(days=i) for i in range(7)]
    week_end = week_days[-1]
    session_by_day = {s.work_date: s for s in data.sessions}
    #: Salida en la zona horaria de `now` (local, p. ej. Córdoba).
    tzinfo = data.now.tzinfo

    # --- Días de la semana: estado + datos --------------------------------
    days: list[dict] = []
    worked_minutes = 0
    for day in week_days:
        session = session_by_day.get(day)
        exc = data.exceptions.get(day)
        is_holiday = day in data.holidays
        template = data.templates.get(day.weekday())
        slot_start, slot_minutes = day_slot(data, day)

        item = {
            "date": day.isoformat(),
            "weekday": day.weekday(),
            "status": None,
            "is_holiday": is_holiday,
            "holiday_name": data.holidays.get(day),
            "start_at": None,
            "end_at": None,
            "worked_minutes": 0,
            "planned_start": None,
            "planned_minutes": None,
            "diff_minutes": 0,
            "needs_checkout_confirmation": None,
            "is_manual": exc is not None,
            "is_locked": bool(exc.is_locked) if exc is not None else False,
        }

        if session is not None:
            worked = effective_minutes(data, session)
            day_confirmation = checkout_confirmation(data, session)
            if day_confirmation is not None:
                day_status = DAY_PENDING
            elif session.is_open:
                day_status = DAY_TODAY  # jornada en curso, sin confirmación
            else:
                day_status = DAY_DONE
            item.update(
                {
                    "status": day_status,
                    "start_at": _iso(session.start_at, tzinfo),
                    "end_at": _iso(
                        session.end_at or planned_end_of(data, session), tzinfo
                    ),
                    "worked_minutes": worked,
                    "planned_start": slot_start.strftime("%H:%M"),
                    "planned_minutes": slot_minutes,
                    "diff_minutes": worked - slot_minutes,
                    "needs_checkout_confirmation": day_confirmation,
                }
            )
            worked_minutes += worked
        elif is_holiday:
            item["status"] = DAY_HOLIDAY
        elif template is not None and template.kind == KIND_OFF:
            item["status"] = DAY_OFF
        elif exc is not None and not exc.is_available:
            item["status"] = DAY_OFF
        elif exc is not None and exc.planned_minutes > 0 and day >= data.today:
            # Día manual futuro: se respeta tal cual.
            item.update(
                {
                    "status": DAY_PLANNED,
                    "planned_start": exc.planned_start.strftime("%H:%M"),
                    "planned_minutes": exc.planned_minutes,
                }
            )
        elif day < data.today:
            item["status"] = DAY_MISSED
        elif day == data.today:
            item["status"] = DAY_TODAY
        else:
            item["status"] = DAY_PLANNED
        days.append(item)

    day_by_date = {d["date"]: d for d in days}

    # Jornada olvidada más antigua pendiente de confirmar (puede ser del
    # día anterior e incluso de la semana previa).
    confirmation = None
    for session in sorted(data.sessions, key=lambda s: s.work_date):
        found = checkout_confirmation(data, session)
        if found is not None:
            confirmation = found
            break

    # --- Objetivo y saldo --------------------------------------------------
    target = data.target_minutes
    carry = data.opening_deficit_minutes if data.carry_over_deficit else 0
    goal = target + carry

    # Días manuales sin jornada (desde hoy): sus minutos ya están
    # "reservados" y no deben volver a planificarse.
    blocked_minutes = 0
    for day in week_days:
        if day < data.today or day in session_by_day:
            continue
        exc = data.exceptions.get(day)
        if (
            exc is not None
            and exc.is_available
            and exc.planned_minutes > 0
            and day not in data.holidays
        ):
            blocked_minutes += exc.planned_minutes

    remaining = max(0, goal - worked_minutes - blocked_minutes)

    # --- Candidatos ---------------------------------------------------------
    # Semana futura: todos sus días son candidatos; pasada: ninguno.
    first_candidate = max(data.today, data.week_start)
    if data.today in session_by_day and data.week_start <= data.today <= week_end:
        first_candidate = data.today + timedelta(days=1)

    def is_candidate(day: date) -> bool:
        if not (first_candidate <= day <= week_end):
            return False
        if day in data.holidays or day in session_by_day:
            return False
        template = data.templates.get(day.weekday())
        if template is None or template.kind == KIND_OFF:
            return False
        exc = data.exceptions.get(day)
        if exc is not None and (not exc.is_available or exc.planned_minutes > 0):
            return False
        return True

    candidates = [d for d in week_days if is_candidate(d)]

    # --- Asignación ---------------------------------------------------------
    plan: dict[date, dict] = {}  # día → {"start": time, "minutes": int, "kind": str}
    needed = remaining

    def try_assign(day: date, kind: str):
        nonlocal needed
        if needed <= 0:
            return
        if needed < data.min_block_minutes:
            return
        _, standard = day_slot(data, day)
        chunk = min(standard, needed)
        start_time, _ = standard_slot(data, day)
        plan[day] = {"start": start_time, "minutes": chunk, "kind": kind}
        needed -= chunk

    # a) PREFERRED, b) RESERVE, en orden cronológico.
    for kind in (KIND_PREFERRED, KIND_RESERVE):
        for day in candidates:
            template = data.templates.get(day.weekday())
            if template is None or template.kind != kind:
                continue
            try_assign(day, kind)

    # c) Ampliar días ya planificados hasta el máximo diario.
    def extend(cap: int):
        nonlocal needed
        for kind in (KIND_PREFERRED, KIND_RESERVE):
            for day, entry in list(plan.items()):
                if entry["kind"] != kind or needed <= 0:
                    continue
                extra = min(cap - entry["minutes"], needed)
                if extra > 0:
                    entry["minutes"] += extra
                    needed -= extra

    extend(data.max_daily_minutes)

    # d) Absorber un resto menor que el bloque mínimo en un día ya planificado.
    if 0 < needed < data.min_block_minutes and plan:
        last_day = max(plan)
        plan[last_day]["minutes"] += needed
        needed = 0

    # Aplicar el plan a los días (fechas aware en la zona de `now`).
    for day, entry in plan.items():
        item = day_by_date[day.isoformat()]
        start_dt = datetime.combine(day, entry["start"], tzinfo=tzinfo)
        end = start_dt + timedelta(minutes=entry["minutes"])
        item.update(
            {
                "status": DAY_TODAY if item["status"] == DAY_TODAY else DAY_PLANNED,
                "planned_start": entry["start"].strftime("%H:%M"),
                "planned_minutes": entry["minutes"],
                "start_at": _iso(start_dt),
                "end_at": _iso(end),
            }
        )

    unscheduled_minutes = needed

    # --- Proyección: último momento en que se termina el trabajo ----------
    projected: datetime | None = None
    for day in week_days:
        item = day_by_date[day.isoformat()]
        if item["end_at"] and item["status"] in (
            DAY_DONE, DAY_PENDING, DAY_TODAY, DAY_PLANNED
        ):
            end = _parse(item["end_at"])
            if projected is None or end > projected:
                projected = end

    # --- Bloque "hoy" --------------------------------------------------------
    today_item = day_by_date.get(data.today.isoformat())
    today_block = _today_block(data, today_item, session_by_day.get(data.today))
    if confirmation is not None:
        today_block["needs_checkout_confirmation"] = confirmation

    return {
        "week_start": data.week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "target_minutes": target,
        "carry_over_minutes": carry,
        "worked_minutes": worked_minutes,
        "remaining_minutes": remaining,
        "blocked_minutes": blocked_minutes,
        "unscheduled_minutes": unscheduled_minutes,
        "needs_checkout_confirmation": confirmation,
        "projected_end": (
            {"date": projected.date().isoformat(), "time": projected.strftime("%H:%M")}
            if projected
            else None
        ),
        "days": days,
        "today": today_block,
    }


def _today_block(
    data: WeekInput, item: dict | None, session: SessionInput | None
) -> dict:
    """Estado de hoy para /api/today/ y /api/week/."""
    if item is None:
        return {
            "date": data.today.isoformat(),
            "state": TODAY_NOT_STARTED,
            "start_at": None,
            "end_at": None,
            "worked_minutes": 0,
            "planned_minutes": None,
            "remaining_minutes": 0,
            "needs_checkout_confirmation": None,
        }
    if session is None:
        state = TODAY_NOT_STARTED
    elif item["status"] == DAY_PENDING:
        state = TODAY_IN_PROGRESS
    elif session.is_open:
        state = TODAY_IN_PROGRESS
    else:
        state = TODAY_DONE
    planned = item["planned_minutes"] or 0
    return {
        "date": data.today.isoformat(),
        "state": state,
        # Entrada REAL (null si todavía no empezó); la salida prevista ya
        # está en end_at.
        "start_at": item["start_at"] if session is not None else None,
        "end_at": item["end_at"],
        "worked_minutes": item["worked_minutes"],
        "planned_minutes": item["planned_minutes"],
        "remaining_minutes": max(0, planned - item["worked_minutes"]),
        "needs_checkout_confirmation": item["needs_checkout_confirmation"],
    }


def _iso(dt: datetime | None, tz=None) -> str | None:
    """ISO 8601; con `tz` convierte a esa zona antes de serializar."""
    if dt is None:
        return None
    if tz is not None:
        dt = dt.astimezone(tz)
    return dt.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)
