"""Canonical item schema for the four DynamoDB tables.

`architecture.md` -> Storage Model fixes the *keys* in
`backend/infra/data_stack.py` and explicitly defers everything else to
this layer: "Non-key attribute names and the appointment/escalation
status vocabularies are fixed when `backend/tools/` is implemented".
This module is that definition. Tools, Lambda handlers, and the seed
scripts spell attribute names by importing from here -- never as inline
string literals, because a misspelled attribute name in DynamoDB is a
silently absent field rather than an error.

The value *shapes* of the nested clinic fields (`hours`, `closures`,
`services`) are specified in `architecture.md` -> Storage Model ("Clinic
availability config"), not here. This module fixes names, vocabularies,
and the key/timestamp encodings the tables' sort keys depend on -- now
including the key names *inside* those nested values (`HoursInterval`,
`ClosureAttrs`, `ServiceAttrs`, `WEEKDAY_KEYS`), landed by
`tools.scheduling.check_availability`, the first tool that reads them, and
the appointment history entry shapes (`RescheduleEntry`, `ReminderEntry`,
`RescheduleActor`), landed by `tools.appointments.reschedule_appointment`,
the first tool that writes one.

The key attribute and index names below must match
`backend/infra/data_stack.py` exactly;
`backend/tests/test_schema_matches_infra.py` asserts that they do, so the
duplication cannot drift unnoticed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Final

from .errors import ValidationError

# --------------------------------------------------------------------------
# Shared key attributes
# --------------------------------------------------------------------------

# Present on every item in every table: the tenant boundary itself
# (`architecture.md` -> Invariants #1).
CLINIC_ID: Final[str] = "clinic_id"
PATIENT_ID: Final[str] = "patient_id"
APPOINTMENT_ID: Final[str] = "appointment_id"
ESCALATION_ID: Final[str] = "escalation_id"
STARTS_AT: Final[str] = "starts_at"
CREATED_AT: Final[str] = "created_at"
PHONE: Final[str] = "phone"
# Composite `{clinic_id}#{patient_id}`, built by `clinic_patient_key`.
CLINIC_PATIENT: Final[str] = "clinic_patient"

# Separator for the composite index key. A generated id never contains it
# (see `new_id`), and `clinic_patient_key` rejects operands that do rather
# than producing an ambiguous key.
KEY_SEPARATOR: Final[str] = "#"

# --------------------------------------------------------------------------
# Index names (must match `backend/infra/data_stack.py`)
# --------------------------------------------------------------------------

APPOINTMENTS_BY_START_TIME_INDEX: Final[str] = "by-start-time"
APPOINTMENTS_BY_PATIENT_INDEX: Final[str] = "by-patient"
PATIENTS_BY_PHONE_INDEX: Final[str] = "by-phone"
ESCALATIONS_BY_CREATED_AT_INDEX: Final[str] = "by-created-at"


# --------------------------------------------------------------------------
# Status vocabularies
# --------------------------------------------------------------------------


class AppointmentStatus(StrEnum):
    """Lifecycle of one appointment.

    Kept to the states the flows in `project-overview.md` actually
    distinguish. A reschedule is *not* a status: it moves `starts_at` and
    appends to the appointment's reschedule history while the appointment
    stays `SCHEDULED`. That is what lets the dashboard's autonomous-action
    log be derived from the appointment item itself.
    """

    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


# Statuses that still occupy their slot, and are therefore the ones an
# availability check and the daily background scan care about. A cancelled
# or no-show appointment stays in the table as history but frees its time.
ACTIVE_APPOINTMENT_STATUSES: Final[frozenset[AppointmentStatus]] = frozenset(
    {AppointmentStatus.SCHEDULED}
)


class EscalationStatus(StrEnum):
    """Whether a flagged item still needs a human.

    Two states only: `architecture.md` -> Storage Model has the dashboard
    read a clinic's escalations newest-first and filter to the open ones,
    so anything richer would be key-design cost with no reader.
    """

    OPEN = "open"
    RESOLVED = "resolved"


class EscalationSource(StrEnum):
    """Which agent path raised an escalation.

    The two paths `project-overview.md` describes: a live voice session
    that could not safely resolve the request, and the daily background
    scan that hit a case needing a judgment call. The dashboard shows both
    in one queue, so the queue has to record which is which.
    """

    VOICE = "voice"
    BACKGROUND = "background"


class ClinicType(StrEnum):
    """The two clinic types seeded for the demo (`project-overview.md`)."""

    DENTAL = "dental"
    COSMETIC = "cosmetic"


class RescheduleActor(StrEnum):
    """Who moved or cancelled an appointment, for one `reschedule_history` entry.

    `architecture.md` -> Storage Model fixes these two values and says why
    they cannot be inferred later: the dashboard's action log exists to show
    which moves the *agent* made unprompted, and after the fact an agent's
    reschedule and a staff member's look identical on the item.

    The live voice agent and the background job both write `AGENT`; only the
    staff dashboard's own API may write `STAFF`. It is never a value a model
    chooses -- see `tools.appointments.reschedule_appointment`.
    """

    AGENT = "agent"
    STAFF = "staff"


# --------------------------------------------------------------------------
# Non-key attributes, grouped by table
# --------------------------------------------------------------------------


class ClinicAttrs:
    """`Clinics` item: the per-tenant config every other lookup starts from.

    Fields follow `project-overview.md` ("clinic config: name, type,
    hours, services, contact info"), plus `TIMEZONE`, without which
    `HOURS` and "runs daily per clinic" have no fixed meaning.

    `TIMEZONE`, `HOURS`, `CLOSURES`, `SERVICES` and `SLOT_MINUTES` are the
    complete availability config: `architecture.md` -> Storage Model
    requires that nothing outside a clinic's own item is consulted to
    decide whether a time is bookable. Their nested value shapes are
    specified there -- see the module docstring.

    `COUNTRY_CODE` is a separate concern -- phone-number reconciliation,
    not availability -- and is optional: a clinic with none set leaves
    `validation.normalise_phone` at its old behaviour (see there).
    """

    CLINIC_ID: Final[str] = CLINIC_ID
    NAME: Final[str] = "name"
    CLINIC_TYPE: Final[str] = "clinic_type"
    # Availability config. Hours and closures are clinic-local wall-clock
    # time; every timestamp this layer stores stays UTC.
    TIMEZONE: Final[str] = "timezone"
    HOURS: Final[str] = "hours"
    CLOSURES: Final[str] = "closures"
    SERVICES: Final[str] = "services"
    SLOT_MINUTES: Final[str] = "slot_minutes"
    # Digits only, no leading "+" (e.g. "44", "1") -- see
    # `validation.normalise_phone`. Optional; absent means "don't reconcile".
    COUNTRY_CODE: Final[str] = "country_code"
    CONTACT_EMAIL: Final[str] = "contact_email"
    CONTACT_PHONE: Final[str] = "contact_phone"
    CREATED_AT: Final[str] = CREATED_AT
    UPDATED_AT: Final[str] = "updated_at"


class HoursInterval:
    """Keys of one opening interval inside a clinic's `hours` weekday list.

    `{"open": "HH:MM", "close": "HH:MM"}`, 24-hour clinic-local wall-clock
    time. A weekday maps to a *list* of these, so a lunch break or a split
    shift is expressible; an empty list means closed that day.
    """

    OPEN: Final[str] = "open"
    CLOSE: Final[str] = "close"


class ClosureAttrs:
    """Keys of one entry in a clinic's `closures` list.

    `{"date": "YYYY-MM-DD", "label": str}`. Whole-day only: a matching date
    removes the day regardless of `hours` (`architecture.md` -> Storage
    Model). `label` is shown to a human, never matched on.
    """

    DATE: Final[str] = "date"
    LABEL: Final[str] = "label"


class ServiceAttrs:
    """Keys of one entry in a clinic's `services` list.

    `{"id": str, "name": str, "duration_minutes": int}`. `id` is the stable
    machine key written to an appointment's `service` attribute and never
    spoken; `name` is what the agent says and hears. `duration_minutes` is
    what sets an appointment's `ends_at`, so it -- not `slot_minutes` --
    decides how much of an opening interval a booking consumes.
    """

    ID: Final[str] = "id"
    NAME: Final[str] = "name"
    DURATION_MINUTES: Final[str] = "duration_minutes"


# Keys of the `hours` map, ordered to match `datetime.date.weekday()`
# (Monday is 0) so `weekday_key` is an index rather than a lookup table.
# All seven are always present on a clinic item.
WEEKDAY_KEYS: Final[tuple[str, ...]] = (
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
)


class PatientAttrs:
    """`Patients` item: the minimal demo profile.

    `PHONE` is how a voice caller identifies themselves and is the sort
    key of the `by-phone` index, so it is stored in one normalised form
    (see `validation.normalise_phone`) -- otherwise the lookup would need
    a scan instead of an equality match.
    """

    CLINIC_ID: Final[str] = CLINIC_ID
    PATIENT_ID: Final[str] = PATIENT_ID
    NAME: Final[str] = "name"
    PHONE: Final[str] = PHONE
    EMAIL: Final[str] = "email"
    CREATED_AT: Final[str] = CREATED_AT
    UPDATED_AT: Final[str] = "updated_at"


class AppointmentAttrs:
    """`Appointments` item: "patient reference, time, status, history".

    `CLINIC_PATIENT` is the composite index key. It is written on every
    appointment by the tool layer and never supplied by a caller.

    `REMINDERS` and `RESCHEDULE_HISTORY` are append-only lists. They exist
    because `architecture.md` -> Storage Model derives the dashboard's
    autonomous-action log from them plus `Escalations` rather than adding
    a fifth table. What one entry contains is specified there too
    ("Appointment history entry shapes") and landed below as
    `RescheduleEntry` and `ReminderEntry`.
    """

    CLINIC_ID: Final[str] = CLINIC_ID
    APPOINTMENT_ID: Final[str] = APPOINTMENT_ID
    CLINIC_PATIENT: Final[str] = CLINIC_PATIENT
    PATIENT_ID: Final[str] = PATIENT_ID
    # Denormalised so the dashboard day view and a reminder email do not
    # need a second read per appointment. The `Patients` item remains the
    # source of truth for a patient's current name.
    PATIENT_NAME: Final[str] = "patient_name"
    SERVICE: Final[str] = "service"
    STARTS_AT: Final[str] = STARTS_AT
    ENDS_AT: Final[str] = "ends_at"
    STATUS: Final[str] = "status"
    NOTES: Final[str] = "notes"
    REMINDERS: Final[str] = "reminders"
    RESCHEDULE_HISTORY: Final[str] = "reschedule_history"
    CREATED_AT: Final[str] = CREATED_AT
    UPDATED_AT: Final[str] = "updated_at"


class RescheduleEntry:
    """Keys of one entry in an appointment's `reschedule_history` list.

    `{"at", "from", "to", "actor", "reason"}`, fixed by `architecture.md` ->
    Storage Model. `AT` is when the move happened and `FROM`/`TO` are the
    old and new `starts_at`, all three in `ISO8601_FORMAT` -- the same
    encoding as every other timestamp, since the dashboard renders them
    beside the appointment's own times. `ACTOR` is a `RescheduleActor`.
    `REASON` is free text with no machine reader, like an escalation's.

    `TO` is `None` for a **cancellation**. A cancelled appointment is a move
    to nowhere: `status` alone records that it happened, but not who did it
    or why, and those are exactly what the dashboard's action log is for.
    Encoding it here rather than as a fifth appointment attribute keeps the
    log one list to read (`tools.appointments.cancel_appointment`).
    """

    AT: Final[str] = "at"
    FROM: Final[str] = "from"
    TO: Final[str] = "to"
    ACTOR: Final[str] = "actor"
    REASON: Final[str] = "reason"


class ReminderEntry:
    """Keys of one entry in an appointment's `reminders` list.

    `{"at", "channel", "outcome"}`, fixed by `architecture.md` -> Storage
    Model. `CHANNEL` is `email` (SES is the only one in scope) and `OUTCOME`
    distinguishes "we reminded them" from "we tried and SES rejected it",
    which are different facts for staff deciding whether to phone a patient.
    Their value vocabularies land with the background job, the only writer.
    """

    AT: Final[str] = "at"
    CHANNEL: Final[str] = "channel"
    OUTCOME: Final[str] = "outcome"


class ReminderChannel(StrEnum):
    """`ReminderEntry.CHANNEL` values. SES email is the only channel in
    scope (`architecture.md` -> Stack); the vocabulary exists as an enum
    rather than a bare string so a second channel is one member to add, not
    a string to get right twice.
    """

    EMAIL = "email"


class ReminderOutcome(StrEnum):
    """`ReminderEntry.OUTCOME` values, landed by `tools.automation`, the
    only writer of a `reminders` entry.

    `SENT` and `FAILED` are the two facts `architecture.md` -> Storage Model
    says staff need distinguished: "we reminded them" from "we tried and it
    did not go" -- whether the failure is SES rejecting the send or the
    patient having no address on file, both mean the same thing to a
    person deciding whether to phone them instead.
    """

    SENT = "sent"
    FAILED = "failed"


class EscalationAttrs:
    """`Escalations` item: what was flagged, why, and whether it is handled.

    `REASON` is free text on purpose: it is written by the Escalation
    sub-agent and read by a human, on the dashboard or in an SES email. A
    closed reason vocabulary would be product behavior none of the context
    files define, and the field has no machine reader.
    """

    CLINIC_ID: Final[str] = CLINIC_ID
    ESCALATION_ID: Final[str] = ESCALATION_ID
    STATUS: Final[str] = "status"
    SOURCE: Final[str] = "source"
    REASON: Final[str] = "reason"
    # Optional back-references to what the escalation is about.
    PATIENT_ID: Final[str] = PATIENT_ID
    APPOINTMENT_ID: Final[str] = APPOINTMENT_ID
    CREATED_AT: Final[str] = CREATED_AT
    RESOLVED_AT: Final[str] = "resolved_at"


# --------------------------------------------------------------------------
# Id and timestamp encodings
# --------------------------------------------------------------------------

PATIENT_ID_PREFIX: Final[str] = "pat"
APPOINTMENT_ID_PREFIX: Final[str] = "apt"
ESCALATION_ID_PREFIX: Final[str] = "esc"

# `2026-08-27T14:30:00Z`: fixed width, UTC, second precision, `Z` suffix.
# Not cosmetic -- `starts_at` and `created_at` are sort keys and DynamoDB
# orders strings bytewise, so a mix of offsets ("+00:00") or of precisions
# would silently order items wrongly. Every timestamp this layer writes
# goes through `to_iso8601`.
ISO8601_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"

# `2026-08-27`: a calendar date with no time and no zone -- the `closures`
# entries and the day a caller asks about. Distinct from `ISO8601_FORMAT`
# because a date is not an instant: "the 27th" means the clinic's local
# day, and only `tools.scheduling` turns it into UTC instants.
DATE_FORMAT: Final[str] = "%Y-%m-%d"

# `09:00`: clinic-local wall-clock time, used by `hours` and by the local
# start/end a tool hands back for the agent to speak. Never stored.
LOCAL_TIME_FORMAT: Final[str] = "%H:%M"


def new_id(prefix: str) -> str:
    """Generate an opaque, collision-free entity id, e.g. ``apt_1f3c...``.

    Args:
        prefix: One of the ``*_ID_PREFIX`` constants in this module.

    Returns:
        The prefix, an underscore, and a uuid4 in hex. Contains no
        `KEY_SEPARATOR`, so ids compose into `clinic_patient_key` safely.
    """
    return f"{prefix}_{uuid.uuid4().hex}"


def clinic_patient_key(clinic_id: str, patient_id: str) -> str:
    """Build the `clinic_patient` composite key for the `by-patient` index.

    The index is keyed on this composite rather than on `patient_id` so
    that "this patient's appointments" cannot be expressed as a
    cross-clinic query at all (`architecture.md` -> Invariants #1).

    Args:
        clinic_id: The tenant the appointment belongs to.
        patient_id: The patient within that tenant.

    Returns:
        ``{clinic_id}#{patient_id}``.

    Raises:
        ValidationError: If either part is blank or contains the
            separator. An ambiguous split would let one clinic's composite
            key collide with another's, which is the one thing this key
            exists to prevent.
    """
    parts = {CLINIC_ID: clinic_id, PATIENT_ID: patient_id}
    for field, value in parts.items():
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{field} is required and must be a non-empty string.")
        if KEY_SEPARATOR in value:
            raise ValidationError(
                f"{field} must not contain {KEY_SEPARATOR!r}: it is the composite "
                "key separator."
            )
    return f"{clinic_id.strip()}{KEY_SEPARATOR}{patient_id.strip()}"


def to_iso8601(value: datetime) -> str:
    """Normalise a datetime to this project's single timestamp encoding.

    Args:
        value: Aware or naive datetime. A naive value is read as UTC, per
            `architecture.md` -> Storage Model ("all timestamps ISO-8601
            UTC"); an aware value is converted to UTC.

    Returns:
        A string in `ISO8601_FORMAT`, safe to use as a sort key.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime(ISO8601_FORMAT)


def from_iso8601(value: str) -> datetime:
    """Read a stored timestamp back into an aware UTC datetime.

    The inverse of `to_iso8601`, for the tools that have to do arithmetic
    on stored times (does this appointment overlap that slot?) rather than
    just compare them as sort keys.

    Args:
        value: A string written by `to_iso8601`.

    Returns:
        A timezone-aware datetime in UTC.

    Raises:
        ValidationError: If the string is not in `ISO8601_FORMAT`. Stored
            values always are, so this is a corrupt-data signal, not a
            caller-input one.
    """
    try:
        parsed = datetime.strptime(value, ISO8601_FORMAT)
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            f"Timestamp must be in the form {ISO8601_FORMAT}; got {value!r}."
        ) from exc
    return parsed.replace(tzinfo=timezone.utc)


def utc_now_iso() -> str:
    """The current UTC time in `ISO8601_FORMAT`, for `created_at`/`updated_at`."""
    return to_iso8601(datetime.now(timezone.utc))


def weekday_key(value: date) -> str:
    """The `hours` map key for a calendar date, e.g. ``"mon"``.

    Args:
        value: A clinic-local calendar date.

    Returns:
        One of `WEEKDAY_KEYS`.
    """
    return WEEKDAY_KEYS[value.weekday()]
