"""Tests for the phone lookup a voice caller arrives by.

The identity rule under test is phone *and* name together
(`architecture.md` -> Storage Model, "Patient identity"), so the cases that
matter are the two a phone-only rule would get wrong: the same person
calling back must be reused, and a second household member on the same
number must not be mistaken for the first.

DynamoDB is replaced by a fake, as in `test_scheduling.py`: the module's
only contact with it is `patients_table()`.
"""

from __future__ import annotations

from typing import Any

import pytest

from tools import patients
from tools.errors import ValidationError

CLINIC = "clinic-dental"
OTHER_CLINIC = "clinic-cosmetic"
# The stored form: digits only, as `normalise_phone` writes it and as a
# seed script (which calls the same function) would store it.
PHONE = "15551234567"


class FakePatientsTable:
    """`query` over the by-phone index, plus recording `put_item`/`update_item`.

    Queries are answered by filtering the stored items the way the real
    index would -- on `clinic_id` and `phone` equality -- so a test cannot
    pass by the fake being more forgiving than DynamoDB.
    """

    def __init__(self, *items: dict[str, Any], pages: int = 1) -> None:
        self.items = [dict(item) for item in items]
        self.pages = pages
        self.queries: list[dict[str, Any]] = []
        self.puts: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []

    def _matches(self, clinic_id: str, phone: str) -> list[dict[str, Any]]:
        return [
            item
            for item in self.items
            if item.get("clinic_id") == clinic_id and item.get("phone") == phone
        ]

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        expression = kwargs["KeyConditionExpression"].get_expression()
        clinic_id, phone = (
            sub.get_expression()["values"][1] for sub in expression["values"]
        )
        matched = self._matches(clinic_id, phone)
        # Split the result across `pages` responses so the pagination loop
        # is exercised rather than assumed.
        start = kwargs.get("ExclusiveStartKey", {}).get("offset", 0)
        size = max(1, -(-len(matched) // self.pages)) if matched else len(matched)
        page = matched[start : start + size]
        response: dict[str, Any] = {"Items": page}
        if start + size < len(matched):
            response["LastEvaluatedKey"] = {"offset": start + size}
        return response

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        self.items.append(dict(kwargs["Item"]))
        return {}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.updates.append(kwargs)
        return {}


def stored_patient(
    name: str,
    phone: str = PHONE,
    clinic_id: str = CLINIC,
    patient_id: str = "pat_existing",
    created_at: str = "2026-01-01T00:00:00Z",
    email: str | None = None,
) -> dict[str, Any]:
    item = {
        "clinic_id": clinic_id,
        "patient_id": patient_id,
        "name": name,
        "phone": phone,
        "created_at": created_at,
        "updated_at": created_at,
    }
    if email is not None:
        item["email"] = email
    return item


@pytest.fixture
def table(monkeypatch: pytest.MonkeyPatch):
    def install(*items: dict[str, Any], pages: int = 1) -> FakePatientsTable:
        fake = FakePatientsTable(*items, pages=pages)
        monkeypatch.setattr(patients, "patients_table", lambda: fake)
        return fake

    return install


# --------------------------------------------------------------------------
# The tenant boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clinic_id", ["", "   ", None])
def test_blank_clinic_id_fails_before_any_read(clinic_id, table) -> None:
    fake = table(stored_patient("Dana Okafor"))
    with pytest.raises(ValidationError):
        patients.find_patients_by_phone(clinic_id, PHONE)
    with pytest.raises(ValidationError):
        patients.lookup_or_create_patient(clinic_id, PHONE, "Dana Okafor")
    assert fake.queries == []
    assert fake.puts == []


def test_lookup_is_scoped_to_the_requested_clinic(table) -> None:
    """Another clinic's identical phone number is not this clinic's patient."""
    fake = table(stored_patient("Dana Okafor", clinic_id=OTHER_CLINIC))
    assert patients.find_patients_by_phone(CLINIC, PHONE) == []

    expression = fake.queries[0]["KeyConditionExpression"].get_expression()
    assert expression["values"][0].get_expression()["values"][1] == CLINIC
    assert fake.queries[0]["IndexName"] == "by-phone"


def test_a_new_record_is_created_under_the_calling_clinic(table) -> None:
    fake = table(stored_patient("Dana Okafor", clinic_id=OTHER_CLINIC))
    patient, created = patients.lookup_or_create_patient(CLINIC, PHONE, "Dana Okafor")
    assert created is True
    assert patient["clinic_id"] == CLINIC
    assert fake.puts[0]["Item"]["clinic_id"] == CLINIC


# --------------------------------------------------------------------------
# The identity rule: phone AND name
# --------------------------------------------------------------------------


def test_same_phone_and_name_reuses_the_record(table) -> None:
    fake = table(stored_patient("Dana Okafor"))
    patient, created = patients.lookup_or_create_patient(CLINIC, PHONE, "Dana Okafor")
    assert created is False
    assert patient["patient_id"] == "pat_existing"
    assert fake.puts == []


@pytest.mark.parametrize("spoken", ["dana okafor", "DANA OKAFOR", "  Dana   Okafor  "])
def test_name_match_ignores_case_and_spacing(spoken, table) -> None:
    """The name arrives from speech; casing and spacing carry no information."""
    fake = table(stored_patient("Dana Okafor"))
    _, created = patients.lookup_or_create_patient(CLINIC, PHONE, spoken)
    assert created is False
    assert fake.puts == []


def test_a_second_household_member_gets_their_own_record(table) -> None:
    """The case a phone-only rule gets silently wrong."""
    fake = table(stored_patient("Dana Okafor"))
    patient, created = patients.lookup_or_create_patient(CLINIC, PHONE, "Sam Okafor")
    assert created is True
    assert patient["patient_id"] != "pat_existing"
    assert patient["name"] == "Sam Okafor"
    # The first record is untouched -- not renamed, not overwritten.
    assert fake.updates == []
    assert fake.items[0]["name"] == "Dana Okafor"


def test_the_right_household_member_is_matched(table) -> None:
    table(
        stored_patient("Dana Okafor", patient_id="pat_dana"),
        stored_patient("Sam Okafor", patient_id="pat_sam", created_at="2026-02-02T00:00:00Z"),
    )
    patient, created = patients.lookup_or_create_patient(CLINIC, PHONE, "Sam Okafor")
    assert created is False
    assert patient["patient_id"] == "pat_sam"


@pytest.mark.parametrize(
    "spoken", ["+1 (555) 123-4567", "1-555-123-4567", "1 555 123 4567"]
)
def test_a_spoken_number_finds_a_seeded_one(spoken, table) -> None:
    """Every way of saying one number has to reach one record.

    The ``+`` case is the regression: while `normalise_phone` preserved it,
    a caller who said "plus one" got a second patient record instead of
    their own.
    """
    table(stored_patient("Dana Okafor"))
    _, created = patients.lookup_or_create_patient(CLINIC, spoken, "Dana Okafor")
    assert created is False


def test_matching_is_deterministic_across_identical_calls(table) -> None:
    """Items sharing a sort key come back in no defined order; ours must not."""
    fake = table(
        stored_patient("Dana Okafor", patient_id="pat_b", created_at="2026-03-01T00:00:00Z"),
        stored_patient("Dana Okafor", patient_id="pat_a", created_at="2026-01-01T00:00:00Z"),
    )
    first, _ = patients.lookup_or_create_patient(CLINIC, PHONE, "Dana Okafor")
    fake.items.reverse()
    second, _ = patients.lookup_or_create_patient(CLINIC, PHONE, "Dana Okafor")
    assert first["patient_id"] == second["patient_id"] == "pat_a"


def test_pagination_is_followed(table) -> None:
    """A match on the second page is still a match."""
    fake = table(
        stored_patient("Dana Okafor", patient_id="pat_dana"),
        stored_patient("Sam Okafor", patient_id="pat_sam"),
        pages=2,
    )
    patient, created = patients.lookup_or_create_patient(CLINIC, PHONE, "Sam Okafor")
    assert created is False
    assert patient["patient_id"] == "pat_sam"
    assert len(fake.queries) == 2


# --------------------------------------------------------------------------
# What a new record contains
# --------------------------------------------------------------------------


def test_new_patient_item_shape(table) -> None:
    fake = table()
    patient, created = patients.lookup_or_create_patient(
        CLINIC, "555 123 4567", "  Dana Okafor  ", email="dana@example.com"
    )
    assert created is True
    item = fake.puts[0]["Item"]
    assert item == patient
    assert item["clinic_id"] == CLINIC
    assert item["patient_id"].startswith("pat_")
    assert item["name"] == "Dana Okafor"
    # Stored normalised, because the index does an equality match on it.
    assert item["phone"] == "5551234567"
    assert item["email"] == "dana@example.com"
    assert item["created_at"] == item["updated_at"]
    assert item["created_at"].endswith("Z")


def test_email_is_omitted_rather_than_stored_null(table) -> None:
    fake = table()
    patients.lookup_or_create_patient(CLINIC, PHONE, "Dana Okafor")
    assert "email" not in fake.puts[0]["Item"]


def test_creation_is_conditional_on_the_id_being_free(table) -> None:
    fake = table()
    patients.lookup_or_create_patient(CLINIC, PHONE, "Dana Okafor")
    assert "ConditionExpression" in fake.puts[0]


@pytest.mark.parametrize(
    "phone", ["", "   ", None, "12345", "1234567890123456789", "no digits here"]
)
def test_implausible_phone_numbers_are_refused(phone, table) -> None:
    fake = table()
    with pytest.raises(ValidationError):
        patients.lookup_or_create_patient(CLINIC, phone, "Dana Okafor")
    assert fake.puts == []


@pytest.mark.parametrize("name", ["", "   ", None, "x" * 129])
def test_missing_or_oversized_names_are_refused(name, table) -> None:
    fake = table()
    with pytest.raises(ValidationError):
        patients.lookup_or_create_patient(CLINIC, PHONE, name)
    assert fake.puts == []


@pytest.mark.parametrize(
    "email",
    ["", "   ", "dana at example.com", "dana@", "@example.com", "a@b@c", "d ana@e.com"],
)
def test_malformed_emails_are_refused(email, table) -> None:
    fake = table()
    with pytest.raises(ValidationError):
        patients.lookup_or_create_patient(CLINIC, PHONE, "Dana Okafor", email=email)
    assert fake.puts == []


# --------------------------------------------------------------------------
# Existing records are added to, never rewritten
# --------------------------------------------------------------------------


def test_an_existing_patients_details_are_not_overwritten(table) -> None:
    """A booking must not quietly change what the clinic already holds."""
    fake = table(stored_patient("Dana Okafor", email="dana@old.example.com"))
    patient, _ = patients.lookup_or_create_patient(
        CLINIC, PHONE, "Dana Okafor", email="typo@wrong.example.com"
    )
    assert patient["email"] == "dana@old.example.com"
    assert fake.updates == []


def test_a_missing_email_is_filled_in(table) -> None:
    """Additive: without it the reminder job has no address for this patient."""
    fake = table(stored_patient("Dana Okafor"))
    patient, created = patients.lookup_or_create_patient(
        CLINIC, PHONE, "Dana Okafor", email="dana@example.com"
    )
    assert created is False
    assert patient["email"] == "dana@example.com"
    assert len(fake.updates) == 1
    update = fake.updates[0]
    assert update["Key"] == {"clinic_id": CLINIC, "patient_id": "pat_existing"}
    assert update["ExpressionAttributeValues"][":email"] == "dana@example.com"
    # Re-checked at write time, in case another session filled it in first.
    assert "ConditionExpression" in update


def test_no_email_given_leaves_the_record_alone(table) -> None:
    fake = table(stored_patient("Dana Okafor"))
    patients.lookup_or_create_patient(CLINIC, PHONE, "Dana Okafor")
    assert fake.updates == []


# --------------------------------------------------------------------------
# What a tool hands back to the model
# --------------------------------------------------------------------------


def test_patient_summary_carries_only_what_is_spoken() -> None:
    summary = patients.patient_summary(
        stored_patient("Dana Okafor", email="dana@example.com"), created=False
    )
    assert summary == {
        "patient_id": "pat_existing",
        "name": "Dana Okafor",
        "phone": PHONE,
        "is_new": False,
    }


def test_patient_summary_rejects_an_item_with_no_id() -> None:
    with pytest.raises(ValidationError):
        patients.patient_summary({"name": "Dana Okafor"}, created=True)
