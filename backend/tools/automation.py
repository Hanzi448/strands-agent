"""The daily background scan: reminders, and no-show risk escalation.

`project-overview.md` -> Core User Flow, "Background (autonomous)": once a
day, per clinic, the job looks at each upcoming appointment and decides
what to do with it. `project-overview.md` names three possible decisions --
send a reminder, attempt an automatic reschedule, or flag it for staff --
but the middle one is not implemented here. Confirmed with the user rather
than invented (`ai-workflow-rules.md` -> Handling Missing Requirements):
reminders go out one-way over SES, so there is no confirmation channel a
"likely no-show" could be read off; the only available signal is a
patient's own history at this clinic, and the chosen response to a
flagged appointment is to escalate to staff outright rather than guess a
new time nobody asked for. That keeps `architecture.md` -> Invariants #6
intact -- the job's only autonomous actions are ones a rule in this layer
defines, and "pick a different slot with nobody having asked" is not one.

So the real decision per appointment is binary: escalate, or remind. Both
branches call into `tools.patients`, `tools.appointments` and
`tools.escalations` rather than reading or writing anything of their own,
so the live agent path and this job share the same rules
(`architecture.md` -> Invariants #3) -- there is no second copy of "who is
this patient" or "how do we raise something for staff" here.

**The no-show signal**: a patient's own count of past `no_show` appointments
at this clinic, from `tools.appointments.appointment_history_for_patient`.
`NO_SHOW_RISK_THRESHOLD` is not a product rule and was not asked about --
a boundary decision of the same kind as `escalations.DEFAULT_ESCALATION_LIMIT`,
picked here and flagged rather than buried. Reversible: one constant, one
reader.

**The reminder window**: one email, sent once, for any appointment starting
within `REMINDER_WINDOW` (24 hours) of the moment the job runs -- confirmed
with the user. Idempotency comes from the appointment's own `reminders`
list: an appointment that already has an entry is skipped, so a job rerun
or a window that happened to overlap a previous run's does not send a
second email. This is also what keeps a flagged (escalated) appointment
from being escalated a second time in the ordinary case: with a once-daily
job and a 24-hour window, one appointment falls inside exactly one day's
scan, so neither branch needs a "have I already handled this?" flag beyond
what `reminders` already gives the reminder branch. That is a property of
the window, not a guarantee this module enforces -- worth re-checking if
the window or the schedule's cadence ever changes.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Final
from zoneinfo import ZoneInfo

from .appointments import appointment_history_for_patient
from .dynamo import appointments_table
from .errors import ConfigurationError, ToolError, ValidationError
from .escalations import create_escalation
from .patients import get_patient
from .scheduling import clinic_timezone, get_clinic, resolve_service
from .schema import (
    APPOINTMENTS_BY_START_TIME_INDEX,
    CLINIC_ID,
    DATE_FORMAT,
    LOCAL_TIME_FORMAT,
    STARTS_AT,
    AppointmentAttrs,
    AppointmentStatus,
    ClinicAttrs,
    EscalationSource,
    PatientAttrs,
    ReminderChannel,
    ReminderEntry,
    ReminderOutcome,
    ServiceAttrs,
    from_iso8601,
    to_iso8601,
    utc_now_iso,
)
from .validation import require_clinic_id

# Not a product rule -- see the module docstring. One prior no-show is
# enough to flag the next appointment; raise it here if the demo shows it
# firing too eagerly.
NO_SHOW_RISK_THRESHOLD: Final[int] = 1

# Confirmed with the user: one reminder, 24 hours out. The job is expected
# to run about once a day, so this is also the width of the window each
# run covers.
REMINDER_WINDOW: Final[timedelta] = timedelta(hours=24)

# The verified SES sender identity reminders go out from (`progress-tracker.md`
# -> Session Notes: SES stays in sandbox mode for the demo, sender and
# recipient both the same verified personal Gmail).
REMINDER_SENDER_ENV: Final[str] = "CLINICPILOT_REMINDER_SENDER_EMAIL"


def run_daily_scan(clinic_id: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Run one clinic's daily scan: escalate no-show risk, else remind.

    The whole job `backend/lambda/background_scan.py` invokes. One call is
    one clinic -- `architecture.md` -> Invariants #1 -- so the EventBridge
    schedule that triggers this is expected to pass one `clinic_id` per
    invocation rather than fan out inside a single run.

    Args:
        clinic_id: The clinic to scan. Required; never inferred.
        now: The instant to scan from. Defaults to the real current time;
            a test or a backfill run may pass a fixed one.

    Returns:
        A summary dict: ``clinic_id``, ``scanned`` (how many appointments
        were due), ``reminded``, ``reminder_failed``, ``escalated`` and
        ``skipped`` counts, and ``results`` -- one entry per appointment
        processed, each ``{"appointment_id", "patient_id", "outcome",
        ...}``. Nothing here is read out to a patient; this is a return
        value for a Lambda's own logs and, later, the dashboard's action
        log.

    Raises:
        ValidationError: If `clinic_id` is missing or malformed.
        NotFoundError: If no clinic exists with that `clinic_id`.
        ConfigurationError: If the clinic's stored config is unusable. A
            deployment fault -- the whole scan is abandoned rather than
            run against a clinic whose timezone cannot even be resolved.
    """
    clinic_id = require_clinic_id(clinic_id)
    clinic = get_clinic(clinic_id)
    zone = clinic_timezone(clinic)
    moment = now if now is not None else datetime.now(timezone.utc)

    due = [
        appointment
        for appointment in _scheduled_starting_within(
            clinic_id, moment, moment + REMINDER_WINDOW
        )
        # Idempotency: an appointment that already carries a reminder entry
        # has been through this job before, on some earlier run.
        if not appointment.get(AppointmentAttrs.REMINDERS)
    ]

    results: list[dict[str, Any]] = []
    for appointment in due:
        appointment_id = str(appointment.get(AppointmentAttrs.APPOINTMENT_ID))
        try:
            results.append(
                _process_appointment(clinic_id, clinic, zone, appointment)
            )
        except ToolError as exc:
            # One bad appointment -- a service the clinic no longer offers,
            # a patient record that vanished -- must not sink the rest of
            # the day's scan for every other patient.
            results.append(
                {
                    "appointment_id": appointment_id,
                    "outcome": "failed",
                    "detail": exc.message,
                }
            )

    return {
        CLINIC_ID: clinic_id,
        "scanned": len(due),
        "reminded": sum(1 for r in results if r["outcome"] == "reminder_sent"),
        "reminder_failed": sum(
            1 for r in results if r["outcome"] == "reminder_failed"
        ),
        "escalated": sum(1 for r in results if r["outcome"] == "escalated"),
        "skipped": sum(1 for r in results if r["outcome"] == "failed"),
        "results": results,
    }


def _process_appointment(
    clinic_id: str,
    clinic: dict[str, Any],
    zone: ZoneInfo,
    appointment: dict[str, Any],
) -> dict[str, Any]:
    """Decide, and act on, one due appointment: escalate, or remind."""
    appointment_id = str(appointment.get(AppointmentAttrs.APPOINTMENT_ID))
    patient_id = appointment.get(AppointmentAttrs.PATIENT_ID)
    if not isinstance(patient_id, str) or not patient_id.strip():
        # Bad data -- every appointment `book_appointment` writes carries
        # one -- not a case a caller supplied, so this fails the same way
        # `appointments._stored_service` fails on a vanished service.
        raise ConfigurationError(
            f"Appointment {appointment_id!r} at clinic {clinic_id!r} has no "
            f"{AppointmentAttrs.PATIENT_ID}."
        )

    history = appointment_history_for_patient(clinic_id, patient_id)
    no_show_count = sum(
        1
        for item in history
        if str(item.get(AppointmentAttrs.STATUS, "")) == AppointmentStatus.NO_SHOW.value
    )
    if no_show_count >= NO_SHOW_RISK_THRESHOLD:
        create_escalation(
            clinic_id,
            _risk_reason(clinic, zone, appointment, no_show_count),
            patient_id=patient_id,
            appointment_id=appointment_id,
            # Explicit, not the default, for the reason
            # `escalation_agent.py` passes `voice` explicitly: each path
            # knows its own, and the contrast is the point of the field.
            source=EscalationSource.BACKGROUND,
        )
        return {
            "appointment_id": appointment_id,
            "patient_id": patient_id,
            "outcome": "escalated",
            "no_show_count": no_show_count,
        }

    patient = get_patient(clinic_id, patient_id)
    email = patient.get(PatientAttrs.EMAIL) if patient else None
    now_iso = utc_now_iso()
    if not isinstance(email, str) or not email.strip():
        # A permanent condition, not a transient SES failure -- but the
        # vocabulary staff read is the same "we did not reach them" fact
        # either way (`schema.ReminderOutcome`).
        _record_reminder(clinic_id, appointment_id, ReminderOutcome.FAILED, now_iso)
        return {
            "appointment_id": appointment_id,
            "patient_id": patient_id,
            "outcome": "reminder_failed",
            "detail": "no email on file",
        }

    sent = _send_reminder_email(email, clinic, zone, appointment)
    outcome = ReminderOutcome.SENT if sent else ReminderOutcome.FAILED
    _record_reminder(clinic_id, appointment_id, outcome, now_iso)
    return {
        "appointment_id": appointment_id,
        "patient_id": patient_id,
        "outcome": "reminder_sent" if sent else "reminder_failed",
    }


def _risk_reason(
    clinic: dict[str, Any],
    zone: ZoneInfo,
    appointment: dict[str, Any],
    no_show_count: int,
) -> str:
    """The free-text `reason` for a no-show-risk escalation.

    Read by a person in the dashboard queue or an SES email
    (`tools.escalations.create_escalation`), so it says what a staff member
    needs to act: how many times this has happened before, and which
    appointment is at risk.
    """
    plural = "s" if no_show_count != 1 else ""
    return (
        f"{no_show_count} prior no-show{plural} on record for this patient. "
        f"They are booked for {_service_label(clinic, appointment)} at "
        f"{_spoken_when(str(appointment.get(AppointmentAttrs.STARTS_AT, '')), zone)}. "
        "Flagged for a decision instead of an automatic reminder -- consider "
        "calling to confirm before the appointment."
    )


def _service_label(clinic: dict[str, Any], appointment: dict[str, Any]) -> str:
    """A service's spoken name, falling back to its stored id.

    Mirrors `appointments._service_label`: degrades to the id rather than
    failing the whole escalation over a clinic that has since dropped the
    service -- a person reading the queue can still act on it.
    """
    service_id = appointment.get(AppointmentAttrs.SERVICE)
    try:
        return str(resolve_service(clinic, str(service_id))[ServiceAttrs.NAME])
    except (ValidationError, ConfigurationError):
        return str(service_id or "appointment")


def _spoken_when(starts_at: str, zone: ZoneInfo) -> str:
    """One stored instant as ``09:00 on 2026-07-01``, for a human reader."""
    local = from_iso8601(starts_at).astimezone(zone)
    return f"{local.strftime(LOCAL_TIME_FORMAT)} on {local.strftime(DATE_FORMAT)}"


def _reminder_sender_email() -> str:
    """The verified SES sender address reminders go out from.

    Raises:
        ConfigurationError: If unset. A deployment fault: it means
            reminders cannot work at all, not that this one patient's
            failed to send.
    """
    sender = os.environ.get(REMINDER_SENDER_ENV, "").strip()
    if not sender:
        raise ConfigurationError(
            f"{REMINDER_SENDER_ENV} is not set; the background job has no "
            "verified SES sender address to send a reminder from."
        )
    return sender


def _send_reminder_email(
    to_address: str,
    clinic: dict[str, Any],
    zone: ZoneInfo,
    appointment: dict[str, Any],
) -> bool:
    """Send one reminder email via SES.

    Returns:
        `True` if SES accepted the send, `False` if it did not -- the two
        facts `ReminderOutcome` distinguishes. Not raised as an exception:
        a rejected send is an expected outcome for a batch job, not a
        programming fault.
    """
    # Lazy, mirroring `dynamo._dynamodb_resource`: importing this module
    # must not require the AWS SDK.
    import boto3  # noqa: PLC0415
    from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415

    clinic_name = clinic.get(ClinicAttrs.NAME) or "your clinic"
    when = _spoken_when(str(appointment.get(AppointmentAttrs.STARTS_AT, "")), zone)
    try:
        boto3.client("ses").send_email(
            Source=_reminder_sender_email(),
            Destination={"ToAddresses": [to_address]},
            Message={
                "Subject": {"Data": f"Reminder: your appointment at {clinic_name}"},
                "Body": {
                    "Text": {
                        "Data": (
                            f"This is a reminder of your upcoming appointment at "
                            f"{clinic_name}, {when}."
                        )
                    }
                },
            },
        )
        return True
    except (ClientError, BotoCoreError):
        return False


def _record_reminder(
    clinic_id: str, appointment_id: str, outcome: ReminderOutcome, sent_at: str
) -> None:
    """Append one entry to an appointment's `reminders` list.

    Unlike `appointments._write_change`, this carries no condition on the
    appointment's current state: this job runs once a day, single-threaded
    per clinic, so there is no concurrent writer for it to race -- the
    conditional-write pattern elsewhere in this layer exists for a live
    call racing another live call, which does not apply here.
    """
    appointments_table().update_item(
        Key={
            AppointmentAttrs.CLINIC_ID: clinic_id,
            AppointmentAttrs.APPOINTMENT_ID: appointment_id,
        },
        UpdateExpression=(
            "SET #reminders = list_append(if_not_exists(#reminders, :empty), :entry)"
        ),
        ExpressionAttributeNames={"#reminders": AppointmentAttrs.REMINDERS},
        ExpressionAttributeValues={
            ":entry": [
                {
                    ReminderEntry.AT: sent_at,
                    ReminderEntry.CHANNEL: ReminderChannel.EMAIL.value,
                    ReminderEntry.OUTCOME: outcome.value,
                }
            ],
            ":empty": [],
        },
    )


def _scheduled_starting_within(
    clinic_id: str, window_start: datetime, window_end: datetime
) -> list[dict[str, Any]]:
    """Whole `scheduled` appointment items starting in `[window_start, window_end]`.

    The `by-start-time` query `scheduling._booked_spans` runs, but returning
    whole items rather than `(start, end)` spans: the scan needs the
    patient reference and the service, not just the occupied time.
    """
    # Lazy, mirroring `dynamo._dynamodb_resource`: importing this module
    # must not require the AWS SDK.
    from boto3.dynamodb.conditions import Key  # noqa: PLC0415

    table = appointments_table()
    query: dict[str, Any] = {
        "IndexName": APPOINTMENTS_BY_START_TIME_INDEX,
        "KeyConditionExpression": Key(CLINIC_ID).eq(clinic_id)
        & Key(STARTS_AT).between(to_iso8601(window_start), to_iso8601(window_end)),
    }
    items: list[dict[str, Any]] = []
    while True:
        response = table.query(**query)
        items.extend(
            item
            for item in response.get("Items", [])
            if str(item.get(AppointmentAttrs.STATUS, ""))
            == AppointmentStatus.SCHEDULED.value
        )
        next_key = response.get("LastEvaluatedKey")
        if not next_key:
            return items
        query["ExclusiveStartKey"] = next_key
