"""Tests for the boundary checks every tool runs before touching data."""

from __future__ import annotations

from decimal import Decimal

import pytest

from tools.errors import ValidationError
from tools.schema import AppointmentStatus
from tools.validation import (
    MAX_IDENTIFIER_LENGTH,
    normalise_phone,
    require_bounded_int,
    require_clinic_id,
    require_enum,
    require_identifier,
    require_text,
    require_timestamp,
)


@pytest.mark.parametrize("blank", ["", "   ", None, 0, [], {}])
def test_require_clinic_id_rejects_anything_blank_or_non_string(blank) -> None:
    """The tenant boundary: no tool may proceed without a real `clinic_id`."""
    with pytest.raises(ValidationError):
        require_clinic_id(blank)


def test_require_clinic_id_returns_the_trimmed_value() -> None:
    assert require_clinic_id("  clinic-dental  ") == "clinic-dental"


def test_require_clinic_id_error_names_the_argument() -> None:
    with pytest.raises(ValidationError, match="clinic_id"):
        require_clinic_id("")


def test_require_identifier_rejects_over_long_values() -> None:
    with pytest.raises(ValidationError):
        require_identifier("x" * (MAX_IDENTIFIER_LENGTH + 1), "patient_id")


def test_require_text_enforces_its_own_bound() -> None:
    assert require_text("  cleaning  ", "service") == "cleaning"
    with pytest.raises(ValidationError):
        require_text("x" * 51, "service", max_length=50)


def test_require_timestamp_normalises_to_the_stored_encoding() -> None:
    assert require_timestamp("2026-08-27T16:30:00+02:00", "starts_at") == (
        "2026-08-27T14:30:00Z"
    )
    assert require_timestamp("2026-08-27T14:30:00Z", "starts_at") == (
        "2026-08-27T14:30:00Z"
    )
    # Naive input is read as UTC, per `architecture.md` -> Storage Model.
    assert require_timestamp("2026-08-27T14:30:00", "starts_at") == (
        "2026-08-27T14:30:00Z"
    )


@pytest.mark.parametrize(
    "bad", ["", "tomorrow at 3", "27/08/2026", "2026-13-01T00:00:00Z", None]
)
def test_require_timestamp_rejects_unparseable_values(bad) -> None:
    """Speech-derived times arrive as prose; that must fail, not be guessed."""
    with pytest.raises(ValidationError):
        require_timestamp(bad, "starts_at")


def test_require_enum_accepts_members_and_their_strings() -> None:
    assert require_enum("scheduled", AppointmentStatus, "status") is (
        AppointmentStatus.SCHEDULED
    )
    assert require_enum("  SCHEDULED ", AppointmentStatus, "status") is (
        AppointmentStatus.SCHEDULED
    )
    assert require_enum(AppointmentStatus.CANCELLED, AppointmentStatus, "status") is (
        AppointmentStatus.CANCELLED
    )


def test_require_enum_error_lists_the_allowed_values() -> None:
    """The caller is often a model that guessed; tell it what is valid."""
    with pytest.raises(ValidationError, match="scheduled"):
        require_enum("pending", AppointmentStatus, "status")


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("+1 (555) 123-4567", "15551234567"),
        ("1-555-123-4567", "15551234567"),
        ("  1 555 123 4567  ", "15551234567"),
        ("555 123 4567", "5551234567"),
        ("555-123-4567", "5551234567"),
        ("+44 20 7946 0958", "442079460958"),
    ],
)
def test_normalise_phone_converges_on_one_stored_form(spoken, expected) -> None:
    """The `by-phone` index is an equality match; formats must converge.

    Including the ``+``: a leading marker that survived normalisation gave
    one number two index keys, so a caller who said "plus one" on Monday
    and did not on Tuesday got two patient records.
    """
    assert normalise_phone(spoken) == expected


def test_normalise_phone_does_not_invent_a_country_code() -> None:
    """The limit of what this can converge, asserted rather than assumed.

    A national number cannot be turned into its international form without
    assuming a country, which no context file specifies -- so these stay
    two keys, and it is `progress-tracker.md` -> Open Questions that has to
    resolve it, not a default picked here.
    """
    assert normalise_phone("555 123 4567") != normalise_phone("+1 555 123 4567")


@pytest.mark.parametrize("bad", ["", "12345", "1" * 16, "no digits here", None])
def test_normalise_phone_rejects_implausible_numbers(bad) -> None:
    with pytest.raises(ValidationError):
        normalise_phone(bad)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, 1), (3, 3), ("3", 3), (" 3 ", 3), (Decimal("3"), 3), (3.0, 3)],
)
def test_require_bounded_int_accepts_the_forms_a_count_arrives_in(
    value, expected
) -> None:
    """`None` means "not supplied"; a model sends `"3"`, DynamoDB a `Decimal`."""
    assert (
        require_bounded_int(value, "days", minimum=1, maximum=14, default=1) == expected
    )


@pytest.mark.parametrize("value", [0, 15, -1, 1.5, "many", True, None.__class__])
def test_require_bounded_int_rejects_rather_than_clamping(value) -> None:
    """Silently answering for 14 would hide the misunderstanding from the model."""
    with pytest.raises(ValidationError):
        require_bounded_int(value, "days", minimum=1, maximum=14, default=1)


def test_require_bounded_int_error_states_the_range() -> None:
    with pytest.raises(ValidationError, match="between 1 and 14"):
        require_bounded_int(365, "days", minimum=1, maximum=14, default=1)
