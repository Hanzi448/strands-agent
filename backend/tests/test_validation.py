"""Tests for the boundary checks every tool runs before touching data."""

from __future__ import annotations

import pytest

from tools.errors import ValidationError
from tools.schema import AppointmentStatus
from tools.validation import (
    MAX_IDENTIFIER_LENGTH,
    normalise_phone,
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
        ("+1 (555) 123-4567", "+15551234567"),
        ("555 123 4567", "5551234567"),
        ("555-123-4567", "5551234567"),
        ("+44 20 7946 0958", "+442079460958"),
    ],
)
def test_normalise_phone_converges_on_one_stored_form(spoken, expected) -> None:
    """The `by-phone` index is an equality match; formats must converge."""
    assert normalise_phone(spoken) == expected


@pytest.mark.parametrize("bad", ["", "12345", "1" * 16, "no digits here", None])
def test_normalise_phone_rejects_implausible_numbers(bad) -> None:
    with pytest.raises(ValidationError):
        normalise_phone(bad)
