"""Pruebas de configuración (singleton + vigencia), feriados y Dashboard."""
import json
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings as django_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.settings import api_settings
from rest_framework.test import APITestCase

from core.models import (
    INITIAL_EFFECTIVE_FROM,
    SETTING_MONTHLY_TRIP_LIMIT,
    SETTING_WEEKLY_TARGET_MINUTES,
    Holiday,
    SettingValue,
    Settings,
    WeekdayTemplate,
)
from core.services import get_setting
from transport.services import monthly_summary
from work.services.state import weekly_balance
from work.services.time_utils import current_week_start


def next_week_start() -> date:
    return current_week_start() + timedelta(days=7)


class SettingsTests(APITestCase):
    def setUp(self):
        self.url = reverse("core:settings")

    def test_defaults(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["max_daily_minutes"], 420)
        self.assertEqual(data["min_block_minutes"], 60)
        self.assertFalse(data["carry_over_deficit"])
        self.assertEqual(data["forgotten_checkout_threshold_minutes"], 60)
        self.assertEqual(data["current_fare"], "0.00")
        self.assertIsNone(data["monthly_salary"])
        self.assertFalse(data["hide_amounts"])
        self.assertEqual(data["timezone"], "America/Argentina/Cordoba")
        # Valores con vigencia: iniciales que cubren todo el historial.
        self.assertEqual(data["weekly_target_minutes"], 1200)
        self.assertEqual(data["weekly_target_effective_from"], "2000-01-01")
        self.assertEqual(data["monthly_trip_limit"], 20)
        self.assertEqual(data["monthly_trip_limit_effective_from"], "2000-01-01")

    def test_defaults_include_seven_weekday_templates(self):
        data = self.client.get(self.url).json()
        templates = data["weekday_templates"]
        self.assertEqual(len(templates), 7)
        kinds = {t["weekday"]: t["kind"] for t in templates}
        self.assertEqual(kinds, {0: "PREFERRED", 1: "PREFERRED", 2: "PREFERRED",
                                 3: "PREFERRED", 4: "RESERVE", 5: "OFF", 6: "OFF"})
        for template in templates:
            self.assertEqual(template["start_time"], "09:00:00")
            self.assertIsNone(template["default_minutes"])
        # Duración derivada: 1200 / 4 días PREFERRED = 300 min.
        resolved = {t["weekday"]: t["resolved_minutes"] for t in templates}
        self.assertEqual(resolved, {0: 300, 1: 300, 2: 300, 3: 300,
                                    4: 300, 5: None, 6: None})

    def test_initial_setting_values_cover_full_history(self):
        """Los valores iniciales tienen effective_from lo bastante viejo."""
        self.assertLessEqual(INITIAL_EFFECTIVE_FROM, date(2000, 1, 1))
        self.assertEqual(get_setting(SETTING_WEEKLY_TARGET_MINUTES, date(2000, 1, 1)), 1200)
        self.assertEqual(get_setting(SETTING_MONTHLY_TRIP_LIMIT, date(2000, 1, 1)), 20)
        self.assertEqual(get_setting(SETTING_WEEKLY_TARGET_MINUTES), 1200)
        self.assertEqual(get_setting(SETTING_MONTHLY_TRIP_LIMIT), 20)

    def test_patch_updates_singleton_fields(self):
        resp = self.client.patch(
            self.url,
            {
                "max_daily_minutes": 360,
                "min_block_minutes": 45,
                "current_fare": "820.50",
                "monthly_salary": "250000.00",
                "hide_amounts": True,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["max_daily_minutes"], 360)
        self.assertEqual(data["min_block_minutes"], 45)
        self.assertEqual(data["current_fare"], "820.50")
        self.assertEqual(data["monthly_salary"], "250000.00")
        self.assertTrue(data["hide_amounts"])
        cfg = Settings.load()
        self.assertEqual(cfg.max_daily_minutes, 360)
        self.assertEqual(cfg.current_fare, Decimal("820.50"))
        self.assertEqual(cfg.monthly_salary, Decimal("250000.00"))

    def test_patch_clears_monthly_salary(self):
        Settings.load()
        self.client.patch(
            self.url, {"monthly_salary": "100.00"}, format="json"
        )
        resp = self.client.patch(self.url, {"monthly_salary": None}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["monthly_salary"])

    def test_rejects_negative_fare_and_salary(self):
        resp = self.client.patch(self.url, {"current_fare": "-1"}, format="json")
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch(self.url, {"monthly_salary": "-1"}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_singleton_is_not_duplicated(self):
        self.client.get(self.url)
        self.client.patch(self.url, {"max_daily_minutes": 300}, format="json")
        self.assertEqual(Settings.objects.count(), 1)

    def test_weekday_template_updates_keep_history_rows(self):
        resp = self.client.patch(
            self.url,
            {"weekday_templates": [{"weekday": 0, "kind": "OFF"}]},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        monday = WeekdayTemplate.objects.get(weekday=0)
        self.assertEqual(monday.kind, WeekdayTemplate.Kind.OFF)
        self.assertIsNone(monday.resolved_minutes)
        # Los demás días no se tocaron.
        self.assertEqual(WeekdayTemplate.objects.count(), 7)


class SettingValueVigenceTests(APITestCase):
    """Vigencia: los cambios crean filas nuevas y no reescriben el pasado."""

    def setUp(self):
        self.url = reverse("core:settings")

    def test_weekly_target_from_next_week_does_not_touch_past_weeks(self):
        # 30 h entran en el máximo diario por defecto (420 × 5 días = 2100).
        resp = self.client.patch(
            self.url,
            {"weekly_target_minutes": 1800, "apply_from": "next_week"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        # Hoy sigue vigente el valor anterior.
        self.assertEqual(data["weekly_target_minutes"], 1200)
        self.assertEqual(data["weekly_target_effective_from"], "2000-01-01")
        # Se creó una fila nueva sin tocar la anterior.
        self.assertEqual(
            SettingValue.objects.filter(key=SETTING_WEEKLY_TARGET_MINUTES).count(), 2
        )
        self.assertEqual(
            weekly_balance(current_week_start())["weekly_target_minutes"], 1200
        )
        self.assertEqual(
            weekly_balance(current_week_start() - timedelta(weeks=3))[
                "weekly_target_minutes"
            ],
            1200,
        )
        self.assertEqual(
            weekly_balance(next_week_start())["weekly_target_minutes"], 1800
        )

    def test_weekly_target_defaults_to_this_week(self):
        resp = self.client.patch(
            self.url, {"weekly_target_minutes": 1260}, format="json"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["weekly_target_minutes"], 1260)
        self.assertEqual(
            data["weekly_target_effective_from"],
            current_week_start().isoformat(),
        )

    def test_same_value_does_not_create_a_new_row(self):
        self.client.patch(
            self.url, {"weekly_target_minutes": 1200}, format="json"
        )
        self.assertEqual(
            SettingValue.objects.filter(key=SETTING_WEEKLY_TARGET_MINUTES).count(), 1
        )

    def test_trip_limit_change_applies_to_current_month(self):
        first_of_month = timezone.localdate().replace(day=1)
        last_month = (first_of_month - timedelta(days=1)).replace(day=1)
        self.assertEqual(monthly_summary(first_of_month)["limit"], 20)
        resp = self.client.patch(
            self.url,
            {"monthly_trip_limit": 30, "apply_from": "this_month"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(monthly_summary(first_of_month)["limit"], 30)
        # El mes anterior conserva el cupo histórico.
        self.assertEqual(monthly_summary(last_month)["limit"], 20)

    def test_trip_limit_next_month_keeps_current_month(self):
        first_of_month = timezone.localdate().replace(day=1)
        resp = self.client.patch(
            self.url,
            {"monthly_trip_limit": 35, "apply_from": "next_month"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["monthly_trip_limit"], 20)
        self.assertEqual(monthly_summary(first_of_month)["limit"], 20)

    def test_rejects_unknown_apply_from(self):
        resp = self.client.patch(
            self.url, {"weekly_target_minutes": 1500, "apply_from": "someday"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


class SettingsFeasibilityTests(APITestCase):
    """Validación: max_daily_minutes × (PREFERRED + RESERVE) >= objetivo."""

    def setUp(self):
        self.url = reverse("core:settings")

    def test_40h_with_420_max_daily_is_rejected_with_422(self):
        resp = self.client.patch(
            self.url, {"weekly_target_minutes": 2400}, format="json"
        )
        self.assertEqual(resp.status_code, 422)
        detail = resp.json()["detail"]
        self.assertIn("40 h", detail)
        self.assertIn("máximo diario", detail)
        # No se persistió nada: ni el objetivo ni una fila con vigencia.
        self.assertEqual(get_setting(SETTING_WEEKLY_TARGET_MINUTES), 1200)
        self.assertEqual(
            SettingValue.objects.filter(key=SETTING_WEEKLY_TARGET_MINUTES).count(), 1
        )
        self.assertEqual(Settings.load().max_daily_minutes, 420)

    def test_40h_is_accepted_when_max_daily_allows_it(self):
        resp = self.client.patch(
            self.url,
            {"weekly_target_minutes": 2400, "max_daily_minutes": 600},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(get_setting(SETTING_WEEKLY_TARGET_MINUTES), 2400)

    def test_extra_preferred_day_makes_40h_feasible(self):
        # 480 × 5 días = 2400: alcanza justo para 40 h.
        resp = self.client.patch(
            self.url,
            {
                "weekly_target_minutes": 2400,
                "max_daily_minutes": 480,
                "weekday_templates": [{"weekday": 4, "kind": "PREFERRED"}],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            {t["weekday"]: t["kind"] for t in resp.json()["weekday_templates"]}[4],
            "PREFERRED",
        )

    def test_all_days_off_rejects_any_target(self):
        templates = [{"weekday": wd, "kind": "OFF"} for wd in range(7)]
        resp = self.client.patch(
            self.url, {"weekday_templates": templates}, format="json"
        )
        self.assertEqual(resp.status_code, 422)


class DerivedDailyDurationTests(APITestCase):
    """Duración diaria = objetivo semanal / días PREFERRED (enteros).

    El plan automático ya no se persiste: se calcula al vuelo en
    GET /api/week/.
    """

    def setUp(self):
        self.settings_url = reverse("core:settings")
        self.week_url = reverse("work:week")
        self.week = next_week_start()

    def _planned_days(self):
        resp = self.client.get(self.week_url, {"date": self.week.isoformat()})
        self.assertEqual(resp.status_code, 200)
        return [d for d in resp.json()["days"] if d["planned_minutes"]]

    def test_20h_over_4_days_is_300_minutes(self):
        days = self._planned_days()
        self.assertEqual(len(days), 4)
        for day in days:
            self.assertEqual(day["planned_minutes"], 300)

    def test_40h_over_5_days_is_480_minutes(self):
        # 40 h con viernes PREFERRED y máximo diario que lo admite.
        patch = self.client.patch(
            self.settings_url,
            {
                "weekly_target_minutes": 2400,
                "max_daily_minutes": 600,
                "weekday_templates": [{"weekday": 4, "kind": "PREFERRED"}],
            },
            format="json",
        )
        self.assertEqual(patch.status_code, 200)
        resolved = {
            t["weekday"]: t["resolved_minutes"]
            for t in patch.json()["weekday_templates"]
        }
        self.assertEqual(resolved[0], 480)
        self.assertEqual(resolved[4], 480)

        days = self._planned_days()
        self.assertEqual(len(days), 5)
        for day in days:
            self.assertEqual(day["planned_minutes"], 480)

    def test_explicit_default_minutes_beats_derivation(self):
        self.client.patch(
            self.settings_url,
            {"weekday_templates": [{"weekday": 0, "default_minutes": 120}]},
            format="json",
        )
        days = self._planned_days()
        monday = next(
            d for d in days if d["date"] == self.week.isoformat()
        )
        self.assertEqual(monday["planned_minutes"], 120)


class HolidayTests(APITestCase):
    def setUp(self):
        self.url = reverse("core:holidays-list")

    def test_full_crud(self):
        create = self.client.post(
            self.url,
            {
                "date": "2026-12-08",
                "name": "Inmaculada Concepción de María",
                "kind": "NATIONAL",
            },
            format="json",
        )
        self.assertEqual(create.status_code, 201)
        pk = create.json()["id"]

        listing = self.client.get(self.url).json()
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["results"][0]["kind"], "NATIONAL")

        patch = self.client.patch(
            f"{self.url}{pk}/", {"kind": "PERSONAL"}, format="json"
        )
        self.assertEqual(patch.status_code, 200)
        self.assertEqual(patch.json()["kind"], "PERSONAL")

        delete = self.client.delete(f"{self.url}{pk}/")
        self.assertEqual(delete.status_code, 204)
        self.assertEqual(Holiday.objects.count(), 0)

    def test_list_filters_by_year(self):
        Holiday.objects.create(date=date(2026, 1, 1), name="Año nuevo")
        Holiday.objects.create(date=date(2027, 1, 1), name="Año nuevo 2027")
        data = self.client.get(f"{self.url}?year=2026").json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["date"], "2026-01-01")

    def test_rejects_empty_name(self):
        resp = self.client.post(
            self.url, {"date": "2026-06-01", "name": "   "}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_accepts_year_month_day_instead_of_date(self):
        resp = self.client.post(
            self.url,
            {"year": 2026, "month": 5, "day": 25, "name": "Revolución de Mayo"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["date"], "2026-05-25")


class ImportHolidaysCommandTests(APITestCase):
    """manage.py import_holidays <año> desde la API pública (fuente mockeada)."""

    def _run(self, payload: bytes):
        from io import BytesIO
        from unittest.mock import patch

        from django.core.management import call_command

        with patch("urllib.request.urlopen", return_value=BytesIO(payload)):
            call_command("import_holidays", "2026")

    def test_imports_and_maps_kinds(self):
        payload = json.dumps(
            [
                {"fecha": "2026-01-01", "tipo": "inamovible", "nombre": "Año nuevo"},
                {"fecha": "2026-03-23", "tipo": "puente", "nombre": "Puente turístico"},
                {"fecha": "2026-06-15", "tipo": "trasladable", "nombre": "Martín Güemes"},
            ]
        ).encode()
        self._run(payload)
        self.assertEqual(Holiday.objects.count(), 3)
        self.assertEqual(
            Holiday.objects.get(date=date(2026, 1, 1)).kind, Holiday.Kind.NATIONAL
        )
        self.assertEqual(
            Holiday.objects.get(date=date(2026, 3, 23)).kind, Holiday.Kind.BRIDGE
        )
        # Reimportar es idempotente (actualiza, no duplica).
        self._run(payload)
        self.assertEqual(Holiday.objects.count(), 3)

    def test_respects_personal_holidays(self):
        Holiday.objects.create(
            date=date(2026, 1, 1), name="Año nuevo", kind=Holiday.Kind.PERSONAL
        )
        payload = json.dumps(
            [{"fecha": "2026-01-01", "tipo": "inamovible", "nombre": "Año nuevo"}]
        ).encode()
        self._run(payload)
        self.assertEqual(
            Holiday.objects.get(date=date(2026, 1, 1)).kind, Holiday.Kind.PERSONAL
        )


class ImportHolidaysEndpointTests(APITestCase):
    """POST /api/holidays/import/: el botón «Importar feriados» de Ajustes."""

    def test_imports_year_and_returns_count(self):
        from io import BytesIO
        from unittest.mock import patch

        payload = json.dumps(
            [{"fecha": "2026-01-01", "tipo": "inamovible", "nombre": "Año nuevo"}]
        ).encode()
        with patch("urllib.request.urlopen", return_value=BytesIO(payload)):
            resp = self.client.post(
                reverse("core:holidays-import"), {"year": 2026}, format="json"
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"year": 2026, "count": 1})

    def test_rejects_invalid_year(self):
        resp = self.client.post(
            reverse("core:holidays-import"), {"year": "nope"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.client.post(
            reverse("core:holidays-import"), {"year": 1999}, format="json"
        )
        self.assertEqual(resp.status_code, 400)

    def test_source_error_is_reported(self):
        from unittest.mock import patch

        with patch("urllib.request.urlopen", side_effect=OSError("sin red")):
            resp = self.client.post(
                reverse("core:holidays-import"), {"year": 2026}, format="json"
            )
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["code"], "IMPORT_FAILED")


class NoAuthTests(APITestCase):
    """Sin usuarios, sesiones ni tokens: todos los endpoints son abiertos."""

    def test_endpoints_answer_without_credentials(self):
        urls = [
            reverse("core:settings"),
            reverse("core:dashboard"),
            reverse("core:holidays-list"),
            reverse("transport:travels-list"),
            reverse("transport:travels-summary"),
            reverse("work:work-sessions-list"),
            reverse("work:work-sessions-current"),
            reverse("work:work-plans-list"),
            reverse("work:today"),
            reverse("work:week"),
            reverse("work:hours-monthly-summary"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_write_endpoints_work_without_credentials(self):
        resp = self.client.post(
            reverse("transport:travels-list"),
            {"amount": "700.00", "direction": "IDA"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

    def test_auth_apps_are_not_installed(self):
        for app in (
            "django.contrib.auth",
            "django.contrib.sessions",
            "django.contrib.admin",
        ):
            self.assertNotIn(app, django_settings.INSTALLED_APPS)

    def test_drf_has_no_authentication(self):
        self.assertEqual(api_settings.DEFAULT_AUTHENTICATION_CLASSES, [])
        self.assertIsNone(api_settings.UNAUTHENTICATED_USER)


class DashboardTests(APITestCase):
    def test_dashboard_returns_summary(self):
        resp = self.client.get(reverse("core:dashboard"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        for key in (
            "week_start",
            "weekly_target_minutes",
            "worked_minutes",
            "remaining_minutes",
            "accumulated_deficit_minutes",
            "progress_ratio",
            "transport",
            "next_shift",
        ):
            self.assertIn(key, data)
        self.assertEqual(data["weekly_target_minutes"], 1200)
        self.assertIsNone(data["open_session"])
        transport = data["transport"]
        self.assertEqual(transport["limit"], 20)
        self.assertEqual(transport["remaining_company"], 20)
        self.assertEqual(transport["used_company"], 0)
        self.assertIsNone(transport["salary_percentage"])

    def test_dashboard_reflects_open_session(self):
        from work.models import WorkSession

        start = timezone.now() - timedelta(minutes=90)
        WorkSession.objects.create(start_at=start)
        data = self.client.get(reverse("core:dashboard")).json()
        self.assertIsNotNone(data["open_session"])
        self.assertGreaterEqual(data["worked_minutes"], 89)

    def test_dashboard_shows_week_specific_target(self):
        self.client.patch(
            reverse("core:settings"),
            {"weekly_target_minutes": 2400, "max_daily_minutes": 600,
             "apply_from": "this_week"},
            format="json",
        )
        data = self.client.get(reverse("core:dashboard")).json()
        self.assertEqual(data["weekly_target_minutes"], 2400)
