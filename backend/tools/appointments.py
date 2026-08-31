"""Changing an appointment that already exists: move it, or call it off.

`book_appointment` creates; this module is everything after. The two writes
here are one module rather than two because they are the same operation
with a different destination -- both have to work out *which* of a caller's
appointments is being talked about, both write one entry to the same
`reschedule_history` list, and a cancellation is a move to nowhere
(`schema.RescheduleEntry`). Splitting them would put that shared
resolution, which is the delicate part, in two places.

**Whose appointment it is** is decided by `patients.find_patient`, the same
phone-*and*-name pair that decides who a booking belongs to. Phone alone
would be enough to find an appointment and is deliberately not enough to
change one: a household shares a number, and silently cancelling a
spouse's appointment is the failure that pair exists to prevent. The cost
is the one already accepted in `patients` -- a caller heard as "Dave" one
week and "David" the next cannot reach their own booking, and the agent's
recovery is to escalate rather than to guess.

**Which appointment** it is, when a caller has several upcoming, is not
guessed either. Both tools refuse with a `ConflictError` naming them, so
the agent asks; taking the soonest would be a silent wrong cancellation,
which is the error a patient discovers by arriving at a closed clinic.

**Whether the new time is bookable** is not decided here at all, any more
than it is in `booking`: `scheduling.offerable_slots_for_date` answers it,
and a reschedule passes its own `appointment_id` as
`exclude_appointment_id` so the booking being moved does not block its own
move. `architecture.md` -> Invariants #3 is the rule -- the composition
rule exists once, in `scheduling`, and every write asks it.

The slot-contention window documented in `booking` applies here too: the
re-check closes the conversation-length gap, not the milliseconds before
the write. What this module *does* settle is a race over the appointment
itself -- an update lands only if the row is still `scheduled` and still at
the time it was read at, so two sessions changing one appointment resolve
to one winner rather than to whichever wrote last.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from .dynamo import appointments_table
from .errors import ConfigurationError, ConflictError, NotFoundError, ValidationError
from .patients import find_patient, patient_summary
from .scheduling import (
    clinic_timezone,
    get_clinic,
    offerable_slots_for_date,
    resolve_service,
    unavailable_message,
)
from .schema import (
    APPOINTMENTS_BY_PATIENT_INDEX,
    CLINIC_ID,
    CLINIC_PATIENT,
    DATE_FORMAT,
    LOCAL_TIME_FORMAT,
    AppointmentAttrs,
    AppointmentStatus,
    PatientAttrs,
    RescheduleActor,
    RescheduleEntry,
    ServiceAttrs,
    clinic_patient_key,
    from_iso8601,
    utc_now_iso,
)
from .validation import (
    MAX_IDENTIFIER_LENGTH,
    normalise_phone,
    require_clinic_id,
    require_enum,
    require_identifier,
    require_text,
    require_timestamp,
)

# How many of a caller's appointments a "which one?" error names. A voice
# agent reading more than this aloud has stopped being useful, and a caller
# with more upcoming than this is a case for staff anyway.
_APPOINTMENTS_IN_ERROR = 3


def find_upcoming_appointments(
    clinic_id: str, patient_phone: str, patient_name: str
) -> list[dict[str, Any]]:
    """One caller's still-scheduled appointments, earliest first.

    The read `reschedule_appointment` and `cancel_appointment` both start
    from, and the only path either takes to an appointment item -- so
    "which appointments may this caller change?" is answered once.

    Args:
        clinic_id: The clinic the caller is talking to. Required; never
            inferred or defaulted.
        patient_phone: The caller's number, in any spoken form.
        patient_name: The caller's name, as spoken. Required as well as the
            number -- see this module's docstring.

    Returns:
        The raw `Appointments` items that are still `scheduled` and start
        from now on, earliest first. Empty if this clinic has no patient
        with that number and name, or if they have nothing coming up -- the
        two are not distinguished here, because neither is an error and
        both mean "nothing to change".

    Raises:
        ValidationError: If `clinic_id`, `patient_phone`, or `patient_name`
            is missing or malformed.
    """
    clinic_id = require_clinic_id(clinic_id)
    phone = normalise_phone(patient_phone, "patient_phone")
    name = require_text(patient_name, "patient_name", max_length=MAX_IDENTIFIER_LENGTH)

    patient = find_patient(clinic_id, phone, name)
    if patient is None:
        return []
    return upcoming_appointments_for_patient(
        clinic_id, patient[PatientAttrs.PATIENT_ID]
    )


def upcoming_appointments_for_patient(
    clinic_id: str, patient_id: str
) -> list[dict[str, Any]]:
    """One patient's still-scheduled appointments, earliest first.

    Separate from `find_upcoming_appointments` because the staff dashboard
    holds a `patient_id` already and has no phone number to look one up by.

    Args:
        clinic_id: The clinic the patient belongs to.
        patient_id: The patient, as stored.

    Returns:
        Items with `status` `scheduled` and `starts_at` from now on,
        earliest first (the index's own order). An appointment already
        under way is excluded along with the past ones: its start is behind
        us, and it is not a thing a caller can still move.

    Raises:
        ValidationError: If either id is missing or malformed.
    """
    now = utc_now_iso()
    return [
        item
        for item in appointment_history_for_patient(clinic_id, patient_id)
        if str(item.get(AppointmentAttrs.STATUS, "")) == AppointmentStatus.SCHEDULED.value
        and str(item.get(AppointmentAttrs.STARTS_AT, "")) >= now
    ]


def appointment_history_for_patient(
    clinic_id: str, patient_id: str
) -> list[dict[str, Any]]:
    """Every appointment on record for one patient, any status, any time.

    The `by-patient` query itself, unfiltered -- `upcoming_appointments_for_patient`
    is this narrowed to `scheduled` and not-yet-started, and
    `tools.automation`'s no-show risk check reads the whole history because
    it needs *past* `no_show` entries, which that narrower read excludes by
    design.

    Queries `by-patient`, whose partition key is the composite
    `{clinic_id}#{patient_id}` -- so "this patient's appointments" is not
    expressible across clinics at all (`architecture.md` -> Invariants #1).

    Args:
        clinic_id: The clinic the patient belongs to.
        patient_id: The patient, as stored.

    Returns:
        Every item under this patient's partition, earliest `starts_at`
        first (the index's own order, across all statuses and all time).

    Raises:
        ValidationError: If either id is missing or malformed.
    """
    clinic_id = require_clinic_id(clinic_id)
    patient_id = require_identifier(patient_id, PatientAttrs.PATIENT_ID)

    # Lazy, mirroring `dynamo._dynamodb_resource`: importing this module
    # must not require the AWS SDK.
    from boto3.dynamodb.conditions import Key  # noqa: PLC0415

    table = appointments_table()
    query: dict[str, Any] = {
        "IndexName": APPOINTMENTS_BY_PATIENT_INDEX,
        "KeyConditionExpression": Key(CLINIC_PATIENT).eq(
            clinic_patient_key(clinic_id, patient_id)
        ),
    }
    items: list[dict[str, Any]] = []
    while True:
        response = table.query(**query)
        items.extend(response.get("Items", []))
        next_key = response.get("LastEvaluatedKey")
        if not next_key:
            return items
        query["ExclusiveStartKey"] = next_key


def reschedule_appointment(
    clinic_id: str,
    patient_phone: str,
    patient_name: str,
    new_starts_at: str,
    appointment_id: str | None = None,
    reason: str | None = None,
    *,
    actor: str | RescheduleActor = RescheduleActor.AGENT,
) -> dict[str, Any]:
    """Move one of a caller's appointments to a different time.

    Keeps the same service, and so the same length -- this changes *when*,
    not *what*. A patient who wants a different treatment needs the old
    appointment cancelled and a new one booked.

    Call `check_availability` first and pass one of the `starts_at` values
    it returned. The new time is re-checked here before anything is
    written, because a time quoted earlier in the conversation may have
    been taken since; a time that is not offerable is refused rather than
    adjusted to a nearby one.

    Args:
        clinic_id: The clinic the caller is talking to. Required; never
            inferred or defaulted.
        patient_phone: The caller's number, in any spoken form.
        patient_name: The caller's name, as spoken. Required as well as the
            number: it is what stops one member of a household moving
            another's appointment.
        new_starts_at: The new start, UTC, as returned by
            `check_availability` (``2026-08-27T14:30:00Z``). Take it from a
            slot; never build it from what the patient said.
        appointment_id: Which appointment to move. Omit it when the caller
            has only one coming up. If they have several this tool refuses
            and names them -- ask the patient which, then call again with
            that id.
        reason: Optional free text: why the appointment moved. Clinic staff
            read it in the dashboard's log of what the agent did, so a
            short "patient asked to move it" is worth passing.

    Returns:
        A dict with:
          - ``appointment_id``, ``clinic_id``, ``status`` (still
            ``scheduled`` -- a move is not a status change).
          - ``service``: ``{"id", "name", "duration_minutes"}``.
          - ``date`` (clinic-local ``YYYY-MM-DD``), ``starts_at`` and
            ``ends_at`` in UTC, and ``local_start``/``local_end`` as
            ``HH:MM`` in the clinic's own time -- say the local ones out
            loud, quote neither UTC value to a patient.
          - ``previous``: the same five fields for where the appointment
            *was*, so the move can be confirmed back to the patient in
            full.
          - ``patient``: ``{"patient_id", "name", "phone", "is_new"}``.
          - ``notes``: the appointment's notes, unchanged, or null.

    Raises:
        ValidationError: If any required argument is missing or malformed.
        NotFoundError: If no clinic exists with that `clinic_id`, or if
            this caller has no upcoming appointment -- or none with that
            `appointment_id` -- to move.
        ConflictError: If the caller has several upcoming appointments and
            none was named, if the appointment is already at that time, or
            if the new time is not one the clinic can offer right now. The
            message names the alternatives in each case, so the patient can
            be answered immediately instead of starting over.
        ConfigurationError: If the clinic's stored availability config is
            unusable, or no longer offers the appointment's service. A
            deployment fault; never read out to a patient.
    """
    # Tenant boundary first, before any read (`code-standards.md` -> Python).
    clinic_id = require_clinic_id(clinic_id)
    requested_start = require_timestamp(new_starts_at, "new_starts_at")
    move_reason = None if reason is None else require_text(reason, "reason")
    moved_by = require_enum(actor, RescheduleActor, "actor")

    clinic = get_clinic(clinic_id)
    zone = clinic_timezone(clinic)
    patient, appointment = _resolve_appointment(
        clinic, clinic_id, patient_phone, patient_name, appointment_id, zone
    )
    target_id = str(appointment[AppointmentAttrs.APPOINTMENT_ID])
    current_start = str(appointment[AppointmentAttrs.STARTS_AT])

    if requested_start == current_start:
        # Not a silent success: a `from`/`to` pair saying nothing happened
        # would put a move in the staff action log that never occurred, and
        # the model needs to hear that it misread the patient.
        raise ConflictError(
            "That appointment is already at "
            f"{_spoken_when(current_start, zone)}. Nothing was changed."
        )

    service_entry = _stored_service(clinic, appointment)
    local_date = from_iso8601(requested_start).astimezone(zone).date()
    slots = offerable_slots_for_date(
        clinic,
        local_date,
        service_entry,
        zone,
        # Without this the appointment blocks its own move: any new time
        # within one service length of the old one overlaps the row that is
        # about to be vacated.
        exclude_appointment_id=target_id,
    )
    slot = next(
        (
            candidate
            for candidate in slots
            if candidate[AppointmentAttrs.STARTS_AT] == requested_start
        ),
        None,
    )
    if slot is None:
        raise ConflictError(
            unavailable_message(
                requested_start, zone, slots, clinic, "move that appointment to"
            )
        )

    now = utc_now_iso()
    _write_change(
        clinic_id=clinic_id,
        appointment_id=target_id,
        read_start=current_start,
        now=now,
        # Both taken from the matched slot, so what is stored is exactly
        # what the availability rule produced -- as in `book_appointment`.
        changes={
            AppointmentAttrs.STARTS_AT: slot[AppointmentAttrs.STARTS_AT],
            AppointmentAttrs.ENDS_AT: slot[AppointmentAttrs.ENDS_AT],
        },
        entry={
            RescheduleEntry.AT: now,
            RescheduleEntry.FROM: current_start,
            RescheduleEntry.TO: slot[AppointmentAttrs.STARTS_AT],
            RescheduleEntry.ACTOR: moved_by.value,
            RescheduleEntry.REASON: move_reason,
        },
    )

    return {
        CLINIC_ID: clinic_id,
        AppointmentAttrs.APPOINTMENT_ID: target_id,
        AppointmentAttrs.STATUS: AppointmentStatus.SCHEDULED.value,
        "service": service_entry,
        "date": slot["date"],
        AppointmentAttrs.STARTS_AT: slot[AppointmentAttrs.STARTS_AT],
        AppointmentAttrs.ENDS_AT: slot[AppointmentAttrs.ENDS_AT],
        "local_start": slot["local_start"],
        "local_end": slot["local_end"],
        "previous": _local_view(
            current_start, appointment.get(AppointmentAttrs.ENDS_AT), zone
        ),
        "patient": patient_summary(patient, False),
        AppointmentAttrs.NOTES: appointment.get(AppointmentAttrs.NOTES),
    }


def cancel_appointment(
    clinic_id: str,
    patient_phone: str,
    patient_name: str,
    appointment_id: str | None = None,
    reason: str | None = None,
    *,
    actor: str | RescheduleActor = RescheduleActor.AGENT,
) -> dict[str, Any]:
    """Cancel one of a caller's upcoming appointments.

    The appointment stays in the clinic's records as `cancelled` history,
    and its time is free for someone else the moment this returns. Nothing
    is deleted, so a patient who changes their mind gets a fresh booking
    rather than this one undone.

    Args:
        clinic_id: The clinic the caller is talking to. Required; never
            inferred or defaulted.
        patient_phone: The caller's number, in any spoken form.
        patient_name: The caller's name, as spoken. Required as well as the
            number: it is what stops one member of a household cancelling
            another's appointment.
        appointment_id: Which appointment to cancel. Omit it when the
            caller has only one coming up. If they have several this tool
            refuses and names them -- ask the patient which, then call
            again with that id.
        reason: Optional free text: why it was cancelled. Clinic staff read
            it in the dashboard's log of what the agent did, and a
            cancellation with no reason tells them nothing, so pass what
            the patient said.

    Returns:
        A dict with:
          - ``appointment_id``, ``clinic_id``, ``status`` (``cancelled``).
          - ``service``: ``{"id", "name", "duration_minutes"}``.
          - ``date``, ``starts_at``, ``ends_at``, ``local_start`` and
            ``local_end`` for the appointment that *was* booked, so it can
            be read back as confirmation of what was called off. Say the
            local values, not the UTC ones.
          - ``patient``: ``{"patient_id", "name", "phone", "is_new"}``.
          - ``reason``: what was recorded, or null.

    Raises:
        ValidationError: If any required argument is missing or malformed.
        NotFoundError: If no clinic exists with that `clinic_id`, or if
            this caller has no upcoming appointment -- or none with that
            `appointment_id` -- to cancel.
        ConflictError: If the caller has several upcoming appointments and
            none was named (the message names them), or if this one was
            moved or cancelled by someone else while the call was in
            progress.
        ConfigurationError: If the clinic's stored config no longer offers
            the appointment's service. A deployment fault; never read out
            to a patient.
    """
    # Tenant boundary first, before any read (`code-standards.md` -> Python).
    clinic_id = require_clinic_id(clinic_id)
    cancel_reason = None if reason is None else require_text(reason, "reason")
    cancelled_by = require_enum(actor, RescheduleActor, "actor")

    clinic = get_clinic(clinic_id)
    zone = clinic_timezone(clinic)
    patient, appointment = _resolve_appointment(
        clinic, clinic_id, patient_phone, patient_name, appointment_id, zone
    )
    target_id = str(appointment[AppointmentAttrs.APPOINTMENT_ID])
    current_start = str(appointment[AppointmentAttrs.STARTS_AT])
    # Resolved before the write so a clinic that has dropped the service
    # fails without having cancelled anything.
    service_entry = _stored_service(clinic, appointment)

    now = utc_now_iso()
    _write_change(
        clinic_id=clinic_id,
        appointment_id=target_id,
        read_start=current_start,
        now=now,
        changes={AppointmentAttrs.STATUS: AppointmentStatus.CANCELLED.value},
        entry={
            RescheduleEntry.AT: now,
            RescheduleEntry.FROM: current_start,
            # A cancellation is a move to nowhere (`schema.RescheduleEntry`):
            # `status` records that it happened, this records who did it and
            # why, which is what the dashboard's action log is for.
            RescheduleEntry.TO: None,
            RescheduleEntry.ACTOR: cancelled_by.value,
            RescheduleEntry.REASON: cancel_reason,
        },
    )

    return {
        CLINIC_ID: clinic_id,
        AppointmentAttrs.APPOINTMENT_ID: target_id,
        AppointmentAttrs.STATUS: AppointmentStatus.CANCELLED.value,
        "service": service_entry,
        **_local_view(current_start, appointment.get(AppointmentAttrs.ENDS_AT), zone),
        "patient": patient_summary(patient, False),
        RescheduleEntry.REASON: cancel_reason,
    }


# --------------------------------------------------------------------------
# Which appointment, and whose
# --------------------------------------------------------------------------


def _resolve_appointment(
    clinic: dict[str, Any],
    clinic_id: str,
    patient_phone: str,
    patient_name: str,
    appointment_id: str | None,
    zone: ZoneInfo,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Work out which appointment a caller means, and prove it is theirs.

    Both writes enter here, so ownership is checked in exactly one place.
    An `appointment_id` is matched *within* the caller's own upcoming list
    rather than fetched by key: an id guessed, or carried over from another
    session, can then never reach another patient's row, and past and
    already-cancelled appointments are out of reach by construction.

    Returns:
        `(patient_item, appointment_item)`.

    Raises:
        NotFoundError: If the number and name identify nobody at this
            clinic, if they have nothing upcoming, or if the named
            appointment is not among their upcoming ones. One message for
            all of them, deliberately: from outside they are the same fact,
            and telling them apart would confirm that some other patient's
            appointment id exists.
        ConflictError: If several are upcoming and none was named.
    """
    phone = normalise_phone(patient_phone, "patient_phone")
    name = require_text(patient_name, "patient_name", max_length=MAX_IDENTIFIER_LENGTH)
    wanted = (
        None
        if appointment_id is None
        else require_identifier(appointment_id, AppointmentAttrs.APPOINTMENT_ID)
    )

    patient = find_patient(clinic_id, phone, name)
    upcoming = (
        []
        if patient is None
        else upcoming_appointments_for_patient(
            clinic_id, patient[PatientAttrs.PATIENT_ID]
        )
    )

    if wanted is not None:
        match = next(
            (
                item
                for item in upcoming
                if str(item.get(AppointmentAttrs.APPOINTMENT_ID)) == wanted
            ),
            None,
        )
        if patient is None or match is None:
            raise NotFoundError(_nothing_to_change(name))
        return patient, match

    if patient is None or not upcoming:
        raise NotFoundError(_nothing_to_change(name))
    if len(upcoming) > 1:
        raise ConflictError(_which_one(clinic, upcoming, zone))
    return patient, upcoming[0]


def _nothing_to_change(name: str) -> str:
    """The one message every "cannot reach that appointment" case gets."""
    return (
        f"No upcoming appointment is registered for {name} on that phone "
        "number at this clinic. Check the name and number as the patient "
        "gives them; if they are sure, this needs a member of staff."
    )


def _which_one(
    clinic: dict[str, Any], upcoming: list[dict[str, Any]], zone: ZoneInfo
) -> str:
    """Name a caller's upcoming appointments so the agent can ask which one.

    The alternative -- taking the soonest -- would move or cancel the wrong
    appointment with nobody noticing until the patient arrived. So this
    refuses, and hands back what is needed to ask the question out loud in
    one turn: what each appointment is for, when it is, and the id to pass
    back.
    """
    described = [
        f"{_service_label(clinic, item)} at "
        f"{_spoken_when(str(item.get(AppointmentAttrs.STARTS_AT, '')), zone)} "
        f"(appointment_id {item.get(AppointmentAttrs.APPOINTMENT_ID)})"
        for item in upcoming[:_APPOINTMENTS_IN_ERROR]
    ]
    more = (
        ""
        if len(upcoming) <= _APPOINTMENTS_IN_ERROR
        else f", and {len(upcoming) - _APPOINTMENTS_IN_ERROR} more"
    )
    return (
        f"That caller has {len(upcoming)} upcoming appointments: "
        f"{'; '.join(described)}{more}. Ask which one they mean and call "
        "again with its appointment_id."
    )


# --------------------------------------------------------------------------
# Reading a stored appointment
# --------------------------------------------------------------------------


def _stored_service(
    clinic: dict[str, Any], appointment: dict[str, Any]
) -> dict[str, Any]:
    """The clinic's config for the service an appointment was booked for.

    Its `duration_minutes` is what a reschedule needs to know how much of
    the day the moved appointment consumes, and its `name` is what either
    tool reads back to the patient. Resolved from the clinic rather than
    stored on the appointment, so a clinic that renames a service does not
    have to rewrite its diary.

    Raises:
        ConfigurationError: If the clinic no longer lists that service.
            `resolve_service` raises `ValidationError` here, which is the
            wrong signal: no caller supplied this value, so there is
            nothing for a model to correct and retrying is pointless.
    """
    service_id = appointment.get(AppointmentAttrs.SERVICE)
    try:
        return resolve_service(clinic, str(service_id))
    except ValidationError as exc:
        raise ConfigurationError(
            f"Appointment {appointment.get(AppointmentAttrs.APPOINTMENT_ID)} is "
            f"booked for service {service_id!r}, which clinic "
            f"{clinic.get(CLINIC_ID)!r} no longer offers."
        ) from exc


def _service_label(clinic: dict[str, Any], appointment: dict[str, Any]) -> str:
    """A service's spoken name, falling back to its stored id.

    Used only inside error messages, so an unknown service degrades to the
    id rather than replacing a useful "which one?" question with a
    configuration failure.
    """
    try:
        return str(_stored_service(clinic, appointment)[ServiceAttrs.NAME])
    except ConfigurationError:
        return str(appointment.get(AppointmentAttrs.SERVICE, "appointment"))


def _local_view(starts_at: str, ends_at: Any, zone: ZoneInfo) -> dict[str, str | None]:
    """A stored appointment's times, in both the stored and the spoken form.

    The same five fields `check_availability` puts on a slot, rendered from
    what is in the table rather than from a freshly computed one -- a
    cancellation and the "moved from" half of a reschedule are both about a
    time that is no longer offerable, so neither can be looked up.

    `ends_at` is tolerated as missing, for the reason
    `scheduling._appointment_span` gives: a row without one is bad data
    rather than a supported shape, and refusing to describe the appointment
    the patient is asking about would be the worse answer.
    """
    local_start = from_iso8601(starts_at).astimezone(zone)
    stored_end = ends_at if isinstance(ends_at, str) else None
    local_end = (
        None if stored_end is None else from_iso8601(stored_end).astimezone(zone)
    )
    return {
        "date": local_start.strftime(DATE_FORMAT),
        AppointmentAttrs.STARTS_AT: starts_at,
        AppointmentAttrs.ENDS_AT: stored_end,
        "local_start": local_start.strftime(LOCAL_TIME_FORMAT),
        "local_end": (
            None if local_end is None else local_end.strftime(LOCAL_TIME_FORMAT)
        ),
    }


def _spoken_when(starts_at: str, zone: ZoneInfo) -> str:
    """One stored instant as ``09:00 on 2026-07-01``, for an error message."""
    local = from_iso8601(starts_at).astimezone(zone)
    return f"{local.strftime(LOCAL_TIME_FORMAT)} on {local.strftime(DATE_FORMAT)}"


# --------------------------------------------------------------------------
# The write
# --------------------------------------------------------------------------


def _write_change(
    *,
    clinic_id: str,
    appointment_id: str,
    read_start: str,
    now: str,
    changes: dict[str, Any],
    entry: dict[str, Any],
) -> None:
    """Apply one change and its history entry as a single conditional update.

    Both writes are the same shape -- set a field or two, stamp
    `updated_at`, append one `reschedule_history` entry -- and both have to
    be all-or-nothing: an appointment moved without its history entry is a
    move missing from the staff action log, which is the one thing that log
    exists to show. One `update_item` gives that for free.

    The condition is the appointment's own state as it was read: still
    `scheduled`, and still at `read_start`. It is what makes two sessions
    racing to change one appointment resolve to a single winner. Unlike the
    slot contention discussed in `booking`, this race is between rows that
    already exist, so DynamoDB can settle it.

    `list_append` is guarded with `if_not_exists`: `book_appointment` always
    writes an empty list, but a seeded or hand-written item may not have
    one, and appending to a missing attribute fails the whole update.

    Every attribute is referenced through a `#name` alias rather than
    inline, because `status` -- the one a cancellation sets -- is a DynamoDB
    reserved word.

    Raises:
        ConflictError: If the condition fails, meaning the appointment was
            moved or cancelled between the read above and this write.
    """
    from botocore.exceptions import ClientError  # noqa: PLC0415

    names: dict[str, str] = {}

    def alias(attribute: str) -> str:
        placeholder = f"#{attribute}"
        names[placeholder] = attribute
        return placeholder

    values: dict[str, Any] = {
        ":updated_at": now,
        ":entry": [entry],
        ":empty": [],
        ":read_start": read_start,
        ":scheduled": AppointmentStatus.SCHEDULED.value,
    }
    assignments = [f"{alias(AppointmentAttrs.UPDATED_AT)} = :updated_at"]
    for index, (attribute, value) in enumerate(changes.items()):
        values[f":change{index}"] = value
        assignments.append(f"{alias(attribute)} = :change{index}")
    history = alias(AppointmentAttrs.RESCHEDULE_HISTORY)
    assignments.append(
        f"{history} = list_append(if_not_exists({history}, :empty), :entry)"
    )
    # Built before the call rather than inline: `alias` mutates `names`, and
    # the two must not depend on the order Python evaluates arguments in.
    condition = (
        f"{alias(AppointmentAttrs.STATUS)} = :scheduled AND "
        f"{alias(AppointmentAttrs.STARTS_AT)} = :read_start"
    )

    try:
        appointments_table().update_item(
            Key={
                AppointmentAttrs.CLINIC_ID: clinic_id,
                AppointmentAttrs.APPOINTMENT_ID: appointment_id,
            },
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression=condition,
        )
    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            != "ConditionalCheckFailedException"
        ):
            raise
        raise ConflictError(
            "That appointment changed while this call was in progress -- "
            "someone else has moved or cancelled it. Check its current time "
            "before changing it again."
        ) from exc
