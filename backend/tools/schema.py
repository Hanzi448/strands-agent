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
and the key/timestamp encodings the tables' sort keys depend on; the
nested key names inside those values land here as constants with the
first tool that reads them (`check_availability`).

The key attribute and index names below must match
`backend/infra/data_stack.py` exactly;
`backend/tests/test_schema_matches_infra.py` asserts that they do, so the
duplication cannot drift unnoticed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
    CONTACT_EMAIL: Final[str] = "contact_email"
    CONTACT_PHONE: Final[str] = "contact_phone"
    CREATED_AT: Final[str] = CREATED_AT
    UPDATED_AT: Final[str] = "updated_at"


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
    a fifth table. What one entry contains is decided by the tools that
    write them (reminder dispatch, auto-reschedule), not here.
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


def utc_now_iso() -> str:
    """The current UTC time in `ISO8601_FORMAT`, for `created_at`/`updated_at`."""
    return to_iso8601(datetime.now(timezone.utc))
