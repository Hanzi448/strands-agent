"""Tests for `check_availability` and the slot composition behind it.

The two clinic fixtures are the demo configs recorded in `architecture.md`
-> Storage Model ("Clinic availability config"): a dental clinic with a
lunch break, 15-minute slots and short services, and a cosmetic clinic
with unbroken hours, 30-minute slots and long ones. They differ on every
axis on purpose -- an availability bug that assumes one clinic's shape
shows up on the other.

DynamoDB is replaced by fakes rather than mocked at the boto3 level: the
tool layer's only contact with it is `clinics_table()`/`appointments_table()`,
so substituting those covers the real code path without credentials.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from tools import scheduling
from tools.errors import ConfigurationError, NotFoundError, ValidationError
from tools.schema import AppointmentStatus

# --------------------------------------------------------------------------
# Fixtures: the two demo clinics from `architecture.md`
# --------------------------------------------------------------------------

DENTAL_ID = "clinic-dental"
COSMETIC_ID = "clinic-cosmetic"

# 2026-07-01 is a Wednesday, in British Summer Time (UTC+1) -- so a London
# clinic's 09:00 local is 08:00Z, which is what makes the conversion
# visible in the assertions rather than accidentally an identity.
WEDNESDAY = "2026-07-01"
SUNDAY = "2026-07-05"
SATURDAY = "2026-07-04"
# 2026-01-07, a Wednesday in GMT (UTC+0): the same clinic, no offset.
WINTER_WEDNESDAY = "2026-01-07"


def dental_clinic() -> dict[str, Any]:
    """Mon-Fri 09:00-13:00 and 14:00-17:30, short Sat morning, 15-min slots."""
    weekday = [
        {"open": "09:00", "close": "13:00"},
        {"open": "14:00", "close": "17:30"},
    ]
    return {
        "clinic_id": DENTAL_ID,
        "name": "Bright Smile Dental",
        "clinic_type": "dental",
        "timezone": "Europe/London",
        "hours": {
            "mon": weekday,
            "tue": weekday,
            "wed": weekday,
            "thu": weekday,
            "fri": weekday,
            "sat": [{"open": "09:00", "close": "12:00"}],
            "sun": [],
        },
        "closures": [{"date": "2026-07-08", "label": "Staff training day"}],
        "services": [
            # Decimals, because that is what DynamoDB hands back.
            {"id": "checkup", "name": "Check-up", "duration_minutes": Decimal("15")},
            {
                "id": "cleaning",
                "name": "Dental cleaning",
                "duration_minutes": Decimal("30"),
            },
        ],
        "slot_minutes": Decimal("15"),
    }


def cosmetic_clinic() -> dict[str, Any]:
    """Tue-Sat 10:00-18:00 unbroken, 30-min slots, 60/90-min services."""
    weekday = [{"open": "10:00", "close": "18:00"}]
    return {
        "clinic_id": COSMETIC_ID,
        "name": "Lumiere Aesthetics",
        "clinic_type": "cosmetic",
        "timezone": "Europe/London",
        "hours": {
            "mon": [],
            "tue": weekday,
            "wed": weekday,
            "thu": weekday,
            "fri": weekday,
            "sat": weekday,
            "sun": [],
        },
        "closures": [],
        "services": [
            {"id": "consult", "name": "Consultation", "duration_minutes": Decimal("60")},
            {"id": "treatment", "name": "Treatment", "duration_minutes": Decimal("90")},
        ],
        "slot_minutes": Decimal("30"),
    }


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeClinicsTable:
    """`get_item` over a dict of clinic items, recording the keys it was asked."""

    def __init__(self, *clinics: dict[str, Any]) -> None:
        self.items = {clinic["clinic_id"]: clinic for clinic in clinics}
        self.requested: list[dict[str, Any]] = []

    def get_item(self, *, Key: dict[str, Any]) -> dict[str, Any]:  # noqa: N803
        self.requested.append(Key)
        item = self.items.get(Key["clinic_id"])
        return {"Item": item} if item is not None else {}


class FakeAppointmentsTable:
    """`query` returning canned pages, recording the query it was given."""

    def __init__(self, *pages: list[dict[str, Any]]) -> None:
        self.pages = [list(page) for page in pages] or [[]]
        self.queries: list[dict[str, Any]] = []

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        # Which page to serve comes from the cursor, as it does in
        # DynamoDB -- so a second, unrelated query starts from page one
        # rather than continuing the previous one's pagination.
        start_key = kwargs.get("ExclusiveStartKey")
        index = 0 if start_key is None else start_key["page"] + 1
        response: dict[str, Any] = {"Items": self.pages[index]}
        if index + 1 < len(self.pages):
            response["LastEvaluatedKey"] = {"page": index}
        return response


def appointment(
    starts_at: str,
    ends_at: str | None = "",
    status: str = AppointmentStatus.SCHEDULED.value,
) -> dict[str, Any]:
    """One `Appointments` item, as the by-start-time index would return it."""
    item: dict[str, Any] = {
        "clinic_id": DENTAL_ID,
        "appointment_id": f"apt_{starts_at}",
        "starts_at": starts_at,
        "status": status,
    }
    if ends_at:
        item["ends_at"] = ends_at
    return item


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch):
    """Point the module's two table accessors at fakes.

    Returns a callable that installs the clinics/appointments fakes and
    hands both back, so a test can assert on what was queried.
    """

    def install(
        clinics: FakeClinicsTable, appointments: FakeAppointmentsTable | None = None
    ) -> tuple[FakeClinicsTable, FakeAppointmentsTable]:
        appointments = appointments or FakeAppointmentsTable()
        monkeypatch.setattr(scheduling, "clinics_table", lambda: clinics)
        monkeypatch.setattr(scheduling, "appointments_table", lambda: appointments)
        return clinics, appointments

    return install


def local_starts(result: dict[str, Any]) -> list[str]:
    return [slot["local_start"] for slot in result["slots"]]


# --------------------------------------------------------------------------
# The tenant boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clinic_id", ["", "   ", None])
def test_blank_clinic_id_fails_before_any_read(clinic_id, tables) -> None:
    """`code-standards.md`: the tenant check runs *before anything else*."""
    clinics, appointments = tables(FakeClinicsTable(dental_clinic()))
    with pytest.raises(ValidationError):
        scheduling.check_availability(clinic_id, WEDNESDAY, "checkup")
    assert clinics.requested == []
    assert appointments.queries == []


def test_unknown_clinic_raises_not_found(tables) -> None:
    tables(FakeClinicsTable(dental_clinic()))
    with pytest.raises(NotFoundError):
        scheduling.check_availability("clinic-nope", WEDNESDAY, "checkup")


def test_query_is_scoped_to_the_requested_clinic(tables) -> None:
    """The appointments query is keyed on `clinic_id` (Invariants #1)."""
    _, appointments = tables(FakeClinicsTable(dental_clinic(), cosmetic_clinic()))
    scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")

    expression = appointments.queries[0]["KeyConditionExpression"].get_expression()
    equals = next(
        sub
        for sub in expression["values"]
        if sub.get_expression()["operator"] == "="
    ).get_expression()
    assert equals["values"][1] == DENTAL_ID
    assert appointments.queries[0]["IndexName"] == "by-start-time"


def test_appointments_are_queried_over_the_clinics_local_day(tables) -> None:
    """The window is local midnight to local midnight, expressed in UTC.

    In BST that is 23:00Z the previous day -- if the window were built in
    UTC instead, the last hour of the clinic's day would be invisible.
    """
    _, appointments = tables(FakeClinicsTable(dental_clinic()))
    scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")

    expression = appointments.queries[0]["KeyConditionExpression"].get_expression()
    between = next(
        sub
        for sub in expression["values"]
        if sub.get_expression()["operator"] == "BETWEEN"
    ).get_expression()
    assert between["values"][1] == "2026-06-30T23:00:00Z"
    assert between["values"][2] == "2026-07-01T23:00:00Z"


# --------------------------------------------------------------------------
# Hours, closures, and the slot grid
# --------------------------------------------------------------------------


def test_slots_follow_the_grid_and_stop_before_the_lunch_break(tables) -> None:
    tables(FakeClinicsTable(dental_clinic()))
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")

    starts = local_starts(result)
    assert result["is_open"] is True
    assert result["closure_label"] is None
    # 09:00-13:00 on a 15-minute grid, last 15-minute start at 12:45...
    assert starts[:3] == ["09:00", "09:15", "09:30"]
    assert "12:45" in starts
    assert "13:00" not in starts
    # ...then the afternoon interval starts fresh at 14:00 and ends 17:15.
    assert "14:00" in starts
    assert starts[-1] == "17:15"
    assert "13:15" not in starts


def test_duration_must_fit_inside_one_interval(tables) -> None:
    """A 30-minute cleaning is not offered at 12:45 against a 13:00 close."""
    tables(FakeClinicsTable(dental_clinic()))
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "cleaning")

    starts = local_starts(result)
    assert "12:30" in starts
    assert "12:45" not in starts
    assert starts[-1] == "17:00"


def test_duration_need_not_be_a_multiple_of_slot_minutes(tables) -> None:
    """A 90-minute treatment still starts on the clinic's 30-minute grid."""
    tables(FakeClinicsTable(cosmetic_clinic()))
    result = scheduling.check_availability(COSMETIC_ID, WEDNESDAY, "treatment")

    starts = local_starts(result)
    assert starts[:3] == ["10:00", "10:30", "11:00"]
    assert starts[-1] == "16:30"
    assert result["slots"][0]["local_end"] == "11:30"


def test_the_two_demo_clinics_answer_the_same_question_differently(tables) -> None:
    """`project-overview.md` Goal 2, as a property of the data alone."""
    tables(FakeClinicsTable(dental_clinic(), cosmetic_clinic()))
    dental = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")
    cosmetic = scheduling.check_availability(COSMETIC_ID, WEDNESDAY, "consult")

    assert local_starts(dental)[0] == "09:00"
    assert local_starts(cosmetic)[0] == "10:00"
    assert dental["service"]["duration_minutes"] == 15
    assert cosmetic["service"]["duration_minutes"] == 60


def test_a_weekday_the_clinic_does_not_open_is_closed_without_a_label(tables) -> None:
    _, appointments = tables(FakeClinicsTable(dental_clinic()))
    result = scheduling.check_availability(DENTAL_ID, SUNDAY, "checkup")

    assert result["is_open"] is False
    assert result["closure_label"] is None
    assert result["slots"] == []
    # A closed day costs no appointments read at all.
    assert appointments.queries == []


def test_saturday_uses_its_own_shorter_hours(tables) -> None:
    tables(FakeClinicsTable(dental_clinic()))
    result = scheduling.check_availability(DENTAL_ID, SATURDAY, "checkup")

    assert local_starts(result)[0] == "09:00"
    assert local_starts(result)[-1] == "11:45"


def test_a_whole_day_closure_removes_the_day_and_reports_its_label(tables) -> None:
    _, appointments = tables(FakeClinicsTable(dental_clinic()))
    # 2026-07-08 is a Wednesday the clinic would otherwise be open.
    result = scheduling.check_availability(DENTAL_ID, "2026-07-08", "checkup")

    assert result["is_open"] is False
    assert result["closure_label"] == "Staff training day"
    assert result["slots"] == []
    assert appointments.queries == []


# --------------------------------------------------------------------------
# Local time vs stored UTC
# --------------------------------------------------------------------------


def test_local_hours_convert_to_utc_across_a_dst_change(tables) -> None:
    """Same clinic, same 09:00 opening: 08:00Z in summer, 09:00Z in winter.

    This is the failure the whole local/UTC split exists to prevent -- a
    stored-UTC `hours` value would be an hour wrong for half the year.
    """
    tables(FakeClinicsTable(dental_clinic()))
    summer = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")
    winter = scheduling.check_availability(DENTAL_ID, WINTER_WEDNESDAY, "checkup")

    assert summer["slots"][0]["starts_at"] == "2026-07-01T08:00:00Z"
    assert summer["slots"][0]["local_start"] == "09:00"
    assert winter["slots"][0]["starts_at"] == "2026-01-07T09:00:00Z"
    assert winter["slots"][0]["local_start"] == "09:00"


def test_slot_timestamps_use_the_projects_single_encoding(tables) -> None:
    tables(FakeClinicsTable(dental_clinic()))
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")

    for slot in result["slots"]:
        for field in ("starts_at", "ends_at"):
            # Parses under the one stored format, `Z`-suffixed and
            # second-precision, so it is comparable with a sort key.
            datetime.strptime(slot[field], "%Y-%m-%dT%H:%M:%SZ")
    assert result["timezone"] == "Europe/London"
    assert result["date"] == WEDNESDAY


def test_date_accepts_a_full_timestamp_from_a_model(tables) -> None:
    tables(FakeClinicsTable(dental_clinic()))
    result = scheduling.check_availability(
        DENTAL_ID, "2026-07-01T00:00:00Z", "checkup"
    )
    assert result["date"] == WEDNESDAY


def test_unparseable_date_is_a_validation_error(tables) -> None:
    tables(FakeClinicsTable(dental_clinic()))
    with pytest.raises(ValidationError):
        scheduling.check_availability(DENTAL_ID, "next Tuesday", "checkup")


# --------------------------------------------------------------------------
# Existing appointments
# --------------------------------------------------------------------------


def test_a_booked_appointment_removes_only_the_slots_it_overlaps(tables) -> None:
    tables(
        FakeClinicsTable(dental_clinic()),
        FakeAppointmentsTable(
            [appointment("2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z")]
        ),
    )
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")

    starts = local_starts(result)
    # 09:00Z-09:30Z is 10:00-10:30 local.
    assert "10:00" not in starts
    assert "10:15" not in starts
    # Half-open: a slot starting exactly at the appointment's end is free.
    assert "10:30" in starts
    assert "09:45" in starts


def test_a_longer_service_is_blocked_by_a_nearby_appointment(tables) -> None:
    """A 30-minute cleaning cannot start 15 minutes before a booked slot."""
    tables(
        FakeClinicsTable(dental_clinic()),
        FakeAppointmentsTable(
            [appointment("2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z")]
        ),
    )
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "cleaning")

    starts = local_starts(result)
    assert "09:45" not in starts  # 09:45-10:15 local overlaps 10:00-10:30
    assert "09:30" in starts  # 09:30-10:00 local ends as it begins
    assert "10:30" in starts


@pytest.mark.parametrize(
    "status",
    [
        AppointmentStatus.CANCELLED.value,
        AppointmentStatus.COMPLETED.value,
        AppointmentStatus.NO_SHOW.value,
    ],
)
def test_inactive_appointments_free_their_slot(status, tables) -> None:
    tables(
        FakeClinicsTable(dental_clinic()),
        FakeAppointmentsTable(
            [appointment("2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z", status)]
        ),
    )
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")
    assert "10:00" in local_starts(result)


def test_an_unrecognised_status_still_blocks_its_slot(tables) -> None:
    """Offering a taken slot is the worse of the two possible mistakes."""
    tables(
        FakeClinicsTable(dental_clinic()),
        FakeAppointmentsTable(
            [appointment("2026-07-01T09:00:00Z", "2026-07-01T09:30:00Z", "pending")]
        ),
    )
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")
    assert "10:00" not in local_starts(result)


def test_an_appointment_without_ends_at_blocks_the_slot_containing_it(tables) -> None:
    tables(
        FakeClinicsTable(dental_clinic()),
        FakeAppointmentsTable([appointment("2026-07-01T09:05:00Z", None)]),
    )
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")

    starts = local_starts(result)
    assert "10:00" not in starts  # 10:00-10:15 local contains 10:05
    assert "10:15" in starts


def test_all_pages_of_appointments_are_read(tables) -> None:
    """A paginated query must not silently drop the appointments it missed."""
    tables(
        FakeClinicsTable(dental_clinic()),
        FakeAppointmentsTable(
            [appointment("2026-07-01T09:00:00Z", "2026-07-01T09:15:00Z")],
            [appointment("2026-07-01T14:00:00Z", "2026-07-01T14:15:00Z")],
        ),
    )
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")

    starts = local_starts(result)
    assert "10:00" not in starts
    assert "15:00" not in starts  # only visible if page two was read


def test_a_fully_booked_open_day_is_not_the_same_as_a_closed_one(tables) -> None:
    tables(
        FakeClinicsTable(cosmetic_clinic()),
        FakeAppointmentsTable(
            [appointment("2026-07-01T09:00:00Z", "2026-07-01T17:00:00Z")]
        ),
    )
    result = scheduling.check_availability(COSMETIC_ID, WEDNESDAY, "consult")

    assert result["slots"] == []
    assert result["is_open"] is True
    assert result["closure_label"] is None


# --------------------------------------------------------------------------
# Service resolution
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "requested", ["cleaning", "Cleaning", "Dental cleaning", "  dental CLEANING  "]
)
def test_service_resolves_by_id_or_name_case_insensitively(requested, tables) -> None:
    tables(FakeClinicsTable(dental_clinic()))
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, requested)

    assert result["service"] == {
        "id": "cleaning",
        "name": "Dental cleaning",
        "duration_minutes": 30,
    }


def test_an_id_is_never_shadowed_by_another_entrys_name(tables) -> None:
    """Ids are matched first, so an ambiguous word resolves to the id."""
    clinic = dental_clinic()
    clinic["services"] = [
        {"id": "consult", "name": "Long consult", "duration_minutes": Decimal("60")},
        {"id": "long", "name": "Consult", "duration_minutes": Decimal("15")},
    ]
    tables(FakeClinicsTable(clinic))
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "consult")
    assert result["service"]["id"] == "consult"


def test_an_unknown_service_is_rejected_and_the_real_ones_listed(tables) -> None:
    tables(FakeClinicsTable(dental_clinic()))
    with pytest.raises(ValidationError) as caught:
        scheduling.check_availability(DENTAL_ID, WEDNESDAY, "botox")

    assert "Dental cleaning" in str(caught.value)


@pytest.mark.parametrize("service", ["", "   ", None])
def test_a_missing_service_is_rejected(service, tables) -> None:
    tables(FakeClinicsTable(dental_clinic()))
    with pytest.raises(ValidationError):
        scheduling.check_availability(DENTAL_ID, WEDNESDAY, service)


def test_decimal_durations_are_coerced_to_int(tables) -> None:
    """`timedelta(minutes=Decimal(...))` raises, so this is not cosmetic."""
    tables(FakeClinicsTable(dental_clinic()))
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")
    assert isinstance(result["service"]["duration_minutes"], int)


# --------------------------------------------------------------------------
# Malformed clinic config is a deployment fault, not a patient-request one
# --------------------------------------------------------------------------


def test_a_missing_timezone_is_a_configuration_error(tables) -> None:
    clinic = dental_clinic()
    del clinic["timezone"]
    tables(FakeClinicsTable(clinic))
    with pytest.raises(ConfigurationError):
        scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")


def test_an_unknown_timezone_is_a_configuration_error(tables) -> None:
    clinic = dental_clinic()
    clinic["timezone"] = "Mars/Olympus_Mons"
    tables(FakeClinicsTable(clinic))
    with pytest.raises(ConfigurationError):
        scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")


@pytest.mark.parametrize(
    "day",
    [
        [{"open": "09:00", "close": "09:00"}],  # close not after open
        [{"open": "17:00", "close": "13:00"}],  # inverted
        [{"open": "09:00", "close": "13:00"}, {"open": "12:00", "close": "17:00"}],
        [{"open": "9am", "close": "1pm"}],  # not HH:MM
        [{"open": "09:00"}],  # missing close
        ["09:00-13:00"],  # not an interval object
    ],
)
def test_malformed_hours_fail_loudly(day, tables) -> None:
    """Silently wrong slots would be far worse than a loud config failure."""
    clinic = dental_clinic()
    clinic["hours"]["wed"] = day
    tables(FakeClinicsTable(clinic))
    with pytest.raises(ConfigurationError):
        scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")


@pytest.mark.parametrize("slot_minutes", [Decimal("0"), Decimal("-15"), "many", None])
def test_a_non_positive_slot_minutes_is_a_configuration_error(
    slot_minutes, tables
) -> None:
    clinic = dental_clinic()
    clinic["slot_minutes"] = slot_minutes
    tables(FakeClinicsTable(clinic))
    with pytest.raises(ConfigurationError):
        scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")


def test_a_clinic_with_no_services_is_a_configuration_error(tables) -> None:
    clinic = dental_clinic()
    clinic["services"] = []
    tables(FakeClinicsTable(clinic))
    with pytest.raises(ConfigurationError):
        scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")


def test_a_bad_closure_entry_does_not_take_the_calendar_offline(tables) -> None:
    clinic = dental_clinic()
    clinic["closures"] = ["2026-07-01", {"label": "no date"}, {"date": "not-a-date"}]
    tables(FakeClinicsTable(clinic))
    result = scheduling.check_availability(DENTAL_ID, WEDNESDAY, "checkup")
    assert result["is_open"] is True
    assert result["slots"]


# --------------------------------------------------------------------------
# The overlap rule itself
# --------------------------------------------------------------------------


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 1, hour, minute, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("booked_start", "booked_end", "expected"),
    [
        ((9, 0), (10, 0), True),  # identical
        ((9, 30), (10, 30), True),  # overlaps the tail
        ((8, 30), (9, 30), True),  # overlaps the head
        ((9, 15), (9, 45), True),  # contained
        ((8, 0), (11, 0), True),  # contains
        ((10, 0), (11, 0), False),  # abuts after
        ((8, 0), (9, 0), False),  # abuts before
        ((9, 0), (9, 0), True),  # degenerate, inside the slot
        ((10, 0), (10, 0), False),  # degenerate, at the exclusive end
    ],
)
def test_overlap_is_half_open(booked_start, booked_end, expected) -> None:
    assert (
        scheduling._overlaps(
            utc(9), utc(10), utc(*booked_start), utc(*booked_end)
        )
        is expected
    )
