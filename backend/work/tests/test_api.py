"""Pruebas de la API de horas + planificador (endpoints nuevos).

Fija el reloj del servidor (mock de ``timezone.now``) para que "hoy"
sea determinista; todo lo demás sale de la base de datos real.
"""
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Holiday
from work.models import WorkPlan, WorkSession

TZ = ZoneInfo("America/Argentina/Cordoba")

#: "Hoy" de los tests: viernes 2026-11-06 10:00 (hora de Córdoba).
FRIDAY = date(2026, 11, 6)
NOW = datetime(2026, 11, 6, 10, 0, tzinfo=TZ)


def dt(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


class FrozenClock:
    """Congela timezone.now/localdate en la fecha indicada."""

    def __init__(self, moment: datetime):
        self.moment = moment

    def __enter__(self):
        self.patcher = patch(
            "work.services.state.timezone.now", return_value=self.moment
        )
        self.patcher.start()
        # timezone.localdate deriva de now() en los módulos que lo usan.
        self.date_patcher = patch(
            "django.utils.timezone.localdate",
            return_value=self.moment.date(),
        )
        self.date_patcher.start()
        return self

    def __exit__(self, *exc):
        self.patcher.stop()
        self.date_patcher.stop()


def closed(day: date, hour: int, minutes: int, minute: int = 0) -> WorkSession:
    start = dt(day, hour, minute)
    return WorkSession.objects.create(
        start_at=start, end_at=start + timedelta(minutes=minutes)
    )


class TodayEndpointTests(APITestCase):
    def setUp(self):
        self.url = reverse("work:today")

    def test_not_started(self):
        with FrozenClock(NOW):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["state"], "NOT_STARTED")
        self.assertIsNone(data["start_at"])
        # El viernes es el único día disponible: su plan se estira al máximo.
        self.assertEqual(data["planned_minutes"], 420)
        self.assertIsNone(data["needs_checkout_confirmation"])

    def test_in_progress_and_done(self):
        with FrozenClock(NOW):
            session = WorkSession.objects.create(start_at=dt(FRIDAY, 9))
            data = self.client.get(self.url).json()
            self.assertEqual(data["state"], "IN_PROGRESS")
            self.assertEqual(data["worked_minutes"], 60)
            self.assertEqual(data["remaining_minutes"], 240)

            resp = self.client.post(
                reverse("work:work-sessions-check-out"), format="json"
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["worked_minutes"], 60)
            data = self.client.get(self.url).json()
            self.assertEqual(data["state"], "DONE")
        session.refresh_from_db()
        self.assertIsNotNone(session.end_at)


class CheckInOutTests(APITestCase):
    def setUp(self):
        self.check_in = reverse("work:work-sessions-check-in")
        self.check_out = reverse("work:work-sessions-check-out")
        self.current = reverse("work:work-sessions-current")

    def test_full_flow_with_server_time(self):
        with FrozenClock(NOW):
            resp = self.client.post(
                self.check_in,
                {"start_at": dt(FRIDAY, 9).isoformat()},
                format="json",
            )
            self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
            self.assertEqual(resp.json()["status"], "IN_PROGRESS")

            # Doble tap: segunda entrada → 409.
            again = self.client.post(self.check_in, format="json")
            self.assertEqual(again.status_code, status.HTTP_409_CONFLICT)

            closed = self.client.post(self.check_out, format="json")
            self.assertEqual(closed.status_code, 200)
            self.assertEqual(closed.json()["worked_minutes"], 60)

    def test_double_check_out_is_409(self):
        with FrozenClock(NOW):
            self.client.post(
                self.check_in,
                {"start_at": dt(FRIDAY, 9).isoformat()},
                format="json",
            )
            self.client.post(self.check_out, format="json")
            resp = self.client.post(self.check_out, format="json")
            self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(resp.json()["code"], "NO_OPEN_SESSION")

    def test_manual_end_at_validations(self):
        with FrozenClock(NOW):
            self.client.post(
                self.check_in, {"start_at": dt(FRIDAY, 9).isoformat()}, format="json"
            )
            session = WorkSession.objects.get()
            url = reverse("work:work-sessions-check-out-by-id", args=[session.id])

            # Anterior a la entrada.
            resp = self.client.post(
                url, {"end_at": dt(FRIDAY, 8, 30).isoformat()}, format="json"
            )
            self.assertEqual(resp.status_code, 400)

            # Futura.
            resp = self.client.post(
                url, {"end_at": dt(FRIDAY, 23, 0).isoformat()}, format="json"
            )
            self.assertEqual(resp.status_code, 400)

    def test_end_at_from_another_day_is_rejected(self):
        # Jornada que empezó ayer a las 23:00 y "cierran" hoy a las 9:00:
        # es otra fecha local → 400 (la corrección rara va por PATCH).
        yesterday = FRIDAY - timedelta(days=1)
        session = WorkSession.objects.create(start_at=dt(yesterday, 23))
        with FrozenClock(NOW):
            resp = self.client.post(
                reverse("work:work-sessions-check-out-by-id", args=[session.id]),
                {"end_at": dt(FRIDAY, 9).isoformat()},
                format="json",
            )
        self.assertEqual(resp.status_code, 400)

    def test_over_max_duration_requires_confirmation(self):
        # Congelado a las 16:00 para que el cierre manual de 15:00 no sea
        # futuro; 7:00 → 15:00 = 480 min > 420 (máximo por defecto).
        with FrozenClock(dt(FRIDAY, 16)):
            self.client.post(
                self.check_in, {"start_at": dt(FRIDAY, 7).isoformat()}, format="json"
            )
            session = WorkSession.objects.get()
            url = reverse("work:work-sessions-check-out-by-id", args=[session.id])
            resp = self.client.post(
                url, {"end_at": dt(FRIDAY, 15).isoformat()}, format="json"
            )
            self.assertEqual(resp.status_code, 422)
            body = resp.json()
            self.assertEqual(body["code"], "DURATION_EXCEEDS_MAX")

            # Reintento con confirm=true.
            resp = self.client.post(
                url,
                {"end_at": dt(FRIDAY, 15).isoformat(), "confirm": True},
                format="json",
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["worked_minutes"], 480)


class ForgottenCheckoutApiTests(APITestCase):
    def setUp(self):
        self.today_url = reverse("work:today")
        self.check_in = reverse("work:work-sessions-check-in")

    def test_yesterday_session_asks_and_blocks_new_check_in(self):
        yesterday = FRIDAY - timedelta(days=1)
        session = WorkSession.objects.create(start_at=dt(yesterday, 9))
        with FrozenClock(NOW):
            data = self.client.get(self.today_url).json()
            confirmation = data["needs_checkout_confirmation"]
            self.assertIsNotNone(confirmation)
            self.assertEqual(confirmation["scope"], "PREVIOUS_DAY")
            self.assertEqual(confirmation["session_id"], session.id)

            resp = self.client.post(self.check_in, format="json")
            self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(resp.json()["code"], "PENDING_CONFIRMATION")

    def test_fifty_nine_minutes_late_does_not_ask(self):
        # Jornada de hoy abierta 59 min después de su salida prevista.
        WorkSession.objects.create(start_at=dt(FRIDAY, 9))
        with FrozenClock(dt(FRIDAY, 14, 59)):
            data = self.client.get(self.today_url).json()
        self.assertIsNone(data["needs_checkout_confirmation"])

    def test_sixty_one_minutes_late_asks(self):
        WorkSession.objects.create(start_at=dt(FRIDAY, 9))
        with FrozenClock(dt(FRIDAY, 15, 1)):
            data = self.client.get(self.today_url).json()
            confirmation = data["needs_checkout_confirmation"]
            self.assertIsNotNone(confirmation)
            self.assertEqual(confirmation["scope"], "TODAY")
            self.assertEqual(confirmation["suggested_end"], dt(FRIDAY, 14, 0).isoformat())

    def test_pending_counts_only_until_planned_end(self):
        WorkSession.objects.create(start_at=dt(FRIDAY, 9))
        with FrozenClock(dt(FRIDAY, 15, 1)):
            data = self.client.get(self.today_url).json()
            self.assertEqual(data["worked_minutes"], 300)

    def test_snooze_defers_today_but_not_previous_day(self):
        session = WorkSession.objects.create(start_at=dt(FRIDAY, 9))
        snooze_url = reverse("work:work-sessions-snooze", args=[session.id])
        with FrozenClock(dt(FRIDAY, 15, 1)):
            resp = self.client.post(snooze_url, format="json")
            self.assertEqual(resp.status_code, 200)
            self.assertIsNotNone(resp.json()["snoozed_until"])
            # Ya no pide confirmación.
            data = self.client.get(self.today_url).json()
            self.assertIsNone(data["needs_checkout_confirmation"])

        WorkSession.objects.all().delete()
        yesterday = FRIDAY - timedelta(days=1)
        old = WorkSession.objects.create(start_at=dt(yesterday, 9))
        old_url = reverse("work:work-sessions-snooze", args=[old.id])
        with FrozenClock(NOW):
            resp = self.client.post(old_url, format="json")
            self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
            self.assertEqual(resp.json()["code"], "SNOOZE_NOT_ALLOWED")


class WeekEndpointTests(APITestCase):
    def setUp(self):
        self.url = reverse("work:week")

    def test_week_view_without_sessions(self):
        with FrozenClock(NOW):
            data = self.client.get(self.url, {"date": FRIDAY.isoformat()}).json()
        self.assertEqual(data["week_start"], "2026-11-02")  # lunes
        self.assertEqual(data["target_minutes"], 1200)
        self.assertEqual(data["worked_minutes"], 0)
        statuses = {d["date"]: d["status"] for d in data["days"]}
        self.assertEqual(statuses["2026-11-02"], "MISSED")   # lunes pasado
        self.assertEqual(statuses["2026-11-05"], "MISSED")   # jueves pasado
        self.assertEqual(statuses["2026-11-06"], "TODAY")
        self.assertEqual(statuses["2026-11-07"], "OFF")  # sábado OFF
        self.assertEqual(statuses["2026-11-08"], "OFF")
        # Hoy (viernes) es el único candidato: se estira hasta el máximo.
        by_date = {d["date"]: d for d in data["days"]}
        self.assertEqual(by_date["2026-11-06"]["planned_minutes"], 420)
        self.assertEqual(by_date["2026-11-07"]["planned_minutes"], None)
        self.assertEqual(data["unscheduled_minutes"], 780)

    def test_sessions_update_week_totals(self):
        closed(FRIDAY - timedelta(days=1), 9, 300)  # jueves 5 h
        with FrozenClock(NOW):
            data = self.client.get(self.url).json()
        self.assertEqual(data["worked_minutes"], 300)
        self.assertEqual(data["remaining_minutes"], 900)
        # Solo el viernes puede absorber: 300 + estirado a 420 → 480 sin programar.
        by_date = {d["date"]: d for d in data["days"]}
        self.assertEqual(by_date["2026-11-06"]["planned_minutes"], 420)
        self.assertEqual(data["unscheduled_minutes"], 480)

    def test_holiday_moves_hours(self):
        Holiday.objects.create(date=FRIDAY, name="Feriado")
        with FrozenClock(NOW):
            data = self.client.get(self.url).json()
        by_date = {d["date"]: d for d in data["days"]}
        self.assertEqual(by_date["2026-11-06"]["status"], "HOLIDAY")
        self.assertIsNone(by_date["2026-11-06"]["planned_minutes"])
        # Solo queda el sábado... OFF. Nada que planificar → 1200 sin programar.
        self.assertEqual(data["unscheduled_minutes"], 1200)

    def test_manual_day_reduces_remaining(self):
        friday = FRIDAY.isoformat()
        resp = self.client.patch(
            reverse("work:work-plans-detail", args=[friday]),
            {"planned_start": "13:00", "planned_minutes": 240},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        with FrozenClock(NOW):
            data = self.client.get(self.url).json()
        by_date = {d["date"]: d for d in data["days"]}
        self.assertEqual(by_date[friday]["planned_start"], "13:00")
        self.assertEqual(by_date[friday]["planned_minutes"], 240)
        self.assertTrue(by_date[friday]["is_manual"])
        self.assertEqual(data["blocked_minutes"], 240)


class MonthlySummaryEndpointTests(APITestCase):
    def setUp(self):
        self.url = reverse("work:hours-monthly-summary")

    def test_weeks_and_total(self):
        # Dos jornadas en la semana del 2 nov + una en octubre.
        closed(FRIDAY - timedelta(days=1), 9, 300)
        closed(FRIDAY, 9, 240)
        closed(date(2026, 10, 28), 9, 180)
        with FrozenClock(NOW):
            data = self.client.get(self.url, {"month": "2026-11"}).json()
            october = self.client.get(self.url, {"month": "2026-10"}).json()
        self.assertEqual(data["month"], "2026-11")
        self.assertEqual(data["total_worked_minutes"], 540)
        weeks = {w["week_start"]: w for w in data["weeks"]}
        self.assertEqual(weeks["2026-11-02"]["worked_minutes"], 540)
        self.assertEqual(weeks["2026-11-02"]["target_minutes"], 1200)
        # La jornada de octubre se reporta en su mes.
        self.assertEqual(october["total_worked_minutes"], 180)


class WorkPlanApiTests(APITestCase):
    def test_upsert_delete_and_reset_by_date(self):
        friday = FRIDAY.isoformat()
        url = reverse("work:work-plans-detail", args=[friday])

        # Upsert: crear.
        resp = self.client.patch(
            url, {"planned_minutes": 240, "is_locked": True}, format="json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(WorkPlan.objects.get(work_date=FRIDAY).planned_minutes, 240)

        # Upsert: modificar.
        resp = self.client.patch(
            url, {"planned_minutes": 180, "is_locked": False}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(WorkPlan.objects.get(work_date=FRIDAY).planned_minutes, 180)

        # Bloqueada no se puede eliminar.
        self.client.patch(url, {"is_locked": True}, format="json")
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 400)
        self.client.patch(url, {"is_locked": False}, format="json")

        # Delete elimina la excepción (vuelve a automático).
        resp = self.client.delete(url)
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(WorkPlan.objects.filter(work_date=FRIDAY).exists())

        # Reset de la semana (se pide explícita: la semana del viernes).
        saturday = (FRIDAY + timedelta(days=1)).isoformat()
        self.client.patch(
            reverse("work:work-plans-detail", args=[saturday]),
            {"is_available": False},
            format="json",
        )
        resp = self.client.post(
            reverse("work:work-plans-reset"), {"week": "2026-11-02"}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["deleted"], 1)
        self.assertEqual(WorkPlan.objects.count(), 0)

    def test_create_via_json_is_405(self):
        resp = self.client.post(
            reverse("work:work-plans-list"), {"work_date": FRIDAY.isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, 405)

    def test_post_session_list_is_405(self):
        resp = self.client.post(
            reverse("work:work-sessions-list"),
            {"start_at": dt(FRIDAY, 9).isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, 405)


class SessionPatchTests(APITestCase):
    def test_correction_via_patch(self):
        session = closed(FRIDAY - timedelta(days=1), 9, 300)
        url = reverse("work:work-sessions-detail", args=[session.id])
        resp = self.client.patch(
            url, {"end_at": dt(FRIDAY - timedelta(days=1), 13, 30).isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["worked_minutes"], 270)

    def test_patch_rejects_end_before_start(self):
        session = closed(FRIDAY - timedelta(days=1), 9, 300)
        url = reverse("work:work-sessions-detail", args=[session.id])
        resp = self.client.patch(
            url, {"end_at": dt(FRIDAY - timedelta(days=1), 8).isoformat()},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
