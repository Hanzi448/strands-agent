"""Tests for `seed.run_seed`: the CLI orchestrating every seed step.

Offline throughout: `seed_sample_appointments` is driven end to end
through the real `tools.scheduling`/`tools.booking`/`tools.patients`
functions against the same fakes `test_booking.py`'s `tables` fixture
uses, so a rule that drifted between what this script assumes and what
booking actually enforces would show up as a raised exception here rather
than as a failed real seed run.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from tests.test_booking import tables  # noqa: F401
from tests.test_scheduling import (
    COSMETIC_ID,
    DENTAL_ID,
    FakeClinicsTable,
    cosmetic_clinic,
    dental_clinic,
)
from tools.errors import ConfigurationError, NotFoundError
from tools.schema import ClinicAttrs

from seed import clinic_data, run_seed, sample_data
from seed.sample_data import SampleAppointment

# A fixed reference date rather than the real one, so a sample spec's
# `slot_index` lands on a predictable day no matter when this suite runs.
TODAY = date(2026, 8, 3)  # A Monday.


class FakeWritableClinicsTable:
    """`get_item`/`put_item` over a dict, for `seed_clinics`."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def get_item(self, *, Key: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        item = self.items.get(Key[ClinicAttrs.CLINIC_ID])
        return {"Item": item} if item is not None else {}

    def put_item(self, *, Item: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        self.items[Item[ClinicAttrs.CLINIC_ID]] = dict(Item)
        return {}


# --------------------------------------------------------------------------
# seed_clinics
# --------------------------------------------------------------------------


def test_seed_clinics_writes_both_demo_clinics(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeWritableClinicsTable()
    monkeypatch.setattr(run_seed, "clinics_table", lambda: fake)

    written = run_seed.seed_clinics()

    assert written == [DENTAL_ID, COSMETIC_ID]
    assert set(fake.items) == {DENTAL_ID, COSMETIC_ID}
    assert fake.items[DENTAL_ID][ClinicAttrs.NAME] == "Bright Smile Dental"


def test_seed_clinics_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeWritableClinicsTable()
    monkeypatch.setattr(run_seed, "clinics_table", lambda: fake)

    run_seed.seed_clinics()
    run_seed.seed_clinics()

    assert set(fake.items) == {DENTAL_ID, COSMETIC_ID}


# --------------------------------------------------------------------------
# book_sample_appointment / seed_sample_appointments
# --------------------------------------------------------------------------


def test_book_sample_appointment_books_the_slot_at_the_requested_index(tables) -> None:
    tables(clinics=FakeClinicsTable(dental_clinic()))
    spec = SampleAppointment(
        service_id="checkup",
        patient_name="Test Patient",
        patient_phone="+44 7700 900099",
        patient_email="test@example.com",
        notes=None,
        days_ahead=1,
        slot_index=0,
    )

    result = run_seed.book_sample_appointment(DENTAL_ID, spec, today=TODAY)

    assert result["clinic_id"] == DENTAL_ID
    assert result["service"]["id"] == "checkup"
    assert result["patient"]["name"] == "Test Patient"
    assert result["patient"]["is_new"] is True


def test_book_sample_appointment_reconciles_a_nationally_spoken_number(tables) -> None:
    """One dental spec uses a national-form phone on purpose
    (`sample_data`'s module docstring) -- this pins that it still resolves
    against the clinic's own `country_code` rather than raising."""
    tables(clinics=FakeClinicsTable({**dental_clinic(), "country_code": "44"}))
    spec = next(s for s in sample_data.DENTAL_APPOINTMENTS if not s.patient_phone.startswith("+"))

    result = run_seed.book_sample_appointment(DENTAL_ID, spec, today=TODAY)

    assert result["patient"]["phone"] == "447700900002"


def test_book_sample_appointment_fails_loudly_when_the_clinic_does_not_exist(tables) -> None:
    tables(clinics=FakeClinicsTable())
    spec = sample_data.DENTAL_APPOINTMENTS[0]

    with pytest.raises(NotFoundError):
        run_seed.book_sample_appointment(DENTAL_ID, spec, today=TODAY)


def test_seed_sample_appointments_books_every_spec_for_both_clinics(tables) -> None:
    tables(clinics=FakeClinicsTable(dental_clinic(), cosmetic_clinic()))

    booked = run_seed.seed_sample_appointments(today=TODAY)

    expected = sum(len(specs) for specs in sample_data.SAMPLE_APPOINTMENTS_BY_CLINIC.values())
    assert len(booked) == expected
    assert {b["clinic_id"] for b in booked} == {DENTAL_ID, COSMETIC_ID}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_parse_args_defaults() -> None:
    options = run_seed.parse_args([])
    assert options.skip == frozenset()
    assert options.dry_run is False
    assert options.verbose is False


def test_parse_args_skip_is_repeatable() -> None:
    options = run_seed.parse_args(["--skip", "faq", "--skip", "staff"])
    assert options.skip == frozenset({"faq", "staff"})


def test_parse_args_rejects_an_unknown_step() -> None:
    with pytest.raises(SystemExit):
        run_seed.parse_args(["--skip", "not-a-step"])


def test_dry_run_touches_no_aws_client(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """The only mode this environment can actually run
    (`progress-tracker.md` -> Session Notes) -- pinned by making every
    client accessor raise if called at all."""

    def _forbidden() -> None:
        raise AssertionError("dry-run must not build an AWS client")

    monkeypatch.setattr(run_seed, "clinics_table", _forbidden)

    exit_code = run_seed.main(["--dry-run"])

    assert exit_code == run_seed.EXIT_OK
    out = capsys.readouterr().out
    assert "Bright Smile Dental" in out
    assert "Lumiere Aesthetics" in out
    assert "staff+clinic-dental@clinicpilot.demo" in out


def test_dry_run_respects_skip(capsys) -> None:
    exit_code = run_seed.main(["--dry-run", "--skip", "clinics", "--skip", "staff"])

    assert exit_code == run_seed.EXIT_OK
    out = capsys.readouterr().out
    assert "clinics:" not in out
    assert "staff:" not in out
    assert "appointments:" in out
    assert "faq:" in out


def test_main_reports_a_failed_step_but_keeps_running_the_rest(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    fake_clinics = FakeWritableClinicsTable()
    monkeypatch.setattr(run_seed, "clinics_table", lambda: fake_clinics)
    monkeypatch.setattr(
        run_seed,
        "seed_sample_appointments",
        lambda **_: (_ for _ in ()).throw(ConfigurationError("no slots")),
    )
    ran_staff = {"called": False}

    def _fake_staff() -> dict[str, str]:
        ran_staff["called"] = True
        return {}

    monkeypatch.setattr(run_seed, "seed_staff_accounts", _fake_staff)
    monkeypatch.setattr(run_seed, "seed_faq", dict)

    exit_code = run_seed.main([])

    assert exit_code == run_seed.EXIT_STEP_FAILED
    assert ran_staff["called"] is True
    assert set(fake_clinics.items) == {DENTAL_ID, COSMETIC_ID}
    err = capsys.readouterr().err
    assert "appointments" in err
    assert "no slots" in err
