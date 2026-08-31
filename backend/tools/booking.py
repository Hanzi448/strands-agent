"""Booking: the first tool in this layer that writes.

Everything in `tools.scheduling` answers questions; this module commits an
answer. The two are separate modules rather than one because they fail
differently and are called at different moments -- availability is asked
repeatedly while a patient thinks aloud, a booking happens once, and a bug
in the first shows a wrong list while a bug in the second puts a wrong row
in a clinic's diary.

**The rule is not restated here.** Whether a time is bookable is decided by
`scheduling.offerable_slots_for_date`, the same `_day_plan`/`_compute_slots`
pair `check_availability` runs. This module asks that question again at
write time and takes its `ends_at` from the matched slot rather than
recomputing one -- so the appointment that lands in the table is exactly a
slot the availability rule produced. A second copy of the composition rule
here is the specific failure `architecture.md` -> Invariants #3 rules out.

**Why the re-check exists at all**: a slot offered to a patient can be
taken while they are still deciding. The gap this closes is a conversation
turn wide -- tens of seconds. What it does not close is the milliseconds
between this check and the `put_item`: DynamoDB cannot condition a write on
"no appointment overlaps this span" without a transaction over rows that do
not exist yet, so two callers colliding inside that window would both be
booked. For a two-clinic demo that is the right trade; it is recorded in
`progress-tracker.md` rather than hidden here, because the fix (a
per-clinic-slot lock item written conditionally) is a real design change,
not a line of defensive code.
"""

from __future__ import annotations

from typing import Any

from .dynamo import appointments_table
from .errors import ConflictError
from .patients import lookup_or_create_patient, patient_summary
from .scheduling import (
    clinic_timezone,
    get_clinic,
    offerable_slots_for_date,
    resolve_service,
    unavailable_message,
)
from .schema import (
    APPOINTMENT_ID_PREFIX,
    CLINIC_ID,
    AppointmentAttrs,
    AppointmentStatus,
    ClinicAttrs,
    PatientAttrs,
    ServiceAttrs,
    clinic_patient_key,
    from_iso8601,
    new_id,
    utc_now_iso,
)
from .validation import (
    MAX_IDENTIFIER_LENGTH,
    normalise_email,
    normalise_phone,
    require_clinic_id,
    require_text,
    require_timestamp,
)


def book_appointment(
    clinic_id: str,
    starts_at: str,
    service: str,
    patient_name: str,
    patient_phone: str,
    patient_email: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Book one appointment for a caller, registering them if they are new.

    Re-checks that the requested time is still offerable before writing,
    because a time quoted earlier in the conversation may have been taken
    since. Resolves the caller from their phone number and name, creating
    a patient record the first time they call.

    Call `check_availability` first and pass one of the `starts_at` values
    it returned. A time that is not currently offerable -- off the clinic's
    slot grid, too close to closing for this service, on a closed day, or
    already taken -- is refused rather than adjusted to a nearby one.

    Args:
        clinic_id: The clinic the caller is talking to. Required; never
            inferred or defaulted.
        starts_at: The appointment start, UTC, as returned by
            `check_availability` (``2026-08-27T14:30:00Z``). Not a local
            time and not a spoken one -- take it from a slot, never build
            it from what the patient said.
        service: Which service to book, as the service id or the name the
            clinic uses. It sets the appointment's length, so it must be
            the same service the availability check was made for.
        patient_name: The caller's name, as spoken. Stored on the
            appointment as well as the patient record, so it is what staff
            see in the day view.
        patient_phone: The caller's phone number, in any spoken form. This
            is how the caller is recognised on their next call, so ask for
            it rather than guessing.
        patient_email: Optional. An address for appointment reminders. If
            the patient is already known and has one stored, theirs is
            kept.
        notes: Optional free text from the patient about the visit.

    Returns:
        A dict with:
          - ``appointment_id``, ``clinic_id``, ``status`` (``scheduled``).
          - ``service``: ``{"id", "name", "duration_minutes"}``.
          - ``date`` (clinic-local ``YYYY-MM-DD``), ``starts_at`` and
            ``ends_at`` in UTC, and ``local_start``/``local_end`` as
            ``HH:MM`` in the clinic's own time -- say the local ones out
            loud, quote neither UTC value to a patient.
          - ``patient``: ``{"patient_id", "name", "phone", "is_new"}``.
            ``is_new`` false means this caller already had a record, which
            is worth acknowledging rather than asking them to confirm
            details they have given before.
          - ``notes``: what was stored, or null.

    Raises:
        ValidationError: If any required argument is missing or malformed,
            or if the clinic does not offer that service.
        NotFoundError: If no clinic exists with that `clinic_id`.
        ConflictError: If the requested time is not one the clinic can
            offer right now. The message names times that are still free
            that day, so the patient can be offered one immediately
            instead of starting the availability check again.
        ConfigurationError: If the clinic's stored availability config is
            unusable. A deployment fault; never read out to a patient.
    """
    # Tenant boundary first, before any read (`code-standards.md` -> Python).
    # Shape only here -- `patient_phone` is re-normalised below with the
    # clinic's own `country_code`, once the clinic has been read for its
    # other config anyway; this first pass still rejects a malformed number
    # before any read, exactly as the other arguments are validated here.
    clinic_id = require_clinic_id(clinic_id)
    requested_start = require_timestamp(starts_at, "starts_at")
    name = require_text(patient_name, "patient_name", max_length=MAX_IDENTIFIER_LENGTH)
    phone = normalise_phone(patient_phone, "patient_phone")
    email = None if patient_email is None else normalise_email(
        patient_email, "patient_email"
    )
    note_text = None if notes is None else require_text(notes, "notes")

    clinic = get_clinic(clinic_id)
    zone = clinic_timezone(clinic)
    service_entry = resolve_service(clinic, service)
    country_code = clinic.get(ClinicAttrs.COUNTRY_CODE)
    phone = normalise_phone(phone, "patient_phone", country_code)

    # The clinic-local day the requested instant falls on -- the day whose
    # `hours` decide it. Derived from the instant rather than taken as an
    # argument so a caller cannot pair a time with the wrong date.
    local_date = from_iso8601(requested_start).astimezone(zone).date()

    slots = offerable_slots_for_date(clinic, local_date, service_entry, zone)
    slot = next(
        (
            candidate
            for candidate in slots
            if candidate[AppointmentAttrs.STARTS_AT] == requested_start
        ),
        None,
    )
    if slot is None:
        raise ConflictError(unavailable_message(requested_start, zone, slots, clinic))

    # Only now is a record created: a caller who asked for an impossible
    # time should not leave a patient row behind.
    patient, created = lookup_or_create_patient(
        clinic_id, phone=phone, name=name, email=email, country_code=country_code
    )
    patient_id = patient[PatientAttrs.PATIENT_ID]

    from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

    now = utc_now_iso()
    appointment_id = new_id(APPOINTMENT_ID_PREFIX)
    item: dict[str, Any] = {
        AppointmentAttrs.CLINIC_ID: clinic_id,
        AppointmentAttrs.APPOINTMENT_ID: appointment_id,
        # Written by this layer and never supplied by a caller, so the
        # `by-patient` index key is clinic-scoped by construction
        # (`architecture.md` -> Invariants #1).
        AppointmentAttrs.CLINIC_PATIENT: clinic_patient_key(clinic_id, patient_id),
        AppointmentAttrs.PATIENT_ID: patient_id,
        # The stored patient's name, not the spoken one: a returning caller
        # heard slightly differently must not put a second spelling in the
        # clinic's day view.
        AppointmentAttrs.PATIENT_NAME: patient.get(PatientAttrs.NAME, name),
        AppointmentAttrs.SERVICE: service_entry[ServiceAttrs.ID],
        # Both taken from the matched slot, so what is stored is exactly
        # what the availability rule produced.
        AppointmentAttrs.STARTS_AT: slot[AppointmentAttrs.STARTS_AT],
        AppointmentAttrs.ENDS_AT: slot[AppointmentAttrs.ENDS_AT],
        AppointmentAttrs.STATUS: AppointmentStatus.SCHEDULED.value,
        # Present and empty rather than absent: the dashboard's action log
        # and the reminder job both append to these, and an append to a
        # missing attribute is a second code path for no reason.
        AppointmentAttrs.REMINDERS: [],
        AppointmentAttrs.RESCHEDULE_HISTORY: [],
        AppointmentAttrs.CREATED_AT: now,
        AppointmentAttrs.UPDATED_AT: now,
    }
    if note_text is not None:
        item[AppointmentAttrs.NOTES] = note_text

    appointments_table().put_item(
        Item=item,
        # Guards against overwriting an existing appointment, not against a
        # contended slot -- the id is a fresh uuid4, so this can only fire
        # on a genuine bug. Slot contention is discussed in the module
        # docstring.
        ConditionExpression=Attr(AppointmentAttrs.APPOINTMENT_ID).not_exists(),
    )

    return {
        CLINIC_ID: clinic_id,
        AppointmentAttrs.APPOINTMENT_ID: appointment_id,
        AppointmentAttrs.STATUS: AppointmentStatus.SCHEDULED.value,
        "service": service_entry,
        "date": slot["date"],
        AppointmentAttrs.STARTS_AT: slot[AppointmentAttrs.STARTS_AT],
        AppointmentAttrs.ENDS_AT: slot[AppointmentAttrs.ENDS_AT],
        "local_start": slot["local_start"],
        "local_end": slot["local_end"],
        "patient": patient_summary(patient, created),
        AppointmentAttrs.NOTES: note_text,
    }
