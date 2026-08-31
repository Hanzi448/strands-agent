"""Sample patients and appointments for the two demo clinics.

Specs only -- no DynamoDB write lives here. `run_seed.py` turns each spec
into a real booking through `tools.scheduling.check_availability` and
`tools.booking.book_appointment`, the same two calls a voice caller's
booking makes, rather than composing an `Appointments` item by hand. That
is what keeps a seeded appointment indistinguishable from one the agent
would have produced (`architecture.md` -> Invariants #3's spirit).

Each spec names a `days_ahead`/`slot_index` pair instead of a fixed date,
because "the third offerable slot starting two days from now" stays valid
no matter when the seed script actually runs; a fixed `starts_at` would go
stale (or fall on a closure) the day after it was written.

One phone number per clinic is deliberately written in *national* form
(no leading `+`) to exercise `country_code` reconciliation
(`architecture.md` -> Storage Model) end to end against a real table --
`find_patients_by_phone` must resolve it to the same patient as anyone who
later calls back and says it with a "+44".

Those two entries omit the UK national trunk "0" a caller would normally
lead with (`"7700 900002"`, not `"07700 900002"`): `validation.normalise_phone`
only *prepends* `country_code` when no international marker is present --
it does not know to drop a national trunk prefix first, so a real
`"0…"` number would prepend to a different digit string than its `"+44…"`
form produces and the two would **not** reconcile. That gap is real (most
national dialling plans outside the US use a trunk prefix like this one)
and is out of scope for a seed script to fix; this sidesteps it rather
than seeding a "reconciliation" demo that would silently fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .clinic_data import COSMETIC_CLINIC_ID, DENTAL_CLINIC_ID


@dataclass(frozen=True)
class SampleAppointment:
    """One appointment to book during seeding.

    Attributes:
        service_id: A service id from the owning clinic's `services` list.
        patient_name: As "spoken" -- exercises `patients._name_key`
            exactly as a real call would.
        patient_phone: As "spoken" -- national form on some entries (see
            module docstring), international on others.
        patient_email: Optional; when set, seeds a reachable reminder
            address (`tools.automation` needs one to send to).
        notes: Optional free text, exercising the same field a patient's
            own call would fill in.
        days_ahead: The first local date `check_availability` is asked
            about, as an offset from "today" at seed time.
        slot_index: Which offerable slot in the returned window to book --
            spread across a few values so sample appointments land on
            different days and times rather than all on the first slot
            available.
    """

    service_id: str
    patient_name: str
    patient_phone: str
    patient_email: str | None
    notes: str | None
    days_ahead: int
    slot_index: int


# How many consecutive days `check_availability` is asked to search from
# `days_ahead` -- generous enough that a short week (the dental clinic is
# shut Sunday, the cosmetic one Sunday and Monday) still has room for
# `slot_index` to land inside the window.
LOOKAHEAD_DAYS: Final[int] = 7

DENTAL_APPOINTMENTS: Final[tuple[SampleAppointment, ...]] = (
    SampleAppointment(
        service_id="checkup",
        patient_name="Priya Sharma",
        patient_phone="+44 7700 900001",
        patient_email="priya.sharma@example.com",
        notes=None,
        days_ahead=1,
        slot_index=0,
    ),
    SampleAppointment(
        service_id="cleaning",
        patient_name="Tom Fletcher",
        # National form, on purpose -- see module docstring. No leading
        # trunk "0" -- see module docstring on why one would not reconcile.
        patient_phone="7700 900002",
        patient_email="tom.fletcher@example.com",
        notes="First cleaning in over a year.",
        days_ahead=2,
        slot_index=1,
    ),
    SampleAppointment(
        service_id="checkup",
        patient_name="Amara Okoye",
        patient_phone="+44 7700 900003",
        patient_email=None,
        notes=None,
        days_ahead=4,
        slot_index=0,
    ),
)

COSMETIC_APPOINTMENTS: Final[tuple[SampleAppointment, ...]] = (
    SampleAppointment(
        service_id="consult",
        patient_name="Jasmine Lee",
        patient_phone="+44 7700 900011",
        patient_email="jasmine.lee@example.com",
        notes="Interested in a first consultation.",
        days_ahead=1,
        slot_index=0,
    ),
    SampleAppointment(
        service_id="treatment",
        patient_name="Oliver Bennett",
        # National form, on purpose -- see module docstring. No leading
        # trunk "0" -- see module docstring on why one would not reconcile.
        patient_phone="7700 900012",
        patient_email="oliver.bennett@example.com",
        notes=None,
        days_ahead=3,
        slot_index=0,
    ),
    SampleAppointment(
        service_id="consult",
        patient_name="Fatima Rahman",
        patient_phone="+44 7700 900013",
        patient_email=None,
        notes=None,
        days_ahead=5,
        slot_index=1,
    ),
)

# What `run_seed.py` iterates over: one clinic id paired with its own
# appointment specs.
SAMPLE_APPOINTMENTS_BY_CLINIC: Final[dict[str, tuple[SampleAppointment, ...]]] = {
    DENTAL_CLINIC_ID: DENTAL_APPOINTMENTS,
    COSMETIC_CLINIC_ID: COSMETIC_APPOINTMENTS,
}
