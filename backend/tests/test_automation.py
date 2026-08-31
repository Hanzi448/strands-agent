"""Tests for `tools.automation.run_daily_scan`, the background job's logic.

Three properties carry the weight here.

*The decision is binary and mutually exclusive.* A patient at or over
`NO_SHOW_RISK_THRESHOLD` prior no-shows is escalated and never reminded; a
patient under it is (attempted to be) reminded and never escalated. Both
directions are asserted, at and either side of the threshold.

*A batch job survives one bad row.* One appointment with no `patient_id`
on it must not stop the rest of the clinic's due appointments from being
processed -- the fake store below holds a good appointment and a bad one
in the same scan and both outcomes are asserted.

*Idempotency comes from the appointment's own `reminders` list*, not from
a second table. An appointment that already carries an entry is excluded
from the scan outright, before any decision is made about it.

Every fake and fixture is imported from the suite that owns it:
`FakeClinicsTable`/`dental_clinic` from `test_scheduling`, `FakeAppointmentStore`
/`booked` from `test_appointments`, `FakePatientsTable` from `test_booking`,
`FakeEscalationsTable` from `test_escalations` -- so a rule that drifted
between this module and the ones it calls into would show up as a
disagreement between suites rather than passing here in isolation.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.test_appointments import FakeAppointmentStore, booked, patient
from tests.test_booking import FakePatientsTable
from tests.test_escalations import FakeEscalationsTable
from tests.test_scheduling import COSMETIC_ID, DENTAL_ID, FakeClinicsTable, dental_clinic
from tools import appointments, automation, escalations, patients as patients_module, scheduling
from tools.errors import ConfigurationError, NotFoundError, ValidationError
from tools.schema import AppointmentStatus, EscalationSource, ReminderOutcome

NOW = "2026-07-01T09:00:00Z"
# Inside the 24-hour reminder window.
DUE_SOON = "2026-07-01T20:00:00Z"
# Outside it -- more than 24 hours after NOW.
TOO_FAR = "2026-07-03T09:00:00Z"
# Before NOW -- already started.
ALREADY_PAST = "2026-06-30T09:00:00Z"

PATIENT_ID = "pat_dana"
PHONE = "15551234567"
NAME = "Dana Okafor"
EMAIL = "dana@example.com"


def _patient(**overrides: Any) -> dict[str, Any]:
    item = patient(PATIENT_ID, NAME, PHONE)
    item.update(overrides)
    return item


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch):
    """Point every table accessor `run_daily_scan` touches at a fake.

    `scheduling`, `appointments`, `patients` and `escalations` are all
    patched, not just `automation`: the scan reaches DynamoDB through all
    four modules, which is the point -- this module owns no query or write
    of its own.
    """

    def install(
        *,
        appointment_items: list[dict[str, Any]] | None = None,
        patient_items: list[dict[str, Any]] | None = None,
        now: str = NOW,
        send_result: bool = True,
    ) -> tuple[FakeClinicsTable, FakeAppointmentStore, FakePatientsTable, FakeEscalationsTable]:
        clinics = FakeClinicsTable(dental_clinic())
        store = FakeAppointmentStore(*(appointment_items or []))
        patients_fake = FakePatientsTable(*(patient_items or [_patient(email=EMAIL)]))
        escalations_fake = FakeEscalationsTable()
        monkeypatch.setattr(scheduling, "clinics_table", lambda: clinics)
        monkeypatch.setattr(automation, "appointments_table", lambda: store)
        monkeypatch.setattr(appointments, "appointments_table", lambda: store)
        monkeypatch.setattr(patients_module, "patients_table", lambda: patients_fake)
        monkeypatch.setattr(escalations, "escalations_table", lambda: escalations_fake)
        monkeypatch.setattr(automation, "utc_now_iso", lambda: now)
        monkeypatch.setattr(
            automation, "_send_reminder_email", lambda *a, **k: send_result
        )
        return clinics, store, patients_fake, escalations_fake

    return install


def scan(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"clinic_id": DENTAL_ID, "now": _as_datetime(NOW)}
    kwargs.update(overrides)
    return automation.run_daily_scan(**kwargs)


def _as_datetime(value: str):
    from tools.schema import from_iso8601

    return from_iso8601(value)


# --------------------------------------------------------------------------
# The tenant boundary
# --------------------------------------------------------------------------


@pytest.mark.parametrize("clinic_id", ["", "   ", None])
def test_blank_clinic_id_fails_before_any_read(clinic_id, tables) -> None:
    clinics, store, _, _ = tables()
    with pytest.raises(ValidationError):
        scan(clinic_id=clinic_id)
    assert clinics.requested == []
    assert store.queries == []


def test_unknown_clinic_is_not_found(tables) -> None:
    tables()
    with pytest.raises(NotFoundError):
        scan(clinic_id="clinic-nowhere")


def test_another_clinics_appointment_is_invisible(tables) -> None:
    """The index partition key is `clinic_id`; a scan cannot cross tenants."""
    _, store, _, escalations_fake = tables(
        appointment_items=[
            booked("apt_other", DUE_SOON, "2026-07-01T20:30:00Z", clinic_id=COSMETIC_ID)
        ]
    )
    result = scan()
    assert result["scanned"] == 0
    assert store.updates == []
    assert escalations_fake.puts == []


# --------------------------------------------------------------------------
# The scan window
# --------------------------------------------------------------------------


def test_appointment_outside_the_window_is_not_scanned(tables) -> None:
    _, store, _, _ = tables(
        appointment_items=[booked("apt_far", TOO_FAR, "2026-07-03T09:15:00Z")]
    )
    result = scan()
    assert result["scanned"] == 0
    assert store.updates == []


def test_appointment_already_under_way_is_not_scanned(tables) -> None:
    _, store, _, _ = tables(
        appointment_items=[booked("apt_past", ALREADY_PAST, "2026-06-30T09:15:00Z")]
    )
    result = scan()
    assert result["scanned"] == 0


def test_cancelled_appointment_is_not_scanned(tables) -> None:
    tables(
        appointment_items=[
            booked("apt_cancelled", DUE_SOON, "2026-07-01T20:15:00Z", status="cancelled")
        ]
    )
    assert scan()["scanned"] == 0


def test_already_reminded_appointment_is_skipped(tables) -> None:
    """Idempotency: a non-empty `reminders` list means this job already ran."""
    _, store, _, _ = tables(
        appointment_items=[
            booked(
                "apt_done",
                DUE_SOON,
                "2026-07-01T20:15:00Z",
                reminders=[
                    {"at": "2026-06-30T09:00:00Z", "channel": "email", "outcome": "sent"}
                ],
            )
        ]
    )
    result = scan()
    assert result["scanned"] == 0
    assert store.updates == []


# --------------------------------------------------------------------------
# Reminders
# --------------------------------------------------------------------------


def test_a_low_risk_patient_is_reminded_not_escalated(tables) -> None:
    _, store, _, escalations_fake = tables(
        appointment_items=[booked("apt_one", DUE_SOON, "2026-07-01T20:15:00Z")]
    )
    result = scan()
    assert result["scanned"] == 1
    assert result["reminded"] == 1
    assert result["escalated"] == 0
    assert escalations_fake.puts == []
    entry = store.stored("apt_one")["reminders"][-1]
    assert entry["outcome"] == ReminderOutcome.SENT.value
    assert entry["channel"] == "email"
    assert entry["at"] == NOW
    assert result["results"][0]["outcome"] == "reminder_sent"


def test_ses_rejecting_the_send_is_recorded_as_failed(tables) -> None:
    _, store, _, _ = tables(
        appointment_items=[booked("apt_one", DUE_SOON, "2026-07-01T20:15:00Z")],
        send_result=False,
    )
    result = scan()
    assert result["reminded"] == 0
    assert result["reminder_failed"] == 1
    assert store.stored("apt_one")["reminders"][-1]["outcome"] == ReminderOutcome.FAILED.value


def test_a_patient_with_no_email_is_never_asked_to_send(tables, monkeypatch) -> None:
    _, store, _, _ = tables(
        appointment_items=[booked("apt_one", DUE_SOON, "2026-07-01T20:15:00Z")],
        patient_items=[_patient()],  # no email key at all
    )
    calls: list[Any] = []
    monkeypatch.setattr(
        automation, "_send_reminder_email", lambda *a, **k: calls.append(a) or True
    )
    result = scan()
    assert calls == []
    assert result["reminder_failed"] == 1
    assert result["results"][0]["detail"] == "no email on file"
    assert store.stored("apt_one")["reminders"][-1]["outcome"] == ReminderOutcome.FAILED.value


# --------------------------------------------------------------------------
# No-show risk escalation
# --------------------------------------------------------------------------


def _history(no_show_count: int) -> list[dict[str, Any]]:
    """`no_show_count` past, resolved no-shows plus one appointment due today."""
    history = [
        booked(
            f"apt_past_{index}",
            f"2026-06-{10 + index:02d}T09:00:00Z",
            f"2026-06-{10 + index:02d}T09:15:00Z",
            status=AppointmentStatus.NO_SHOW.value,
        )
        for index in range(no_show_count)
    ]
    history.append(booked("apt_today", DUE_SOON, "2026-07-01T20:15:00Z"))
    return history


def test_a_patient_at_the_threshold_is_escalated_not_reminded(tables) -> None:
    _, store, _, escalations_fake = tables(
        appointment_items=_history(automation.NO_SHOW_RISK_THRESHOLD)
    )
    result = scan()
    assert result["escalated"] == 1
    assert result["reminded"] == 0
    assert len(escalations_fake.puts) == 1
    written = escalations_fake.puts[0]["Item"]
    assert written["source"] == EscalationSource.BACKGROUND.value
    assert written["patient_id"] == PATIENT_ID
    assert written["appointment_id"] == "apt_today"
    assert "prior no-show" in written["reason"]
    assert "Check-up" in written["reason"]
    # Never reached the reminder path.
    assert store.stored("apt_today")["reminders"] == []


def test_a_patient_below_the_threshold_is_reminded_not_escalated(tables) -> None:
    below = automation.NO_SHOW_RISK_THRESHOLD - 1
    if below < 0:
        pytest.skip("threshold is 0; nothing is below it")
    _, store, _, escalations_fake = tables(appointment_items=_history(below))
    result = scan()
    assert result["escalated"] == 0
    assert result["reminded"] == 1
    assert escalations_fake.puts == []


def test_no_show_count_ignores_other_patients_history(tables) -> None:
    """`by-patient` is keyed per patient; a housemate's history is invisible."""
    housemate_history = [
        booked(
            "apt_housemate_noshow",
            "2026-06-10T09:00:00Z",
            "2026-06-10T09:15:00Z",
            patient_id="pat_housemate",
            status=AppointmentStatus.NO_SHOW.value,
        ),
        booked("apt_today", DUE_SOON, "2026-07-01T20:15:00Z"),
    ]
    _, store, _, escalations_fake = tables(appointment_items=housemate_history)
    result = scan()
    assert result["escalated"] == 0
    assert result["reminded"] == 1
    assert escalations_fake.puts == []


# --------------------------------------------------------------------------
# Robustness: one bad row must not sink the scan
# --------------------------------------------------------------------------


def test_a_bad_appointment_is_reported_and_does_not_stop_the_rest(tables) -> None:
    bad = booked("apt_bad", DUE_SOON, "2026-07-01T20:15:00Z")
    bad["patient_id"] = ""
    good = booked("apt_good", DUE_SOON, "2026-07-01T20:15:00Z")
    _, store, _, _ = tables(appointment_items=[bad, good])
    result = scan()
    assert result["scanned"] == 2
    assert result["skipped"] == 1
    assert result["reminded"] == 1
    outcomes = {r["appointment_id"]: r["outcome"] for r in result["results"]}
    assert outcomes["apt_bad"] == "failed"
    assert outcomes["apt_good"] == "reminder_sent"


# --------------------------------------------------------------------------
# The SES sender address
# --------------------------------------------------------------------------


def test_missing_sender_env_raises_configuration_error(monkeypatch) -> None:
    monkeypatch.delenv(automation.REMINDER_SENDER_ENV, raising=False)
    with pytest.raises(ConfigurationError):
        automation._reminder_sender_email()


def test_sender_env_is_trimmed(monkeypatch) -> None:
    monkeypatch.setenv(automation.REMINDER_SENDER_ENV, "  demo@example.com  ")
    assert automation._reminder_sender_email() == "demo@example.com"
