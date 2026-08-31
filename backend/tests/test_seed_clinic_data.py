"""Tests for `seed.clinic_data`: the two demo `Clinics` items.

The strongest check here is not a shape assertion but an end-to-end one:
each built item is fed through the real `tools.scheduling.check_availability`
against a fake table, exactly as `test_scheduling.py`'s own fixtures are --
because a config that merely *looks* right (all seven weekday keys, sane
durations) can still be unusable by the availability engine, and that is
the failure a demo would actually hit.
"""

from __future__ import annotations

import pytest
from tests.test_scheduling import COSMETIC_ID, DENTAL_ID, FakeAppointmentsTable, FakeClinicsTable
from tools import scheduling
from tools.schema import WEEKDAY_KEYS, ClinicAttrs, ServiceAttrs

from seed import clinic_data


@pytest.fixture
def clinics_table(monkeypatch: pytest.MonkeyPatch):
    def install(*clinics):
        fake = FakeClinicsTable(*clinics)
        monkeypatch.setattr(scheduling, "clinics_table", lambda: fake)
        monkeypatch.setattr(scheduling, "appointments_table", lambda: FakeAppointmentsTable())
        return fake

    return install


@pytest.mark.parametrize(
    "clinic_id, build_item",
    [(DENTAL_ID, clinic_data.dental_clinic_item), (COSMETIC_ID, clinic_data.cosmetic_clinic_item)],
)
def test_clinic_id_matches_the_id_the_rest_of_the_suite_uses(clinic_id, build_item) -> None:
    """`test_scheduling.py`'s `DENTAL_ID`/`COSMETIC_ID` are the same strings
    `tools.faq.knowledge_base_id_env_var` and the CDK stacks key everything
    on -- a drift here would seed a clinic nothing else in the system
    recognises."""
    assert build_item()[ClinicAttrs.CLINIC_ID] == clinic_id


@pytest.mark.parametrize("build_item", [clinic_data.dental_clinic_item, clinic_data.cosmetic_clinic_item])
def test_all_seven_weekdays_are_present(build_item) -> None:
    hours = build_item()[ClinicAttrs.HOURS]
    assert set(hours) == set(WEEKDAY_KEYS)


@pytest.mark.parametrize("build_item", [clinic_data.dental_clinic_item, clinic_data.cosmetic_clinic_item])
def test_every_interval_closes_after_it_opens(build_item) -> None:
    hours = build_item()[ClinicAttrs.HOURS]
    for day, intervals in hours.items():
        for interval in intervals:
            assert interval["open"] < interval["close"], (day, interval)


@pytest.mark.parametrize("build_item", [clinic_data.dental_clinic_item, clinic_data.cosmetic_clinic_item])
def test_every_service_has_a_positive_duration(build_item) -> None:
    services = build_item()[ClinicAttrs.SERVICES]
    assert services
    for service in services:
        assert service[ServiceAttrs.DURATION_MINUTES] > 0


@pytest.mark.parametrize("build_item", [clinic_data.dental_clinic_item, clinic_data.cosmetic_clinic_item])
def test_slot_minutes_is_a_positive_int(build_item) -> None:
    assert isinstance(build_item()[ClinicAttrs.SLOT_MINUTES], int)
    assert build_item()[ClinicAttrs.SLOT_MINUTES] > 0


@pytest.mark.parametrize("build_item", [clinic_data.dental_clinic_item, clinic_data.cosmetic_clinic_item])
def test_country_code_is_digits_only_no_leading_plus(build_item) -> None:
    country_code = build_item()[ClinicAttrs.COUNTRY_CODE]
    assert country_code.isdigit()


def test_the_two_demo_clinics_differ_on_every_availability_axis() -> None:
    """`architecture.md` -> Storage Model: "The two demo clinics differ in
    all four" -- timezone is the one axis they deliberately share (both UK),
    so this checks the other three: hours shape, slot grid, and services."""
    dental = clinic_data.dental_clinic_item()
    cosmetic = clinic_data.cosmetic_clinic_item()
    assert dental[ClinicAttrs.HOURS] != cosmetic[ClinicAttrs.HOURS]
    assert dental[ClinicAttrs.SLOT_MINUTES] != cosmetic[ClinicAttrs.SLOT_MINUTES]
    assert {s[ServiceAttrs.ID] for s in dental[ClinicAttrs.SERVICES]}.isdisjoint(
        {s[ServiceAttrs.ID] for s in cosmetic[ClinicAttrs.SERVICES]}
    )


def test_dental_clinic_is_usable_by_the_real_availability_engine(clinics_table) -> None:
    """End-to-end: the built item, read by `check_availability` itself."""
    clinics_table(clinic_data.dental_clinic_item())
    result = scheduling.check_availability(DENTAL_ID, "2026-09-02", "checkup", days=7)
    assert result["days_checked"]
    assert any(day["is_open"] for day in result["days_checked"])


def test_cosmetic_clinic_is_usable_by_the_real_availability_engine(clinics_table) -> None:
    clinics_table(clinic_data.cosmetic_clinic_item())
    result = scheduling.check_availability(COSMETIC_ID, "2026-09-02", "consult", days=7)
    assert result["days_checked"]
    assert any(day["is_open"] for day in result["days_checked"])


def test_demo_clinics_tuple_builds_both_in_dental_then_cosmetic_order() -> None:
    items = [build() for build in clinic_data.DEMO_CLINICS]
    assert [item[ClinicAttrs.CLINIC_ID] for item in items] == [DENTAL_ID, COSMETIC_ID]
