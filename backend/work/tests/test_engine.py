"""Pruebas del motor puro (sin BD, sin reloj): horas + planificador.

Cubren los escenarios obligatorios de la especificación:
- 4×5h sin restricciones; ajuste de días cortos; feriados lun+mar;
  40h con 5 preferidos; día no disponible; día bloqueado manual;
  sin duplicar; minutos sin programar; carry-over;
- cierre olvidado (59/61 min, ayer siempre, pendiente acotada).
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from work.services import engine
from work.services.engine import (
    KIND_OFF,
    KIND_PREFERRED,
    KIND_RESERVE,
    SCOPE_PREVIOUS_DAY,
    SCOPE_TODAY,
    DAY_DONE,
    DAY_HOLIDAY,
    DAY_MISSED,
    DAY_OFF,
    DAY_PENDING,
    DAY_PLANNED,
    DAY_TODAY,
    ExceptionInput,
    SessionInput,
    TemplateInput,
    WeekInput,
    build_week,
)

TZ = ZoneInfo("America/Argentina/Cordoba")

#: Lunes de una semana futura fija para todos los tests (2026-11-02).
MONDAY = date(2026, 11, 2)


def dt(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def standard_templates(default_minutes=None, preferred=(0, 1, 2, 3)):
    """Plantillas: lun-jue PREFERRED, vie RESERVE, sáb-dom OFF (semilla)."""
    templates = {}
    for weekday in range(7):
        if weekday in preferred:
            kind = KIND_PREFERRED
        elif weekday == 4:
            kind = KIND_RESERVE
        else:
            kind = KIND_OFF
        templates[weekday] = TemplateInput(
            weekday=weekday, kind=kind, start_time=time(9, 0),
            default_minutes=default_minutes,
        )
    return templates


def make_input(**overrides) -> WeekInput:
    """WeekInput de la semana de MONDAY con hoy = lunes a las 08:00."""
    defaults = dict(
        week_start=MONDAY,
        today=MONDAY,
        now=dt(MONDAY, 8, 0),
        target_minutes=1200,
        templates=standard_templates(),
        max_daily_minutes=420,
        min_block_minutes=60,
    )
    defaults.update(overrides)
    return WeekInput(**defaults)


def closed_session(day: date, hour: int, minutes: int, sid: int = 1, minute: int = 0):
    start = dt(day, hour, minute)
    return SessionInput(
        id=sid, work_date=day, start_at=start, end_at=start + timedelta(minutes=minutes)
    )


def day_by_date(state: dict, day: date) -> dict:
    return next(d for d in state["days"] if d["date"] == day.isoformat())


class PlannerEngineTests(SimpleTestCase):
    """Escenarios de planificación del algoritmo §4."""

    def test_four_five_hour_days_without_restrictions(self):
        state = build_week(make_input())
        expectations = [300, 300, 300, 300]
        for offset, minutes in enumerate(expectations):
            day = day_by_date(state, MONDAY + timedelta(days=offset))
            expected_status = DAY_TODAY if offset == 0 else DAY_PLANNED
            self.assertEqual(day["status"], expected_status)
            self.assertEqual(day["planned_start"], "09:00")
            self.assertEqual(day["planned_minutes"], minutes)
        # El viernes (RESERVE) no hace falta.
        friday = day_by_date(state, MONDAY + timedelta(days=4))
        self.assertIsNone(friday["planned_minutes"])
        self.assertEqual(state["unscheduled_minutes"], 0)
        self.assertEqual(state["remaining_minutes"], 1200)

    def test_short_weekdays_and_friday_extends(self):
        """lun 300, mar 305, mié 294, jue sin ir → vie 9:00-14:01 (301)."""
        state = build_week(
            make_input(
                today=MONDAY + timedelta(days=4),  # viernes
                now=dt(MONDAY + timedelta(days=4), 8, 0),
                sessions=[
                    closed_session(MONDAY, 8, 300, minute=55),        # lun 8:55-13:55
                    closed_session(MONDAY + timedelta(days=1), 9, 305),  # mar 9:00-14:05
                    closed_session(MONDAY + timedelta(days=2), 8, 294, minute=54),  # mié 8:54-13:48
                ],
            )
        )
        self.assertEqual(state["worked_minutes"], 899)
        self.assertEqual(state["remaining_minutes"], 301)
        friday = day_by_date(state, MONDAY + timedelta(days=4))
        self.assertEqual(friday["planned_start"], "09:00")
        self.assertEqual(friday["planned_minutes"], 301)  # 9:00 → 14:01
        self.assertEqual(state["unscheduled_minutes"], 0)
        # El jueves sin jornada queda MISSED, no se replanifica.
        thursday = day_by_date(state, MONDAY + timedelta(days=3))
        self.assertEqual(thursday["status"], DAY_MISSED)

    def test_holidays_push_hours_to_later_days(self):
        """lun y mar feriados → mié 420, jue 420, vie 360."""
        wed = MONDAY + timedelta(days=2)
        state = build_week(
            make_input(
                holidays={MONDAY: "Feriado", MONDAY + timedelta(days=1): "Feriado"},
                max_daily_minutes=420,
            )
        )
        self.assertEqual(day_by_date(state, MONDAY)["status"], DAY_HOLIDAY)
        self.assertEqual(day_by_date(state, wed)["planned_minutes"], 420)       # 9:00-16:00
        self.assertEqual(day_by_date(state, wed + timedelta(days=1))["planned_minutes"], 420)
        friday = day_by_date(state, wed + timedelta(days=2))
        self.assertEqual(friday["planned_minutes"], 360)  # RESERVE estirado: 9:00-15:00
        self.assertEqual(state["unscheduled_minutes"], 0)

    def test_forty_hours_five_preferred_days(self):
        templates = standard_templates(default_minutes=480, preferred=(0, 1, 2, 3, 4))
        templates[4] = TemplateInput(4, KIND_PREFERRED, time(9, 0), 480)
        state = build_week(make_input(target_minutes=2400, templates=templates,
                                      max_daily_minutes=480))
        for offset in range(5):
            day = day_by_date(state, MONDAY + timedelta(days=offset))
            self.assertEqual(day["planned_minutes"], 480)
        self.assertEqual(state["unscheduled_minutes"], 0)

    def test_unavailable_day_is_skipped(self):
        friday = MONDAY + timedelta(days=4)
        state = build_week(
            make_input(exceptions={friday: ExceptionInput(friday, time(9, 0), 0,
                                                          is_available=False)})
        )
        self.assertEqual(day_by_date(state, friday)["status"], DAY_OFF)
        # Los 1200 minutos entran exactos en lun-jue (300 c/u).
        planned = [day_by_date(state, MONDAY + timedelta(days=i))["planned_minutes"]
                   for i in range(4)]
        self.assertEqual(planned, [300, 300, 300, 300])
        self.assertEqual(state["unscheduled_minutes"], 0)

    def test_manual_day_is_respected_and_not_replanned(self):
        friday = MONDAY + timedelta(days=4)
        state = build_week(
            make_input(exceptions={friday: ExceptionInput(friday, time(13, 0), 240)})
        )
        self.assertEqual(state["blocked_minutes"], 240)
        friday_day = day_by_date(state, friday)
        self.assertEqual(friday_day["status"], DAY_PLANNED)
        self.assertEqual(friday_day["planned_start"], "13:00")
        self.assertEqual(friday_day["planned_minutes"], 240)
        # Solo quedan 960 minutos para lun-jue.
        planned = [day_by_date(state, MONDAY + timedelta(days=i))["planned_minutes"]
                   for i in range(4)]
        self.assertEqual(planned, [300, 300, 300, 60])

    def test_does_not_duplicate_days_with_sessions(self):
        state = build_week(
            make_input(sessions=[closed_session(MONDAY, 9, 300)])
        )
        monday = day_by_date(state, MONDAY)
        self.assertEqual(monday["status"], DAY_DONE)
        self.assertEqual(monday["worked_minutes"], 300)
        self.assertEqual(state["remaining_minutes"], 900)
        # Mar-jue cubren los 900 restantes; lunes no se duplica.
        self.assertEqual(day_by_date(state, MONDAY)["planned_minutes"], 300)  # su plan propio
        self.assertEqual(day_by_date(state, MONDAY + timedelta(days=1))["planned_minutes"], 300)
        self.assertEqual(state["unscheduled_minutes"], 0)

    def test_unscheduled_minutes_when_no_days_remain(self):
        """Sin días disponibles: se informa lo que no entró."""
        wed = MONDAY + timedelta(days=2)
        state = build_week(
            make_input(
                today=MONDAY + timedelta(days=2),
                now=dt(wed, 8, 0),
                templates={2: TemplateInput(2, KIND_PREFERRED, time(9, 0), 300)},
                sessions=[closed_session(MONDAY, 9, 300)],
            )
        )
        # Solo el miércoles (300 → estirado a 420) puede absorber.
        self.assertEqual(day_by_date(state, wed)["planned_minutes"], 420)
        self.assertEqual(state["unscheduled_minutes"], 480)

    def test_carry_over_deficit_toggle(self):
        base = dict(opening_deficit_minutes=300)
        with_carry = build_week(make_input(carry_over_deficit=True, **base))
        self.assertEqual(with_carry["carry_over_minutes"], 300)
        self.assertEqual(with_carry["remaining_minutes"], 1500)
        without = build_week(make_input(carry_over_deficit=False, **base))
        self.assertEqual(without["carry_over_minutes"], 0)
        self.assertEqual(without["remaining_minutes"], 1200)


class ForgottenCheckoutTests(SimpleTestCase):
    """Detección de jornadas que se olvidaron de cerrar."""

    def open_session(self, day: date, hour: int, minute: int = 0, sid: int = 7):
        return SessionInput(id=sid, work_date=day, start_at=dt(day, hour, minute))

    def test_fifty_nine_minutes_late_does_not_ask(self):
        session = self.open_session(MONDAY, 9)  # salida prevista 14:00
        state = build_week(make_input(now=dt(MONDAY, 14, 59), sessions=[session]))
        self.assertIsNone(state["needs_checkout_confirmation"])
        self.assertEqual(day_by_date(state, MONDAY)["status"], DAY_TODAY)

    def test_sixty_one_minutes_late_asks(self):
        session = self.open_session(MONDAY, 9)
        state = build_week(make_input(now=dt(MONDAY, 15, 1), sessions=[session]))
        confirmation = state["needs_checkout_confirmation"]
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation["scope"], SCOPE_TODAY)
        self.assertEqual(confirmation["session_id"], 7)
        self.assertEqual(confirmation["planned_end"], dt(MONDAY, 14, 0).isoformat())
        self.assertEqual(day_by_date(state, MONDAY)["status"], DAY_PENDING)
        # La jornada pendiente cuenta solo hasta la salida prevista (300).
        self.assertEqual(state["worked_minutes"], 300)
        self.assertEqual(day_by_date(state, MONDAY)["worked_minutes"], 300)

    def test_previous_day_session_always_asks(self):
        session = self.open_session(MONDAY, 9)
        state = build_week(
            make_input(today=MONDAY + timedelta(days=1),
                       now=dt(MONDAY + timedelta(days=1), 8, 0),
                       sessions=[session])
        )
        confirmation = state["needs_checkout_confirmation"]
        self.assertIsNotNone(confirmation)
        self.assertEqual(confirmation["scope"], SCOPE_PREVIOUS_DAY)
        self.assertEqual(day_by_date(state, MONDAY)["status"], DAY_PENDING)
        # Acotada a la salida prevista aunque hayan pasado muchas horas.
        self.assertEqual(state["worked_minutes"], 300)

    def test_pending_does_not_accumulate_beyond_planned_end(self):
        session = self.open_session(MONDAY, 9)
        state = build_week(
            make_input(today=MONDAY + timedelta(days=3),
                       now=dt(MONDAY + timedelta(days=3), 20, 0),
                       sessions=[session])
        )
        self.assertEqual(state["worked_minutes"], 300)

    def test_today_with_session_is_not_replanned(self):
        """Hoy con jornada en curso no se replanifica (ni pide confirmación)."""
        session = self.open_session(MONDAY, 9)
        state = build_week(make_input(now=dt(MONDAY, 10, 0), sessions=[session]))
        self.assertIsNone(state["needs_checkout_confirmation"])
        self.assertEqual(day_by_date(state, MONDAY)["status"], DAY_TODAY)
        self.assertEqual(day_by_date(state, MONDAY)["worked_minutes"], 60)
        # El resto de la semana sigue planificándose.
        self.assertEqual(state["remaining_minutes"], 1140)

    def test_snooze_defers_the_prompt(self):
        session = self.open_session(MONDAY, 9)
        session.snoozed_until = dt(MONDAY, 15, 30)
        state = build_week(make_input(now=dt(MONDAY, 15, 10), sessions=[session]))
        self.assertIsNone(state["needs_checkout_confirmation"])
        # Pasado el snooze vuelve a pedir confirmación.
        state_late = build_week(make_input(now=dt(MONDAY, 15, 31), sessions=[session]))
        self.assertIsNotNone(state_late["needs_checkout_confirmation"])

    def test_completed_session_never_asks(self):
        state = build_week(make_input(sessions=[closed_session(MONDAY, 9, 300)]))
        self.assertIsNone(state["needs_checkout_confirmation"])
        self.assertEqual(day_by_date(state, MONDAY)["status"], DAY_DONE)


class TodayBlockTests(SimpleTestCase):
    """Bloque «hoy» de /api/today/ y /api/week/."""

    def test_not_started(self):
        state = build_week(make_input())
        today = state["today"]
        self.assertEqual(today["state"], "NOT_STARTED")
        self.assertIsNone(today["start_at"])
        self.assertEqual(today["planned_minutes"], 300)

    def test_in_progress_and_done(self):
        session = SessionInput(id=1, work_date=MONDAY, start_at=dt(MONDAY, 9))
        running = build_week(make_input(now=dt(MONDAY, 10, 30), sessions=[session]))
        self.assertEqual(running["today"]["state"], "IN_PROGRESS")
        self.assertEqual(running["today"]["worked_minutes"], 90)
        self.assertEqual(running["today"]["remaining_minutes"], 210)

        done = build_week(
            make_input(sessions=[closed_session(MONDAY, 9, 300)])
        )
        self.assertEqual(done["today"]["state"], "DONE")
        self.assertEqual(done["today"]["worked_minutes"], 300)

    def test_projected_end_uses_last_planned_day(self):
        state = build_week(make_input())
        self.assertEqual(
            state["projected_end"],
            {"date": (MONDAY + timedelta(days=3)).isoformat(), "time": "14:00"},
        )
