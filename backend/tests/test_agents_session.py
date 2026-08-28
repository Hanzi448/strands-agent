"""Tests for `ClinicSession`, the per-session clinic binding.

This object carries the tenant boundary for the whole agent layer
(`architecture.md` -> Invariants #1). Two things are asserted here and
nowhere else.

*It fails at session start, not mid-call.* A bad `clinic_id`, a missing
clinic, or a timezone the process cannot resolve all surface before the
greeting -- which is the reason `start` reads the clinic at all rather
than deferring to the first tool call.

*It tells the model the truth and nothing extra.* `describe` has to carry
today's local date (without it "next Tuesday" is unresolvable and a model
invents a year) and the clinic's services with their ids. It must *not*
carry opening hours: a model holding the hours is a model that can answer
"we're open until five" without asking `check_availability`, which is the
one thing the availability rule exists to prevent.

The clinic fixtures are the demo configs from `architecture.md`, imported
from `test_scheduling` rather than restated, so the suites cannot drift.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from agents import session as session_module
from agents.session import ClinicSession
from tests.test_scheduling import (
    COSMETIC_ID,
    DENTAL_ID,
    FakeClinicsTable,
    cosmetic_clinic,
    dental_clinic,
)
from tools import scheduling
from tools.errors import ConfigurationError, NotFoundError, ValidationError


@pytest.fixture
def clinics(monkeypatch: pytest.MonkeyPatch):
    """Point `get_clinic` at a fake, and hand it back to assert on."""

    def install(*items: dict[str, Any]) -> FakeClinicsTable:
        table = FakeClinicsTable(*(items or (dental_clinic(), cosmetic_clinic())))
        monkeypatch.setattr(scheduling, "clinics_table", lambda: table)
        return table

    return install


def pin_clock(monkeypatch: pytest.MonkeyPatch, instant: datetime) -> None:
    """Freeze the wall clock `today()` reads."""

    class Frozen(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return instant if tz is None else instant.astimezone(tz)

    monkeypatch.setattr(session_module, "datetime", Frozen)


def dental() -> ClinicSession:
    return ClinicSession(clinic_id=DENTAL_ID, clinic=dental_clinic())


# --------------------------------------------------------------------------
# Starting a session
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clinic_id", ["", "   ", None])
def test_a_blank_clinic_id_fails_before_any_read(clinic_id, clinics) -> None:
    """The tenant check runs first, exactly as it does in the tool layer."""
    table = clinics()
    with pytest.raises(ValidationError):
        ClinicSession.start(clinic_id)
    assert table.requested == []


def test_an_unknown_clinic_fails_at_session_start(clinics) -> None:
    clinics()
    with pytest.raises(NotFoundError):
        ClinicSession.start("clinic-nowhere")


def test_an_unresolvable_timezone_fails_at_session_start(clinics) -> None:
    """Deferring this would put a seeding fault inside the first booking,
    where the only thing the patient hears is that something went wrong."""
    broken = dental_clinic() | {"timezone": "Mars/Olympus"}
    clinics(broken)
    with pytest.raises(ConfigurationError):
        ClinicSession.start(DENTAL_ID)


def test_start_reads_the_clinic_once_and_keeps_it(clinics) -> None:
    """A clinic's hours do not change mid-call, and re-reading them would
    put a DynamoDB round trip in the voice path."""
    table = clinics()
    session = ClinicSession.start(DENTAL_ID)
    assert table.requested == [{"clinic_id": DENTAL_ID}]
    session.describe()
    session.services()
    assert table.requested == [{"clinic_id": DENTAL_ID}]


def test_start_binds_the_clinic_it_was_given(clinics) -> None:
    clinics()
    assert ClinicSession.start(COSMETIC_ID).clinic_id == COSMETIC_ID


# --------------------------------------------------------------------------
# The clinic's own frame of reference
# --------------------------------------------------------------------------


def test_today_is_the_clinics_local_date_not_the_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """23:30Z on the 27th is already the 28th in London under BST -- the
    case that puts a booking on the wrong day if UTC is used as the date."""
    pin_clock(monkeypatch, datetime(2026, 7, 27, 23, 30, tzinfo=timezone.utc))
    assert dental().today() == date(2026, 7, 28)


def test_timezone_comes_from_the_clinic_item() -> None:
    assert dental().timezone == ZoneInfo("Europe/London")


def test_clinic_name_falls_back_to_the_id() -> None:
    """A prompt saying "You are answering for None" is worse than one
    saying the id, and a nameless clinic is a seeding fault, not a
    reason to refuse the call."""
    nameless = ClinicSession(clinic_id=DENTAL_ID, clinic={"timezone": "Europe/London"})
    assert nameless.clinic_name == DENTAL_ID


def test_services_are_normalised_out_of_dynamodb_decimals() -> None:
    """The stored durations are `Decimal`; a prompt built from them
    would say "15 minutes" as `Decimal('15')`."""
    entries = dental().services()
    assert [entry["id"] for entry in entries] == ["checkup", "cleaning"]
    assert [entry["duration_minutes"] for entry in entries] == [15, 30]
    assert all(isinstance(entry["duration_minutes"], int) for entry in entries)


# --------------------------------------------------------------------------
# What the model is told
# --------------------------------------------------------------------------


def test_describe_names_the_clinic_and_its_kind() -> None:
    text = dental().describe()
    assert "Bright Smile Dental" in text
    assert "dental" in text


def test_describe_carries_todays_date_both_ways(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spoken, so the model reads it out as a date rather than digits;
    and as `YYYY-MM-DD`, because that is what the tools take."""
    pin_clock(monkeypatch, datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc))
    text = dental().describe()
    assert "Wednesday, 01 July 2026" in text
    assert "2026-07-01" in text
    assert "Europe/London" in text


def test_describe_lists_each_service_with_its_id_and_length() -> None:
    """`resolve_service` takes either, and the model has to say the name
    while passing the id -- so it needs both in front of it."""
    text = dental().describe()
    assert "Check-up (id: checkup), 15 minutes" in text
    assert "Dental cleaning (id: cleaning), 30 minutes" in text


def test_describe_withholds_the_opening_hours() -> None:
    """The one deliberate omission. `check_availability` composes hours,
    closures, duration and existing bookings; a copy of the hours in the
    prompt is an invitation to answer without asking it."""
    text = dental().describe()
    for fragment in ("09:00", "13:00", "17:30", "Staff training"):
        assert fragment not in text


def test_two_clinics_describe_themselves_differently() -> None:
    """The multi-tenant claim, at the prompt layer: the same code gives
    the same agent a different clinic to be."""
    cosmetic = ClinicSession(clinic_id=COSMETIC_ID, clinic=cosmetic_clinic())
    text = cosmetic.describe()
    assert "Lumiere Aesthetics" in text
    assert "Consultation (id: consult), 60 minutes" in text
    assert "Bright Smile Dental" not in text
    assert "Check-up" not in text
