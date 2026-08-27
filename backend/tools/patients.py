"""Patient records, and the phone lookup a voice caller arrives by.

A caller identifies themselves by *saying a phone number*, not by an id
(`architecture.md` -> Storage Model, `by-phone`), so every patient-facing
write starts here: this module turns a spoken number into a `patient_id`,
creating the record the first time. `book_appointment` enters through
`lookup_or_create_patient` and the reschedule and cancel tools through the
read-only `find_patient`, rather than each deciding for themselves who is
calling.

**The identity rule**: a caller is the same person as an existing record
when the *phone number and the name both match*. Phone alone is not
enough -- a household shares a number, and treating a spouse's booking as
the first-registered patient's would put the wrong name on the
appointment and on the reminder email, silently. Name alone is not enough
either, since names are not unique. The cost of the pair is a duplicate
record when the same person is heard as "Dave" one week and "David" the
next: visible on the staff dashboard, harmless to the booking itself, and
the failure worth having in that direction. Confirmed with the user
rather than defaulted (`ai-workflow-rules.md` -> Handling Missing
Requirements); recorded in `architecture.md` -> Storage Model.

Names are compared through `_name_key`, not raw: the value arrives from
speech, so case and spacing carry no information and must not create a
second record on their own.
"""

from __future__ import annotations

from typing import Any

from .dynamo import patients_table
from .errors import ValidationError
from .schema import (
    CLINIC_ID,
    PATIENT_ID_PREFIX,
    PATIENTS_BY_PHONE_INDEX,
    PHONE,
    PatientAttrs,
    new_id,
    utc_now_iso,
)
from .validation import (
    MAX_IDENTIFIER_LENGTH,
    normalise_email,
    normalise_phone,
    require_clinic_id,
    require_text,
)


def find_patients_by_phone(clinic_id: str, phone: str) -> list[dict[str, Any]]:
    """Every patient at one clinic registered against one phone number.

    A list rather than a single item because a phone number is not a key:
    `by-phone` is `clinic_id` / `phone`, so a household sharing a number
    is several items under one sort key. Deciding *which* of them is
    calling is `find_patient`'s job, not this function's.

    Args:
        clinic_id: The clinic the caller is talking to. The index's own
            partition key, so the query cannot reach another tenant
            (`architecture.md` -> Invariants #1).
        phone: The caller's number, in any spoken or written form.

    Returns:
        Matching `Patients` items, ordered oldest-registered first so the
        result does not depend on DynamoDB's ordering of items that share
        a sort key. Empty if the number is unknown at this clinic.

    Raises:
        ValidationError: If `clinic_id` is missing, or `phone` is missing
            or has an implausible number of digits.
    """
    clinic_id = require_clinic_id(clinic_id)
    normalised = normalise_phone(phone, "phone")

    # Lazy, mirroring `dynamo._dynamodb_resource`: importing this module
    # must not require the AWS SDK.
    from boto3.dynamodb.conditions import Key  # noqa: PLC0415

    table = patients_table()
    query: dict[str, Any] = {
        "IndexName": PATIENTS_BY_PHONE_INDEX,
        "KeyConditionExpression": Key(CLINIC_ID).eq(clinic_id)
        & Key(PHONE).eq(normalised),
    }
    items: list[dict[str, Any]] = []
    while True:
        response = table.query(**query)
        items.extend(response.get("Items", []))
        next_key = response.get("LastEvaluatedKey")
        if not next_key:
            break
        query["ExclusiveStartKey"] = next_key

    # Items sharing a sort key come back in no defined order, and "which
    # record did we match?" must not vary between two identical calls.
    return sorted(
        items,
        key=lambda item: (
            str(item.get(PatientAttrs.CREATED_AT, "")),
            str(item.get(PatientAttrs.PATIENT_ID, "")),
        ),
    )


def lookup_or_create_patient(
    clinic_id: str, phone: str, name: str, email: str | None = None
) -> tuple[dict[str, Any], bool]:
    """Resolve a caller to a `Patients` item, registering them if new.

    Matches on phone *and* name together -- see this module's docstring for
    why neither alone is enough. An existing record is returned as it
    stands: this function does not rewrite a patient's stored details, so a
    booking can never quietly change what the clinic holds about someone.
    The one exception is `email`, filled in when the record has none, since
    that is adding a fact rather than overwriting one -- and without it the
    background job has no address to send that patient's reminder to.

    Args:
        clinic_id: The clinic the caller is talking to. Required.
        phone: The caller's number. Normalised before storage and lookup
            (`validation.normalise_phone`), so a number spoken as
            "555 123 4567" finds a record seeded as "+15551234567".
        name: The caller's name, as spoken.
        email: Optional contact address for reminders.

    Returns:
        `(patient_item, created)` -- the stored item, and whether this call
        is what created it. `created` is what lets a caller greet a
        returning patient differently from a new one.

    Raises:
        ValidationError: If `clinic_id`, `phone`, or `name` is missing or
            malformed, or if `email` is given and is not an address.
    """
    clinic_id = require_clinic_id(clinic_id)
    normalised_phone = normalise_phone(phone, "phone")
    cleaned_name = require_text(name, "name", max_length=MAX_IDENTIFIER_LENGTH)
    cleaned_email = None if email is None else normalise_email(email, "email")

    existing = find_patient(clinic_id, normalised_phone, cleaned_name)
    if existing is not None:
        if cleaned_email is not None:
            existing = _fill_missing_email(existing, cleaned_email)
        return existing, False

    return _create_patient(
        clinic_id, normalised_phone, cleaned_name, cleaned_email
    ), True


def find_patient(clinic_id: str, phone: str, name: str) -> dict[str, Any] | None:
    """The one patient a phone number and a name together identify, if any.

    This module's identity rule, and the *only* place it is applied --
    `lookup_or_create_patient` decides whether to register a caller by
    asking this first, and the reschedule and cancel tools decide whose
    appointments they are allowed to touch by asking the same question.
    A second implementation of "is this the same person?" is how a
    household's two patients start swapping appointments.

    Read-only, unlike `lookup_or_create_patient`: a caller asking about an
    existing appointment must not leave a new patient record behind if the
    number turns out to be unknown.

    Args:
        clinic_id: The clinic the caller is talking to. Required.
        phone: The caller's number, in any spoken form.
        name: The caller's name, as spoken. Compared through `_name_key`,
            so case and spacing do not matter.

    Returns:
        The matching `Patients` item, or `None` if this clinic has no
        record with that number *and* that name. The first match in
        registration order if a clinic somehow holds two -- the pair is
        not a key, so nothing stops a duplicate existing.

    Raises:
        ValidationError: If `clinic_id`, `phone`, or `name` is missing or
            malformed.
    """
    clinic_id = require_clinic_id(clinic_id)
    normalised_phone = normalise_phone(phone, "phone")
    wanted = _name_key(require_text(name, "name", max_length=MAX_IDENTIFIER_LENGTH))
    for candidate in find_patients_by_phone(clinic_id, normalised_phone):
        stored = candidate.get(PatientAttrs.NAME)
        if isinstance(stored, str) and _name_key(stored) == wanted:
            return candidate
    return None


def _create_patient(
    clinic_id: str, phone: str, name: str, email: str | None
) -> dict[str, Any]:
    """Write a new `Patients` item and return it, without re-reading it."""
    from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

    now = utc_now_iso()
    item: dict[str, Any] = {
        PatientAttrs.CLINIC_ID: clinic_id,
        PatientAttrs.PATIENT_ID: new_id(PATIENT_ID_PREFIX),
        PatientAttrs.NAME: name,
        PatientAttrs.PHONE: phone,
        PatientAttrs.CREATED_AT: now,
        PatientAttrs.UPDATED_AT: now,
    }
    # Omitted rather than stored as null: an absent attribute is what the
    # background job's "has no email" check reads.
    if email is not None:
        item[PatientAttrs.EMAIL] = email
    patients_table().put_item(
        Item=item,
        # Guards an id collision, not a concurrent caller: the id is a
        # fresh uuid4, so this can only fire on a genuine bug.
        ConditionExpression=Attr(PatientAttrs.PATIENT_ID).not_exists(),
    )
    return item


def _fill_missing_email(patient: dict[str, Any], email: str) -> dict[str, Any]:
    """Add a contact address to a patient who has none, leaving one that has.

    Additive on purpose: a patient who gives an address while booking
    becomes reachable by the reminder job, but a caller who mis-speaks an
    address cannot overwrite the one the clinic already holds.
    """
    existing = patient.get(PatientAttrs.EMAIL)
    if isinstance(existing, str) and existing.strip():
        return patient

    from boto3.dynamodb.conditions import Attr  # noqa: PLC0415

    now = utc_now_iso()
    patients_table().update_item(
        Key={
            PatientAttrs.CLINIC_ID: patient[PatientAttrs.CLINIC_ID],
            PatientAttrs.PATIENT_ID: patient[PatientAttrs.PATIENT_ID],
        },
        UpdateExpression=(
            f"SET #email = :email, #updated_at = :updated_at"
        ),
        ExpressionAttributeNames={
            "#email": PatientAttrs.EMAIL,
            "#updated_at": PatientAttrs.UPDATED_AT,
        },
        ExpressionAttributeValues={":email": email, ":updated_at": now},
        # Re-checked at write time: another session may have filled it in
        # between the read above and here.
        ConditionExpression=Attr(PatientAttrs.EMAIL).not_exists(),
    )
    return {**patient, PatientAttrs.EMAIL: email, PatientAttrs.UPDATED_AT: now}


def _name_key(name: str) -> str:
    """Reduce a spoken name to the form two records are compared on.

    Case-insensitive and whitespace-collapsed, and nothing further: this
    decides whether a caller gets an existing record or a new one, so it
    must not fold together two people the clinic considers distinct.
    """
    return " ".join(name.split()).casefold()


def patient_summary(patient: dict[str, Any], created: bool) -> dict[str, Any]:
    """The patient fields a tool hands back to the agent, and nothing else.

    A tool result is read by a model and spoken to whoever is on the call,
    so it carries who the appointment is for -- never the record's
    timestamps, and never a second patient's details.

    Args:
        patient: A `Patients` item.
        created: Whether this session registered them, from
            `lookup_or_create_patient`.

    Returns:
        ``{"patient_id", "name", "phone", "is_new"}``.

    Raises:
        ValidationError: If the item carries no `patient_id`, which would
            mean a caller built one by hand instead of through this module.
    """
    patient_id = patient.get(PatientAttrs.PATIENT_ID)
    if not isinstance(patient_id, str) or not patient_id.strip():
        raise ValidationError("patient item has no patient_id.")
    return {
        PatientAttrs.PATIENT_ID: patient_id,
        PatientAttrs.NAME: patient.get(PatientAttrs.NAME),
        PatientAttrs.PHONE: patient.get(PatientAttrs.PHONE),
        "is_new": created,
    }
