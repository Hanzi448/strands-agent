"""Tests for the item schema's key and timestamp encodings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tools.errors import ValidationError
from tools.schema import (
    ACTIVE_APPOINTMENT_STATUSES,
    APPOINTMENT_ID_PREFIX,
    AppointmentStatus,
    EscalationStatus,
    KEY_SEPARATOR,
    clinic_patient_key,
    new_id,
    to_iso8601,
    utc_now_iso,
)


def test_new_id_is_prefixed_unique_and_key_safe() -> None:
    ids = {new_id(APPOINTMENT_ID_PREFIX) for _ in range(100)}
    assert len(ids) == 100
    for value in ids:
        assert value.startswith(f"{APPOINTMENT_ID_PREFIX}_")
        # Composite keys split on this separator; an id containing one
        # would make the split ambiguous.
        assert KEY_SEPARATOR not in value


def test_clinic_patient_key_composes_both_parts() -> None:
    assert clinic_patient_key("clinic-a", "pat_1") == f"clinic-a{KEY_SEPARATOR}pat_1"


def test_clinic_patient_key_trims_whitespace() -> None:
    assert clinic_patient_key("  clinic-a  ", " pat_1 ") == "clinic-a#pat_1"


@pytest.mark.parametrize(
    ("clinic_id", "patient_id"),
    [
        ("", "pat_1"),
        ("   ", "pat_1"),
        ("clinic-a", ""),
        (None, "pat_1"),
        ("clinic-a", None),
    ],
)
def test_clinic_patient_key_rejects_missing_parts(clinic_id, patient_id) -> None:
    with pytest.raises(ValidationError):
        clinic_patient_key(clinic_id, patient_id)


def test_clinic_patient_key_rejects_embedded_separator() -> None:
    """An ambiguous split is the one failure this composite key must prevent.

    Without the guard, clinic ``a`` + patient ``b#c`` and clinic ``a#b`` +
    patient ``c`` would produce the same index key -- a cross-clinic read
    (`architecture.md` -> Invariants #1).
    """
    with pytest.raises(ValidationError):
        clinic_patient_key("a", "b#c")
    with pytest.raises(ValidationError):
        clinic_patient_key("a#b", "c")


def test_to_iso8601_normalises_offsets_to_utc_z() -> None:
    aware = datetime(2026, 8, 27, 16, 30, 0, tzinfo=timezone(timedelta(hours=2)))
    assert to_iso8601(aware) == "2026-08-27T14:30:00Z"


def test_to_iso8601_reads_naive_values_as_utc() -> None:
    assert to_iso8601(datetime(2026, 8, 27, 14, 30, 0)) == "2026-08-27T14:30:00Z"


def test_to_iso8601_drops_sub_second_precision() -> None:
    value = datetime(2026, 8, 27, 14, 30, 0, 123456, tzinfo=timezone.utc)
    assert to_iso8601(value) == "2026-08-27T14:30:00Z"


def test_encoded_timestamps_sort_lexicographically() -> None:
    """`starts_at` is a sort key and DynamoDB compares strings bytewise.

    Mixed offsets or precisions would order items wrongly with no error,
    so encoding order and chronological order must agree.
    """
    moments = [
        datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc),
        datetime(2026, 8, 27, 11, 0, tzinfo=timezone(timedelta(hours=2))),  # 09:00Z
        datetime(2026, 8, 27, 9, 30, tzinfo=timezone.utc),
        datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc),
        datetime(2026, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
    ]
    encoded = [to_iso8601(moment) for moment in moments]
    assert sorted(encoded) == [to_iso8601(m) for m in sorted(moments)]


def test_utc_now_iso_matches_the_stored_format() -> None:
    now = utc_now_iso()
    assert now.endswith("Z")
    assert datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ")


def test_status_vocabularies_serialise_as_plain_strings() -> None:
    """Statuses are written straight into DynamoDB, so they must be `str`."""
    assert isinstance(AppointmentStatus.SCHEDULED, str)
    assert AppointmentStatus.SCHEDULED == "scheduled"
    assert isinstance(EscalationStatus.OPEN, str)
    assert EscalationStatus.OPEN == "open"


def test_only_scheduled_appointments_occupy_a_slot() -> None:
    assert AppointmentStatus.SCHEDULED in ACTIVE_APPOINTMENT_STATUSES
    for freed in (
        AppointmentStatus.CANCELLED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
    ):
        assert freed not in ACTIVE_APPOINTMENT_STATUSES
