"""Tests for `book_appointment`, the first write in the tool layer.

Two properties carry most of the weight here. The first is that booking
does not have its own opinion about availability: every "can this be
booked?" case is asserted against the same clinic configs
`test_scheduling.py` uses, so a rule that drifted between the read and the
write would show up as a disagreement between these two files. The second
is that a refused booking leaves *nothing* behind -- no patient row, no
appointment -- because a voice caller retries, and a half-written first
attempt is what turns one retry into two records.

The clinic fixtures are the demo configs from `architecture.md` -> Storage
Model, imported from `test_scheduling` rather than restated, so the two
suites cannot drift apart.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.test_scheduling import (
    DENTAL_ID,
    FakeAppointmentsTable,
    FakeClinicsTable,
    appointment,
    cosmetic_clinic,
    dental_clinic,
)
from tools import booking, patients, scheduling
from tools.errors import ConflictError, ConfigurationError, NotFoundError, ValidationError

# 2026-07-01 is a Wednesday in British Summer Time, so the dental clinic's
# 09:00 local is 08:00Z -- the offset is visible in every assertion below
# rather than accidentally an identity.
NINE_AM = "2026-07-01T08:00:00Z"
NINE_THIRTY = "2026-07-01T08:30:00Z"
# 2026-07-05 is a Sunday (the dental clinic never opens); 2026-07-08 is its
# seeded staff-training closure.
SUNDAY_NINE = "2026-07-05T08:00:00Z"
CLOSURE_NINE = "2026-07-08T08:00:00Z"

# The stored form: digits only, as `normalise_phone` writes it.
PHONE = "15551234567"
NAME = "Dana Okafor"


class FakePatientsTable:
    """Enough of the `Patients` table for booking: by-phone query plus writes."""

    def __init__(self, *items: dict[str, Any]) -> None:
        self.items = [dict(item) for item in items]
        self.puts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    def query(self, **kwargs: Any) -> dict[str, Any]:
        expression = kwargs["KeyConditionExpression"].get_expression()
        clinic_id, phone = (
            sub.get_expression()["values"][1] for sub in expression["values"]
        )
        return {
            "Items": [
                item
                for item in self.items
                if item.get("clinic_id") == clinic_id and item.get("phone") == phone
            ]
        }

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        self.items.append(dict(kwargs["Item"]))
        return {}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        return {}


class WritableAppointmentsTable(FakeAppointmentsTable):
    """The scheduling suite's query fake, plus the `put_item` booking needs."""

    def __init__(self, *pages: list[dict[str, Any]]) -> None:
        super().__init__(*pages)
        self.puts: list[dict[str, Any]] = []

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        return {}


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch):
    """Point every table accessor the booking path touches at a fake.

    `scheduling` and `patients` are patched as well as `booking`, because
    the write reaches DynamoDB through all three modules -- which is itself
    the point: booking owns no query of its own.
    """

    def install(
        clinics: FakeClinicsTable | None = None,
        appointments: WritableAppointmentsTable | None = None,
        patients_table: FakePatientsTable | None = None,
    ) -> tuple[FakeClinicsTable, WritableAppointmentsTable, FakePatientsTable]:
        clinics = clinics or FakeClinicsTable(dental_clinic(), cosmetic_clinic())
        appointments = appointments or WritableAppointmentsTable()
        patients_fake = patients_table or FakePatientsTable()
        monkeypatch.setattr(scheduling, "clinics_table", lambda: clinics)
        monkeypatch.setattr(scheduling, "appointments_table", lambda: appointments)
        monkeypatch.setattr(booking, "appointments_table", lambda: appointments)
        monkeypatch.setattr(patients, "patients_table", lambda: patients_fake)
        return clinics, appointments, patients_fake

    return install


def book(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "clinic_id": DENTAL_ID,
        "starts_at": NINE_AM,
        "service": "checkup",
        "patient_name": NAME,
        "patient_phone": PHONE,
    }
    kwargs.update(overrides)
    return booking.book_appointment(**kwargs)


# --------------------------------------------------------------------------
# The tenant boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clinic_id", ["", "   ", None])
def test_blank_clinic_id_fails_before_any_read_or_write(clinic_id, tables) -> None:
    """`code-standards.md`: the tenant check runs *before anything else*."""
    clinics, appointments, patients_fake = tables()
    with pytest.raises(ValidationError):
        book(clinic_id=clinic_id)
    assert clinics.requested == []
    assert appointments.queries == []
    assert appointments.puts == []
    assert patients_fake.puts == []


def test_unknown_clinic_raises_not_found(tables) -> None:
    _, appointments, patients_fake = tables()
    with pytest.raises(NotFoundError):
        book(clinic_id="clinic-nope")
    assert appointments.puts == []
    assert patients_fake.puts == []


def test_the_written_item_is_scoped_to_the_booking_clinic(tables) -> None:
    _, appointments, _ = tables()
    result = book()
    item = appointments.puts[0]["Item"]
    assert item["clinic_id"] == DENTAL_ID
    assert result["clinic_id"] == DENTAL_ID
    # The composite index key is built by the tool layer, never supplied,
    # so `by-patient` is clinic-scoped by construction (Invariants #1).
    assert item["clinic_patient"] == f"{DENTAL_ID}#{item['patient_id']}"


def test_a_patient_at_another_clinic_is_not_reused(tables) -> None:
    """The same person at two clinics is two records, by design."""
    _, _, patients_fake = tables(
        patients_table=FakePatientsTable(
            {
                "clinic_id": "clinic-cosmetic",
                "patient_id": "pat_elsewhere",
                "name": NAME,
                "phone": PHONE,
            }
        )
    )
    result = book()
    assert result["patient"]["is_new"] is True
    assert result["patient"]["patient_id"] != "pat_elsewhere"
    assert patients_fake.puts[0]["Item"]["clinic_id"] == DENTAL_ID


# --------------------------------------------------------------------------
# Availability is re-checked, not restated
# --------------------------------------------------------------------------


def test_an_offerable_slot_is_written(tables) -> None:
    _, appointments, _ = tables()
    result = book()
    assert len(appointments.puts) == 1
    item = appointments.puts[0]["Item"]
    assert item["starts_at"] == NINE_AM
    # 09:00 + a 15-minute check-up, taken from the matched slot rather
    # than recomputed here.
    assert item["ends_at"] == "2026-07-01T08:15:00Z"
    assert result["local_start"] == "09:00"
    assert result["local_end"] == "09:15"
    assert result["date"] == "2026-07-01"


def test_a_slot_taken_since_the_quote_is_refused(tables) -> None:
    """The gap the re-check exists to close: a conversation turn wide."""
    _, appointments, patients_fake = tables(
        appointments=WritableAppointmentsTable(
            [appointment(NINE_AM, "2026-07-01T08:15:00Z")]
        )
    )
    with pytest.raises(ConflictError):
        book()
    assert appointments.puts == []
    assert patients_fake.puts == []


def test_a_start_off_the_clinics_slot_grid_is_refused(tables) -> None:
    """09:07 is not on the dental clinic's 15-minute grid."""
    _, appointments, _ = tables()
    with pytest.raises(ConflictError):
        book(starts_at="2026-07-01T08:07:00Z")
    assert appointments.puts == []


def test_a_service_that_would_not_fit_is_refused(tables) -> None:
    """A 30-minute cleaning at 12:45 runs into the 13:00 lunch break.

    The same case `test_scheduling.py` asserts for the read: if this ever
    passed, the write would have grown its own opinion of the rule.
    """
    _, appointments, _ = tables()
    with pytest.raises(ConflictError):
        book(starts_at="2026-07-01T11:45:00Z", service="cleaning")
    assert appointments.puts == []
    # ...and the 12:30 start, which does fit, is bookable.
    assert book(starts_at="2026-07-01T11:30:00Z", service="cleaning")


def test_a_weekday_the_clinic_never_opens_is_refused(tables) -> None:
    _, appointments, _ = tables()
    with pytest.raises(ConflictError):
        book(starts_at=SUNDAY_NINE)
    assert appointments.puts == []
    # A closed day cannot depend on what is booked, so nothing is queried.
    assert appointments.queries == []


def test_a_whole_day_closure_is_refused(tables) -> None:
    _, appointments, _ = tables()
    with pytest.raises(ConflictError):
        book(starts_at=CLOSURE_NINE)
    assert appointments.puts == []


def test_the_refusal_names_times_that_are_still_free(tables) -> None:
    """A voice agent told only "no" has to make another round trip."""
    tables(
        appointments=WritableAppointmentsTable(
            [appointment(NINE_AM, "2026-07-01T08:15:00Z")]
        )
    )
    with pytest.raises(ConflictError) as raised:
        book()
    message = str(raised.value)
    assert "09:00 on 2026-07-01" in message
    assert "09:15" in message
    assert "Bright Smile Dental" in message


def test_the_refusal_says_so_when_the_whole_day_is_unavailable(tables) -> None:
    tables()
    with pytest.raises(ConflictError) as raised:
        book(starts_at=SUNDAY_NINE)
    assert "nothing else free that day" in str(raised.value)


def test_the_other_clinics_rules_apply_to_the_other_clinic(tables) -> None:
    """The cosmetic clinic's 30-minute grid, unbroken hours, 60-minute consult."""
    _, appointments, _ = tables()
    result = booking.book_appointment(
        clinic_id="clinic-cosmetic",
        starts_at="2026-07-01T09:00:00Z",  # 10:00 local, its opening time
        service="consult",
        patient_name=NAME,
        patient_phone=PHONE,
    )
    assert result["local_start"] == "10:00"
    assert result["local_end"] == "11:00"
    # 09:00 local is inside the dental clinic's hours and outside this one's.
    with pytest.raises(ConflictError):
        booking.book_appointment(
            clinic_id="clinic-cosmetic",
            starts_at=NINE_AM,
            service="consult",
            patient_name=NAME,
            patient_phone=PHONE,
        )


def test_the_day_checked_is_the_clinics_local_day(tables) -> None:
    """23:30Z on 2026-06-30 is 00:30 on the 1st in London, not the 30th."""
    _, appointments, _ = tables()
    with pytest.raises(ConflictError) as raised:
        book(starts_at="2026-06-30T23:30:00Z")
    assert "2026-07-01" in str(raised.value)


# --------------------------------------------------------------------------
# Argument validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("starts_at", ["", "   ", None, "tomorrow at nine", "09:00"])
def test_malformed_start_times_are_refused(starts_at, tables) -> None:
    clinics, appointments, _ = tables()
    with pytest.raises(ValidationError):
        book(starts_at=starts_at)
    assert clinics.requested == []
    assert appointments.puts == []


def test_a_start_time_with_an_offset_is_accepted_and_normalised(tables) -> None:
    """09:00+01:00 is the same instant as 08:00Z, and must book the same slot."""
    _, appointments, _ = tables()
    result = book(starts_at="2026-07-01T09:00:00+01:00")
    assert result["starts_at"] == NINE_AM
    assert appointments.puts[0]["Item"]["starts_at"] == NINE_AM


def test_a_service_the_clinic_does_not_offer_is_refused(tables) -> None:
    _, appointments, patients_fake = tables()
    with pytest.raises(ValidationError) as raised:
        book(service="botox")
    # The message lists what the clinic does offer, since the caller guessed.
    assert "Dental cleaning" in str(raised.value)
    assert appointments.puts == []
    assert patients_fake.puts == []


@pytest.mark.parametrize("name", ["", "   ", None, "x" * 129])
def test_missing_or_oversized_patient_names_are_refused(name, tables) -> None:
    clinics, appointments, _ = tables()
    with pytest.raises(ValidationError):
        book(patient_name=name)
    assert clinics.requested == []
    assert appointments.puts == []


@pytest.mark.parametrize("phone", ["", "   ", None, "12345", "not a number"])
def test_implausible_patient_phones_are_refused(phone, tables) -> None:
    clinics, appointments, _ = tables()
    with pytest.raises(ValidationError):
        book(patient_phone=phone)
    assert clinics.requested == []
    assert appointments.puts == []


def test_a_malformed_email_is_refused(tables) -> None:
    _, appointments, _ = tables()
    with pytest.raises(ValidationError):
        book(patient_email="dana at example.com")
    assert appointments.puts == []


def test_oversized_notes_are_refused(tables) -> None:
    """A model pasting a transcript into `notes` must not reach the table."""
    _, appointments, _ = tables()
    with pytest.raises(ValidationError):
        book(notes="x" * 2001)
    assert appointments.puts == []


def test_a_broken_clinic_config_fails_loudly(tables) -> None:
    """A seeding fault, not a patient-request fault -- never a ConflictError."""
    broken = dental_clinic()
    broken["slot_minutes"] = "quarter hour"
    _, appointments, _ = tables(clinics=FakeClinicsTable(broken))
    with pytest.raises(ConfigurationError):
        book()
    assert appointments.puts == []


# --------------------------------------------------------------------------
# The patient behind the booking
# --------------------------------------------------------------------------


def test_a_first_time_caller_is_registered(tables) -> None:
    _, appointments, patients_fake = tables()
    result = book(patient_email="dana@example.com")
    assert result["patient"]["is_new"] is True
    patient_item = patients_fake.puts[0]["Item"]
    assert patient_item["name"] == NAME
    assert patient_item["phone"] == PHONE
    assert patient_item["email"] == "dana@example.com"
    assert appointments.puts[0]["Item"]["patient_id"] == patient_item["patient_id"]


def test_a_returning_caller_is_reused(tables) -> None:
    _, appointments, patients_fake = tables(
        patients_table=FakePatientsTable(
            {
                "clinic_id": DENTAL_ID,
                "patient_id": "pat_dana",
                "name": NAME,
                "phone": PHONE,
                "created_at": "2026-01-01T00:00:00Z",
            }
        )
    )
    result = book()
    assert result["patient"]["is_new"] is False
    assert result["patient"]["patient_id"] == "pat_dana"
    assert patients_fake.puts == []
    assert appointments.puts[0]["Item"]["patient_id"] == "pat_dana"


def test_the_appointment_carries_the_stored_name_not_the_spoken_one(tables) -> None:
    """A returning caller heard as "dana okafor" must not restyle the day view."""
    _, appointments, _ = tables(
        patients_table=FakePatientsTable(
            {
                "clinic_id": DENTAL_ID,
                "patient_id": "pat_dana",
                "name": NAME,
                "phone": PHONE,
                "created_at": "2026-01-01T00:00:00Z",
            }
        )
    )
    book(patient_name="dana okafor")
    assert appointments.puts[0]["Item"]["patient_name"] == NAME


def test_no_patient_is_created_when_the_booking_is_refused(tables) -> None:
    """A caller retries; a half-written first attempt is a duplicate record."""
    _, appointments, patients_fake = tables(
        appointments=WritableAppointmentsTable(
            [appointment(NINE_AM, "2026-07-01T08:15:00Z")]
        )
    )
    with pytest.raises(ConflictError):
        book()
    assert patients_fake.puts == []
    assert patients_fake.items == []
    assert appointments.puts == []


# --------------------------------------------------------------------------
# The stored item and the returned result
# --------------------------------------------------------------------------


def test_the_stored_appointment_item_shape(tables) -> None:
    _, appointments, _ = tables()
    result = book(notes="  Nervous about the drill  ")
    item = appointments.puts[0]["Item"]
    assert item["appointment_id"].startswith("apt_")
    assert item["status"] == "scheduled"
    # The service *id*, never the spoken name.
    assert item["service"] == "checkup"
    assert item["notes"] == "Nervous about the drill"
    # Present and empty, so the reminder job and the reschedule tool append
    # rather than branching on a missing attribute.
    assert item["reminders"] == []
    assert item["reschedule_history"] == []
    assert item["created_at"] == item["updated_at"]
    assert item["created_at"].endswith("Z")
    assert result["appointment_id"] == item["appointment_id"]


def test_the_service_name_resolves_to_its_id(tables) -> None:
    """A model hands back what it heard: "Dental cleaning", not "cleaning"."""
    _, appointments, _ = tables()
    result = book(starts_at="2026-07-01T11:30:00Z", service="Dental cleaning")
    assert appointments.puts[0]["Item"]["service"] == "cleaning"
    assert result["service"]["name"] == "Dental cleaning"
    assert result["service"]["duration_minutes"] == 30


def test_notes_are_omitted_rather_than_stored_null(tables) -> None:
    _, appointments, _ = tables()
    result = book()
    assert "notes" not in appointments.puts[0]["Item"]
    assert result["notes"] is None


def test_the_write_is_conditional_on_the_id_being_free(tables) -> None:
    _, appointments, _ = tables()
    book()
    assert "ConditionExpression" in appointments.puts[0]


def test_two_bookings_get_distinct_ids(tables) -> None:
    _, appointments, _ = tables()
    first = book()
    second = book(starts_at=NINE_THIRTY)
    assert first["appointment_id"] != second["appointment_id"]


def test_the_result_carries_both_utc_and_local_times(tables) -> None:
    """The model must say "nine o'clock" and must not do the arithmetic."""
    tables()
    result = book()
    assert result["starts_at"] == NINE_AM
    assert result["ends_at"] == "2026-07-01T08:15:00Z"
    assert (result["local_start"], result["local_end"]) == ("09:00", "09:15")
    assert result["status"] == "scheduled"
    assert set(result["patient"]) == {"patient_id", "name", "phone", "is_new"}
