"""Escalations: the record that a human has to look at something.

The tool layer's last resort, and the only one of the four tables whose
items exist to be *read by a person* rather than acted on by the agent.
Both paths in `project-overview.md` end here -- a live voice session that
cannot safely resolve a request, and the daily background scan that hits a
case needing a judgment call -- and both land in one queue, which is why
`source` is stored rather than inferred from whichever process wrote the
row.

**Creating one must not fail for a reason of its own.** An escalation is
what happens when everything else already went wrong, so this module reads
nothing it does not have to: `patient_id` and `appointment_id` are stored
as given, unverified. Checking that they resolve would mean a stale
reference could stop the escalation being recorded at all, and a
mis-referenced escalation a human can still read beats a correct one that
was never written. The staff notification email below is held to the same
rule: it is sent after the write, best-effort, and a rejected send (or an
unconfigured one) loses nothing but the email itself.

**Resolving one is not idempotent, deliberately.** Marking an
already-resolved escalation resolved again raises `ConflictError` rather
than quietly succeeding, for the reason `reschedule_appointment` refuses a
move to the time an appointment already has: two staff working the same
queue need to hear that the other has handled it, and a silent success
tells them the opposite.

The tenant boundary needs no check beyond `require_clinic_id` here.
`Escalations` is keyed on `(clinic_id, escalation_id)` and `by-created-at`
is partitioned on `clinic_id`, so another clinic's escalation is not
reachable by key or by query -- it is a `NotFoundError`, indistinguishable
from one that does not exist (`errors.NotFoundError`, `architecture.md` ->
Invariants #1). That is the whole ownership story, unlike
`tools.appointments`, because nothing here belongs to a *patient*: an
escalation is the clinic's own record, and only authenticated staff read
or resolve one.
"""

from __future__ import annotations

import os
from typing import Any

from .dynamo import escalations_table
from .errors import ConflictError, NotFoundError
from .schema import (
    CLINIC_ID,
    ESCALATION_ID_PREFIX,
    ESCALATIONS_BY_CREATED_AT_INDEX,
    EscalationAttrs,
    EscalationSource,
    EscalationStatus,
    new_id,
    utc_now_iso,
)
from .validation import (
    require_bounded_int,
    require_clinic_id,
    require_enum,
    require_identifier,
    require_text,
)

# How many open escalations one `list_open_escalations` call returns.
# A cap rather than pagination: the dashboard's queue is a card list a
# human scrolls (`ui-context.md` -> Layout Patterns) and nothing there
# reads a page cursor. The maximum exists for the reason
# `check_availability`'s `days` cap does -- it is what stops a caller that
# guessed a large number from walking a whole partition.
DEFAULT_ESCALATION_LIMIT = 50
MAX_ESCALATION_LIMIT = 100

# The staff notification email's two addresses. Both must be set or no
# email is sent -- silently, unlike `tools.automation`'s sender env,
# because here an unconfigured deployment must still record escalations
# (`project-overview.md` wants email *and* dashboard, and the dashboard
# half must not depend on the email half). SES sandbox requires every
# recipient verified, so the demo sends to the same verified address it
# sends from (`architecture.md` -> Stack, "Email Escalation").
ESCALATION_SENDER_ENV: str = "CLINICPILOT_ESCALATION_SENDER_EMAIL"
ESCALATION_RECIPIENT_ENV: str = "CLINICPILOT_ESCALATION_RECIPIENT_EMAIL"

# A subject a person scans in an inbox: enough of the reason to recognise
# the case, never a wall of text (the full reason is in the body).
_SUBJECT_REASON_LIMIT = 80


def create_escalation(
    clinic_id: str,
    reason: str,
    patient_id: str | None = None,
    appointment_id: str | None = None,
    *,
    source: str | EscalationSource = EscalationSource.VOICE,
) -> dict[str, Any]:
    """Flag something for a member of clinic staff to deal with.

    Use this when a request cannot be safely completed with the tools
    available -- a billing or refund question, a complaint, a clinical
    question, or anything the clinic's own rules do not cover. It is not a
    fallback for a tool that failed in a way the patient can answer: a time
    that has been taken, or a name that does not match the number, is
    something to ask about rather than to escalate.

    The escalation is recorded immediately and staff pick it up from the
    dashboard, so tell the patient that a member of staff will follow up --
    never that the thing they asked for has been done. When the SES
    addresses are configured, a notification email follows the write,
    best-effort: a rejected or unconfigured send loses the email and
    nothing else.

    Args:
        clinic_id: The clinic the caller is talking to. Required; never
            inferred or defaulted.
        reason: What needs a human, in plain words. Free text with no
            machine reader: a person reads it in the dashboard queue or in
            an email, so write what they need in order to act -- what the
            patient asked for and what stopped it -- not an error code.
        patient_id: Optional. The patient this is about, when one has been
            identified in the call. Pass it whenever it is known: it is how
            staff reach the person back.
        appointment_id: Optional. The appointment this is about, when the
            escalation concerns one.

    Returns:
        The stored `Escalations` item: ``clinic_id``, ``escalation_id``,
        ``status`` (``open``), ``source``, ``reason``, ``created_at``, and
        each back-reference that was given. Confirm to the patient that
        staff will be in touch; the id is for the clinic, not for them.

    Raises:
        ValidationError: If `clinic_id` or `reason` is missing or
            malformed, or if a back-reference is given but is not an id.
    """
    # Tenant boundary first, before any write (`code-standards.md` -> Python).
    clinic_id = require_clinic_id(clinic_id)
    reason_text = require_text(reason, "reason")
    # Not a value a model chooses, exactly like `RescheduleActor`: it
    # records which agent path raised this, and the live agent and the
    # background job each know their own.
    raised_by = require_enum(source, EscalationSource, "source")
    about_patient = (
        None
        if patient_id is None
        else require_identifier(patient_id, EscalationAttrs.PATIENT_ID)
    )
    about_appointment = (
        None
        if appointment_id is None
        else require_identifier(appointment_id, EscalationAttrs.APPOINTMENT_ID)
    )

    from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

    item: dict[str, Any] = {
        EscalationAttrs.CLINIC_ID: clinic_id,
        EscalationAttrs.ESCALATION_ID: new_id(ESCALATION_ID_PREFIX),
        EscalationAttrs.STATUS: EscalationStatus.OPEN.value,
        EscalationAttrs.SOURCE: raised_by.value,
        EscalationAttrs.REASON: reason_text,
        EscalationAttrs.CREATED_AT: utc_now_iso(),
    }
    # Omitted rather than stored as null, as `_create_patient` omits a
    # missing email: an absent attribute is what "not about a particular
    # patient" looks like to the dashboard.
    if about_patient is not None:
        item[EscalationAttrs.PATIENT_ID] = about_patient
    if about_appointment is not None:
        item[EscalationAttrs.APPOINTMENT_ID] = about_appointment

    escalations_table().put_item(
        Item=item,
        # Guards an id collision, not a concurrent writer: the id is a
        # fresh uuid4, so this can only fire on a genuine bug.
        ConditionExpression=Attr(EscalationAttrs.ESCALATION_ID).not_exists(),
    )
    # Only now that the record exists: the email advertises a queue
    # card, it is not the record. Every way this can go wrong -- no
    # addresses configured, SES rejecting the send, the SDK raising --
    # costs the email and nothing else.
    _notify_staff(item)
    return item


def _notification_addresses() -> tuple[str, str] | None:
    """The SES sender and recipient for staff notifications, or None.

    Both halves must be present: half an address pair is not a
    configured email, it is a misconfiguration that would send from or
    to nowhere. Whitespace counts as unset, as everywhere else in this
    layer -- that is how a shell profile exports nothing.
    """
    sender = os.environ.get(ESCALATION_SENDER_ENV, "").strip()
    recipient = os.environ.get(ESCALATION_RECIPIENT_ENV, "").strip()
    if not sender or not recipient:
        return None
    return sender, recipient


def _send_staff_email(item: dict[str, Any]) -> bool:
    """Send one staff notification email via SES.

    Returns:
        `True` if SES accepted the send, `False` if it did not. Not
        raised as an exception -- the caller treats both the same way,
        which is the whole point of the function's existence.
    """
    # Lazy, mirroring `dynamo._dynamodb_resource`: importing this module
    # must not require the AWS SDK.
    import boto3  # noqa: PLC0415
    from botocore.exceptions import BotoCoreError, ClientError  # noqa: PLC0415

    addresses = _notification_addresses()
    if addresses is None:
        return False
    sender, recipient = addresses

    reason = str(item[EscalationAttrs.REASON])
    subject_reason = (
        reason if len(reason) <= _SUBJECT_REASON_LIMIT
        else f"{reason[:_SUBJECT_REASON_LIMIT - 1]}…"
    )
    lines = [
        "A new escalation needs a staff decision.",
        "",
        f"Clinic: {item[EscalationAttrs.CLINIC_ID]}",
        f"Reason: {reason}",
        f"Raised by: {item[EscalationAttrs.SOURCE]}",
        f"Escalation id: {item[EscalationAttrs.ESCALATION_ID]}",
    ]
    # Omitted rather than written as "None": the same rule the item
    # itself follows for its back-references.
    if EscalationAttrs.PATIENT_ID in item:
        lines.append(f"Patient: {item[EscalationAttrs.PATIENT_ID]}")
    if EscalationAttrs.APPOINTMENT_ID in item:
        lines.append(f"Appointment: {item[EscalationAttrs.APPOINTMENT_ID]}")
    lines += [
        "",
        "Open the staff dashboard to resolve it.",
    ]

    try:
        boto3.client("ses").send_email(
            Source=sender,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {
                    "Data": (
                        f"Escalation at {item[EscalationAttrs.CLINIC_ID]}: "
                        f"{subject_reason}"
                    )
                },
                "Body": {"Text": {"Data": "\n".join(lines)}},
            },
        )
        return True
    except (ClientError, BotoCoreError):
        return False


def _notify_staff(item: dict[str, Any]) -> None:
    """Best-effort: tell staff an escalation exists, whatever happens.

    The seam the tests stub. A send that raises is swallowed here, not
    in `create_escalation` -- recording the escalation is the critical
    act and this is the decoration on it.
    """
    if _notification_addresses() is None:
        return
    try:
        _send_staff_email(item)
    except Exception:  # noqa: BLE001
        # Deliberately broad: no failure mode of a notification may
        # escape into the path that records the escalation.
        return


def list_open_escalations(clinic_id: str, limit: object = None) -> list[dict[str, Any]]:
    """One clinic's unresolved escalations, newest first.

    The dashboard's escalation queue (`ui-context.md` -> Layout Patterns),
    and the read a staff member makes to decide what to work on.

    Args:
        clinic_id: The clinic whose queue to read. Required; the index's
            own partition key, so the query cannot reach another tenant.
        limit: Optional. How many to return at most, up to
            `MAX_ESCALATION_LIMIT`; defaults to `DEFAULT_ESCALATION_LIMIT`.

    Returns:
        Whole `Escalations` items whose `status` is `open`, newest
        `created_at` first, ties broken by `escalation_id` so two identical
        calls agree. Empty when the clinic has nothing outstanding. A
        result exactly `limit` long may have more behind it -- there is no
        page cursor, because no screen in `ui-context.md` reads one.

    Raises:
        ValidationError: If `clinic_id` is missing, or `limit` is not a
            whole number in range.
    """
    clinic_id = require_clinic_id(clinic_id)
    wanted = require_bounded_int(
        limit,
        "limit",
        minimum=1,
        maximum=MAX_ESCALATION_LIMIT,
        default=DEFAULT_ESCALATION_LIMIT,
    )

    # Lazy, mirroring `dynamo._dynamodb_resource`: importing this module
    # must not require the AWS SDK.
    from boto3.dynamodb.conditions import Key  # noqa: PLC0415

    table = escalations_table()
    query: dict[str, Any] = {
        "IndexName": ESCALATIONS_BY_CREATED_AT_INDEX,
        "KeyConditionExpression": Key(CLINIC_ID).eq(clinic_id),
        # `created_at` is the index's sort key, so newest-first is that
        # index read backwards rather than a sort over the partition.
        "ScanIndexForward": False,
    }
    open_items: list[dict[str, Any]] = []
    while True:
        response = table.query(**query)
        # Status is filtered here rather than by a `FilterExpression` --
        # the choice `architecture.md` -> Storage Model records for this
        # index: the queue is small enough that filtering beats maintaining
        # a composite status key, and the vocabulary stays one edit.
        open_items.extend(
            item
            for item in response.get("Items", [])
            if str(item.get(EscalationAttrs.STATUS, "")) == EscalationStatus.OPEN.value
        )
        next_key = response.get("LastEvaluatedKey")
        # The cap is applied here, after the status filter, and is not
        # passed to DynamoDB as `Limit`: that counts items *scanned*, so a
        # clinic whose newest 50 escalations are all resolved would come
        # back empty while its queue was full.
        if not next_key or len(open_items) >= wanted:
            break
        query["ExclusiveStartKey"] = next_key

    # The index already returns newest first; this only fixes the order of
    # items sharing one `created_at` second, which DynamoDB leaves
    # undefined -- and "which escalation is at the top?" must not vary
    # between two identical calls.
    open_items.sort(
        key=lambda item: (
            str(item.get(EscalationAttrs.CREATED_AT, "")),
            str(item.get(EscalationAttrs.ESCALATION_ID, "")),
        ),
        reverse=True,
    )
    return open_items[:wanted]


def get_escalation(clinic_id: str, escalation_id: str) -> dict[str, Any]:
    """Fetch one escalation by key.

    Its own function because two readers hold an id without holding the
    item: the dashboard's escalation detail modal (`ui-context.md` ->
    Layout Patterns), and a staff member arriving from the SES escalation
    email. `resolve_escalation` reads through it too, so "which escalation
    is that, and does it exist?" is answered once.

    Args:
        clinic_id: The clinic the escalation belongs to. Part of the item's
            key, so this cannot read across tenants.
        escalation_id: Which escalation.

    Returns:
        The raw `Escalations` item.

    Raises:
        ValidationError: If either id is missing or malformed.
        NotFoundError: If this clinic has no escalation with that id. An id
            belonging to *another* clinic reaches this same error, and must
            stay indistinguishable from one that never existed.
    """
    clinic_id = require_clinic_id(clinic_id)
    target_id = require_identifier(escalation_id, EscalationAttrs.ESCALATION_ID)

    response = escalations_table().get_item(
        Key={
            EscalationAttrs.CLINIC_ID: clinic_id,
            EscalationAttrs.ESCALATION_ID: target_id,
        }
    )
    item = response.get("Item")
    if not item:
        raise NotFoundError(
            f"No escalation found with escalation_id {target_id!r} at this clinic."
        )
    return item


def resolve_escalation(clinic_id: str, escalation_id: str) -> dict[str, Any]:
    """Mark one escalation as handled, so it leaves the queue.

    The dashboard's "Mark Resolved" action. Nothing is deleted: the item
    stays as the record of what the agent flagged and when a human dealt
    with it, which is what `project-overview.md` Goal 3 is demonstrated by.

    Args:
        clinic_id: The clinic the escalation belongs to. Required; part of
            the item's key, so an id from another clinic does not exist
            here.
        escalation_id: Which escalation, as `create_escalation` returned it
            and as `list_open_escalations` reports it.

    Returns:
        The escalation as it now stands: the stored item with `status`
        `resolved` and a `resolved_at` stamp.

    Raises:
        ValidationError: If either id is missing or malformed.
        NotFoundError: If this clinic has no escalation with that id.
        ConflictError: If it was already resolved -- including by someone
            else between this call's read and its write. Not a silent
            success: two staff working one queue need to know the other got
            there first.
    """
    # Tenant boundary first, before any read (`code-standards.md` -> Python).
    clinic_id = require_clinic_id(clinic_id)
    target_id = require_identifier(escalation_id, EscalationAttrs.ESCALATION_ID)

    escalation = get_escalation(clinic_id, target_id)
    if str(escalation.get(EscalationAttrs.STATUS, "")) != EscalationStatus.OPEN.value:
        raise ConflictError(_already_resolved(escalation))

    from botocore.exceptions import ClientError  # noqa: PLC0415

    now = utc_now_iso()
    try:
        escalations_table().update_item(
            Key={
                EscalationAttrs.CLINIC_ID: clinic_id,
                EscalationAttrs.ESCALATION_ID: target_id,
            },
            # `status` is a DynamoDB reserved word, so attributes go through
            # `#name` aliases rather than inline, as in
            # `appointments._write_change`.
            UpdateExpression="SET #status = :resolved, #resolved_at = :now",
            ExpressionAttributeNames={
                "#status": EscalationAttrs.STATUS,
                "#resolved_at": EscalationAttrs.RESOLVED_AT,
            },
            ExpressionAttributeValues={
                ":resolved": EscalationStatus.RESOLVED.value,
                ":now": now,
                ":open": EscalationStatus.OPEN.value,
            },
            # Re-checked at write time: the read above cannot see another
            # staff member resolving it a moment later. This row already
            # exists, so DynamoDB can settle that race -- unlike the slot
            # contention `booking` documents.
            ConditionExpression="#status = :open",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        raise ConflictError(
            f"Escalation {target_id} was resolved by someone else while this "
            "one was being handled."
        ) from exc

    return {
        **escalation,
        EscalationAttrs.STATUS: EscalationStatus.RESOLVED.value,
        EscalationAttrs.RESOLVED_AT: now,
    }


def _already_resolved(escalation: dict[str, Any]) -> str:
    """The message for an escalation somebody has already dealt with."""
    resolved_at = escalation.get(EscalationAttrs.RESOLVED_AT)
    when = f" at {resolved_at}" if isinstance(resolved_at, str) else ""
    return (
        f"Escalation {escalation.get(EscalationAttrs.ESCALATION_ID)} was already "
        f"resolved{when}. Nothing was changed."
    )
