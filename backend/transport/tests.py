"""Pruebas de reglas de negocio del módulo de transporte.

Cubre: derivación COMPANY/PERSONAL, reinicio de cupo, anulación que libera
cupo, importes históricos, vigencia del cupo, next-direction, anti doble tap,
saldo nunca negativo y porcentaje sobre el sueldo.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import SETTING_MONTHLY_TRIP_LIMIT, Settings
from core.services import set_setting
from transport.models import TravelRecord

TZ = ZoneInfo("America/Argentina/Cordoba")

TODAY = timezone.localdate()
THIS_MONTH = TODAY.replace(day=1)
# Primer día del mes anterior (restarle un día al PRIMER día del mes).
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def month_after(first: date) -> date:
    if first.month == 12:
        return date(first.year + 1, 1, 1)
    return date(first.year, first.month + 1, 1)


NEXT_MONTH = month_after(THIS_MONTH)


def at(day: date, hour: int = 12, minute: int = 0):
    """Datetime aware (zona Córdoba) para un día/hora concretos."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


def iso(day: date, hour: int = 12, minute: int = 0) -> str:
    return at(day, hour, minute).isoformat()


class TravelTestCase(APITestCase):
    """Base: tarifa vigente cargada y helpers de alta."""

    def setUp(self):
        self.settings = Settings.load()
        self.settings.current_fare = Decimal("750.00")
        self.settings.save()
        self.url = reverse("transport:travels-list")

    def _post(self, **data):
        return self.client.post(self.url, data, format="json")

    def _patch(self, pk, **data):
        return self.client.patch(f"{self.url}{pk}/", data, format="json")

    def _make(
        self,
        day: date,
        count: int = 1,
        direction: str = TravelRecord.Direction.IDA,
        amount: Decimal = Decimal("700.00"),
        hour_offset: int = 0,
    ) -> list[TravelRecord]:
        """Crea `count` viajes por ORM (sin pasar por la API).

        Se espacian cada 20 minutos desde las 06:00 (+ hour_offset) para que
        el orden por (occurred_at, id) sea determinista.
        """
        records = []
        base = at(day, 6 + hour_offset, 0)
        for i in range(count):
            records.append(
                TravelRecord.objects.create(
                    occurred_at=base + timedelta(minutes=20 * i),
                    direction=direction,
                    amount=amount,
                )
            )
        return records

    def _summary(self, month: date) -> dict:
        return self.client.get(
            f"{self.url}summary/?month={month.strftime('%Y-%m')}"
        ).json()

    def _list(self, **params) -> dict:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return self.client.get(f"{self.url}?{query}").json()

    def _derived(self, pk: int, **params) -> str | None:
        for row in self._list(**params)["results"]:
            if row["id"] == pk:
                return row["payment_type"]
        return None


class TravelDefaultsTests(TravelTestCase):
    """POST con defaults: ahora, tarifa vigente y dirección sugerida."""

    def test_amount_defaults_to_current_fare(self):
        resp = self._post(occurred_at=iso(TODAY - timedelta(days=1)))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TravelRecord.objects.get().amount, Decimal("750.00"))

    def test_defaults_for_occurred_at_amount_and_direction(self):
        before = timezone.now() - timedelta(seconds=2)
        resp = self._post()
        after = timezone.now() + timedelta(seconds=2)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        data = resp.json()
        occurred = datetime.fromisoformat(data["occurred_at"])
        self.assertGreaterEqual(occurred, before)
        self.assertLessEqual(occurred, after)
        self.assertEqual(data["amount"], "750.00")
        # Sin viajes previos: la sugerida es IDA.
        self.assertEqual(data["direction"], "IDA")

    def test_amount_is_required_when_fare_is_not_configured(self):
        self.settings.current_fare = Decimal("0")
        self.settings.save()
        resp = self._post(occurred_at=iso(TODAY - timedelta(days=1)))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("amount", resp.json())

    def test_occurred_at_cannot_be_future(self):
        resp = self._post(occurred_at=iso(TODAY + timedelta(days=1)))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_amount_must_be_positive(self):
        resp = self._post(
            occurred_at=iso(TODAY - timedelta(days=1)), amount="0"
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_delete_is_not_allowed(self):
        self._make(TODAY - timedelta(days=1))
        pk = TravelRecord.objects.get().pk
        resp = self.client.delete(f"{self.url}{pk}/")
        self.assertEqual(resp.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(TravelRecord.objects.count(), 1)

    def test_patch_edits_and_voids_without_deleting(self):
        record = self._make(TODAY - timedelta(days=1))[0]
        resp = self._patch(record.pk, amount="810.00")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["amount"], "810.00")

        resp = self._patch(record.pk, status="VOIDED")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["status"], "VOIDED")
        self.assertEqual(TravelRecord.objects.count(), 1)
        self.assertFalse(TravelRecord.objects.get().is_active)


class PaymentTypeDerivationTests(TravelTestCase):
    """payment_type es derivado: primeros N del mes = COMPANY."""

    def setUp(self):
        super().setUp()
        # Cupo chico para poder provocar PERSONAL con pocos registros.
        set_setting(SETTING_MONTHLY_TRIP_LIMIT, 2, THIS_MONTH)

    def test_first_n_are_company_and_the_rest_personal(self):
        trips = self._make(THIS_MONTH, 3)
        month = f"{THIS_MONTH:%Y-%m}"
        self.assertEqual(self._derived(trips[0].pk, month=month), "COMPANY")
        self.assertEqual(self._derived(trips[1].pk, month=month), "COMPANY")
        self.assertEqual(self._derived(trips[2].pk, month=month), "PERSONAL")

    def test_earlier_trip_recalculates_the_derivation(self):
        set_setting(SETTING_MONTHLY_TRIP_LIMIT, 1, THIS_MONTH)
        first, second = self._make(THIS_MONTH, 2)
        # Un viaje anterior a ambos (pero en el mismo mes) desplaza a todos.
        earlier = TravelRecord.objects.create(
            occurred_at=at(THIS_MONTH, 1, 0),
            direction=TravelRecord.Direction.IDA,
            amount=Decimal("700.00"),
        )
        month = f"{THIS_MONTH:%Y-%m}"
        self.assertEqual(self._derived(earlier.pk, month=month), "COMPANY")
        # Antes de insertarlo, `first` era el COMPANY del mes.
        self.assertEqual(self._derived(first.pk, month=month), "PERSONAL")
        self.assertEqual(self._derived(second.pk, month=month), "PERSONAL")

    def test_voiding_a_trip_frees_the_limit(self):
        set_setting(SETTING_MONTHLY_TRIP_LIMIT, 1, THIS_MONTH)
        first, second = self._make(THIS_MONTH, 2)
        month = f"{THIS_MONTH:%Y-%m}"
        self.assertEqual(self._derived(first.pk, month=month), "COMPANY")
        self.assertEqual(self._derived(second.pk, month=month), "PERSONAL")

        # Al anular el primero, el segundo pasa a consumir el cupo.
        resp = self._patch(first.pk, status="VOIDED")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(self._derived(second.pk, month=month), "COMPANY")
        summary = self._summary(THIS_MONTH)
        self.assertEqual(summary["used_company"], 1)
        self.assertEqual(summary["personal_count"], 0)

    def test_list_filters_by_derived_payment_type(self):
        self._make(THIS_MONTH, 3)
        month = f"{THIS_MONTH:%Y-%m}"
        company = self._list(month=month, payment_type="COMPANY")
        personal = self._list(month=month, payment_type="PERSONAL")
        self.assertEqual(company["count"], 2)
        self.assertEqual(personal["count"], 1)
        self.assertEqual(
            {r["payment_type"] for r in company["results"]}, {"COMPANY"}
        )

    def test_payment_type_is_read_only(self):
        trip = self._make(THIS_MONTH, 1)[0]
        resp = self._patch(trip.pk, payment_type="PERSONAL")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # El campo se ignora: sigue derivado (COMPANY con cupo 2).
        self.assertEqual(resp.json()["payment_type"], "COMPANY")


class MonthlyLimitTests(TravelTestCase):
    """Cupo mensual: reinicio por mes y vigencia de los cambios."""

    def test_limit_resets_in_a_new_month(self):
        self._make(LAST_MONTH, 20, amount=Decimal("10.00"))
        self._make(THIS_MONTH, 1, amount=Decimal("10.00"))

        last = self._summary(LAST_MONTH)
        self.assertEqual(last["used_company"], 20)
        self.assertEqual(last["remaining_company"], 0)

        current = self._summary(THIS_MONTH)
        self.assertEqual(current["used_company"], 1)
        self.assertEqual(current["remaining_company"], 19)

    def test_remaining_is_never_negative(self):
        self._make(LAST_MONTH, 23, amount=Decimal("10.00"))  # límite 20
        summary = self._summary(LAST_MONTH)
        self.assertEqual(summary["limit"], 20)
        self.assertEqual(summary["used_company"], 20)
        self.assertEqual(summary["remaining_company"], 0)  # nunca negativo
        self.assertEqual(summary["personal_count"], 3)
        self.assertEqual(summary["total_count"], 23)

    def test_limit_change_from_next_month_does_not_alter_previous_months(self):
        self._make(LAST_MONTH, 3, amount=Decimal("10.00"))
        resp = self.client.patch(
            reverse("core:settings"),
            {"monthly_trip_limit": 15, "apply_from": "next_month"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        self.assertEqual(self._summary(LAST_MONTH)["limit"], 20)
        self.assertEqual(self._summary(THIS_MONTH)["limit"], 20)
        self.assertEqual(self._summary(NEXT_MONTH)["limit"], 15)


class SummaryShapeTests(TravelTestCase):
    """GET /api/travels/summary/: cifras derivadas del mes consultado."""

    def test_summary_counts_and_amounts(self):
        self._make(THIS_MONTH, 3, amount=Decimal("700.00"))
        self._make(THIS_MONTH, 2, amount=Decimal("800.00"), hour_offset=3)
        summary = self._summary(THIS_MONTH)
        self.assertEqual(summary["month"], f"{THIS_MONTH:%Y-%m}")
        self.assertEqual(summary["limit"], 20)
        self.assertEqual(summary["used_company"], 5)
        self.assertEqual(summary["remaining_company"], 15)
        self.assertEqual(summary["personal_count"], 0)
        self.assertEqual(summary["total_count"], 5)
        self.assertEqual(Decimal(summary["total_value"]), Decimal("3700.00"))
        self.assertEqual(Decimal(summary["company_value"]), Decimal("3700.00"))
        self.assertEqual(Decimal(summary["out_of_pocket_value"]), Decimal("0.00"))
        self.assertIsNone(summary["salary_percentage"])

    def test_personal_value_and_salary_percentage(self):
        set_setting(SETTING_MONTHLY_TRIP_LIMIT, 1, THIS_MONTH)
        self._make(THIS_MONTH, 1, amount=Decimal("700.00"))
        self._make(THIS_MONTH, 2, amount=Decimal("800.00"), hour_offset=3)
        self.settings.monthly_salary = Decimal("300000.00")
        self.settings.save()

        summary = self._summary(THIS_MONTH)
        self.assertEqual(summary["used_company"], 1)
        self.assertEqual(summary["personal_count"], 2)
        self.assertEqual(
            Decimal(summary["out_of_pocket_value"]), Decimal("1600.00")
        )
        # 1600 / 300000 × 100 = 0,53 %
        self.assertEqual(summary["salary_percentage"], 0.53)

    def test_salary_percentage_is_null_without_salary(self):
        set_setting(SETTING_MONTHLY_TRIP_LIMIT, 1, THIS_MONTH)
        self._make(THIS_MONTH, 2, amount=Decimal("800.00"))
        self.assertIsNone(self.settings.monthly_salary)
        summary = self._summary(THIS_MONTH)
        self.assertEqual(summary["personal_count"], 1)
        self.assertIsNone(summary["salary_percentage"])

    def test_voided_trips_do_not_count(self):
        trips = self._make(THIS_MONTH, 2, amount=Decimal("700.00"))
        self._patch(trips[0].pk, status="VOIDED")
        summary = self._summary(THIS_MONTH)
        self.assertEqual(summary["total_count"], 1)
        self.assertEqual(summary["used_company"], 1)
        self.assertEqual(Decimal(summary["total_value"]), Decimal("700.00"))
        # El registro anulado sigue existiendo en la base.
        self.assertEqual(
            TravelRecord.objects.filter(status="VOIDED").count(), 1
        )

    def test_historical_amounts_survive_fare_change(self):
        self._make(TODAY - timedelta(days=2), amount=Decimal("700.00"))
        resp = self.client.patch(
            reverse("core:settings"), {"current_fare": "990.00"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # El registro histórico conserva su importe original.
        self.assertEqual(
            TravelRecord.objects.latest("id").amount, Decimal("700.00")
        )
        # Un viaje nuevo usa la tarifa nueva.
        resp = self._post(occurred_at=iso(TODAY - timedelta(days=3)))
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            TravelRecord.objects.latest("id").amount, Decimal("990.00")
        )

    def test_list_filters_by_month_and_status(self):
        self._make(LAST_MONTH, 1, amount=Decimal("500.00"))
        self._make(THIS_MONTH, 2, amount=Decimal("700.00"))
        self._patch(TravelRecord.objects.latest("pk").pk, status="VOIDED")

        data = self._list(month=f"{THIS_MONTH:%Y-%m}")
        self.assertEqual(data["count"], 2)
        data = self._list(month=f"{THIS_MONTH:%Y-%m}", status="VOIDED")
        self.assertEqual(data["count"], 1)
        data = self._list(month=f"{LAST_MONTH:%Y-%m}")
        self.assertEqual(data["count"], 1)


class NextDirectionTests(TravelTestCase):
    """GET /api/travels/next-direction/."""

    def _next(self) -> str:
        return self.client.get(f"{self.url}next-direction/").json()["direction"]

    def test_without_trips_returns_ida(self):
        self.assertEqual(self._next(), "IDA")

    def test_last_trip_from_a_previous_day_returns_ida(self):
        TravelRecord.objects.create(
            occurred_at=at(TODAY - timedelta(days=1), 18, 0),
            direction=TravelRecord.Direction.VUELTA,
            amount=Decimal("700.00"),
        )
        self.assertEqual(self._next(), "IDA")

    def test_last_trip_today_ida_returns_vuelta(self):
        TravelRecord.objects.create(
            occurred_at=at(TODAY, 8, 0),
            direction=TravelRecord.Direction.IDA,
            amount=Decimal("700.00"),
        )
        self.assertEqual(self._next(), "VUELTA")

    def test_last_trip_today_vuelta_returns_ida(self):
        TravelRecord.objects.create(
            occurred_at=at(TODAY, 8, 0),
            direction=TravelRecord.Direction.VUELTA,
            amount=Decimal("700.00"),
        )
        self.assertEqual(self._next(), "IDA")

    def test_voided_trips_are_ignored(self):
        TravelRecord.objects.create(
            occurred_at=timezone.now(),
            direction=TravelRecord.Direction.IDA,
            amount=Decimal("700.00"),
            status="VOIDED",
        )
        self.assertEqual(self._next(), "IDA")


class DoubleTapTests(TravelTestCase):
    """Anti doble toque: 409 si hay mismo dirección en los últimos 60 s."""

    def test_second_tap_with_same_direction_returns_409(self):
        first = self._post(direction="IDA")  # occurred_at = ahora (default)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self._post(direction="IDA")
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("60", second.json()["detail"])
        self.assertEqual(TravelRecord.objects.count(), 1)

    def test_force_allows_duplicate(self):
        self.assertEqual(
            self._post(direction="IDA").status_code, status.HTTP_201_CREATED
        )
        self.assertEqual(
            self._post(direction="IDA").status_code, status.HTTP_409_CONFLICT
        )
        resp = self.client.post(
            f"{self.url}?force=true", {"direction": "IDA"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TravelRecord.objects.count(), 2)

    def test_default_taps_use_the_suggested_direction(self):
        # El default es la dirección sugerida: después de registrar una IDA
        # la sugerida pasa a VUELTA, por lo que el segundo alta por defecto
        # no se considera doble toque (son viajes de distinta dirección).
        first = self._post()
        second = self._post()
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(first.json()["direction"], "IDA")
        self.assertEqual(second.json()["direction"], "VUELTA")

    def test_opposite_direction_is_not_blocked(self):
        first = self._post(direction="IDA")
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self._post(direction="VUELTA")
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        self.assertEqual(TravelRecord.objects.count(), 2)

    def test_trips_older_than_60_seconds_are_not_blocked(self):
        past = iso(TODAY - timedelta(days=1), 9, 0)
        self.assertEqual(
            self._post(occurred_at=past).status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            self._post(occurred_at=past).status_code,
            status.HTTP_201_CREATED,
        )

    def test_voided_trip_does_not_block(self):
        TravelRecord.objects.create(
            occurred_at=timezone.now(),
            direction=TravelRecord.Direction.IDA,
            amount=Decimal("700.00"),
            status="VOIDED",
        )
        resp = self._post(direction="IDA")
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class MonthlyHistoryTests(TravelTestCase):
    """GET /api/travels/monthly-history/?months=N."""

    def test_history_shape_and_derived_split(self):
        set_setting(SETTING_MONTHLY_TRIP_LIMIT, 2, LAST_MONTH)
        # El cupo de 2 es solo del mes pasado: este mes vuelve al default.
        set_setting(SETTING_MONTHLY_TRIP_LIMIT, 20, THIS_MONTH)
        self._make(LAST_MONTH, 2, direction=TravelRecord.Direction.IDA)
        self._make(
            LAST_MONTH, 1, direction=TravelRecord.Direction.VUELTA,
            hour_offset=3,
        )
        self._make(THIS_MONTH, 1)
        self.settings.monthly_salary = Decimal("300000.00")
        self.settings.save()

        data = self.client.get(f"{self.url}monthly-history/?months=6").json()
        self.assertEqual(
            [m["month"] for m in data],
            [f"{LAST_MONTH:%Y-%m}", f"{THIS_MONTH:%Y-%m}"],
        )

        last = data[0]
        self.assertEqual(last["ida_count"], 2)
        self.assertEqual(last["vuelta_count"], 1)
        self.assertEqual(last["company_count"], 2)  # cupo 2 vigente
        self.assertEqual(last["personal_count"], 1)
        self.assertEqual(Decimal(last["total_value"]), Decimal("2100.00"))
        self.assertEqual(
            Decimal(last["out_of_pocket_value"]), Decimal("700.00")
        )
        self.assertEqual(last["salary_percentage"], 0.23)  # 700/300000
        self.assertEqual(last["limit"], 2)

        current = data[1]
        self.assertEqual(current["limit"], 20)  # cupo vigente de este mes
        self.assertEqual(current["company_count"], 1)
        self.assertEqual(current["personal_count"], 0)
        # Hay sueldo cargado pero gasto propio 0 → 0.0 % (no None).
        self.assertEqual(current["salary_percentage"], 0.0)

    def test_history_is_limited_to_months_param(self):
        self._make(LAST_MONTH, 1)
        self._make(THIS_MONTH, 1)
        data = self.client.get(f"{self.url}monthly-history/?months=1").json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["month"], f"{THIS_MONTH:%Y-%m}")

    def test_history_skips_months_without_active_trips(self):
        trips = self._make(LAST_MONTH, 1)
        self._patch(trips[0].pk, status="VOIDED")
        data = self.client.get(f"{self.url}monthly-history/?months=6").json()
        self.assertEqual(data, [])

    def test_monthly_comparison_keeps_classic_shape(self):
        self._make(LAST_MONTH, 2, amount=Decimal("700.00"))
        data = self.client.get(f"{self.url}monthly-comparison/?months=6").json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["month"], f"{LAST_MONTH:%Y-%m}")
        self.assertIn("month_label", data[0])
        self.assertEqual(Decimal(data[0]["company_amount"]), Decimal("1400.00"))
        self.assertEqual(Decimal(data[0]["personal_amount"]), Decimal("0.00"))
