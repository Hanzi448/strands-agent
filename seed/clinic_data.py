"""The two demo `Clinics` items -- config, not code.

Shapes match `architecture.md` -> Storage Model ("Clinic availability
config") and `backend/tests/test_scheduling.py`'s fixtures exactly: the
dental clinic runs a real lunch break on a 15-minute grid with short
services, the cosmetic clinic runs unbroken hours on a 30-minute grid with
long ones. They differ on every axis on purpose -- an availability bug
that assumes one clinic's shape shows up on the other the moment both are
seeded (`project-overview.md` Goal 2).

Both are UK clinics (`timezone: "Europe/London"`), so both seed
`country_code: "44"` -- the value `progress-tracker.md` recorded when the
phone-reconciliation question was resolved, and what lets a sample number
be written in either national or international form.

Every attribute name is a `tools.schema.ClinicAttrs`/`HoursInterval`/
`ClosureAttrs`/`ServiceAttrs` constant, never an inline string literal --
this writes real `Clinics` rows, not test fixtures, so
`code-standards.md` -> Python's "no inline attribute literals" applies
here exactly as it does in `backend/tools/`.
"""

from __future__ import annotations

from typing import Any, Final

from tools.schema import (
    WEEKDAY_KEYS,
    ClinicAttrs,
    ClinicType,
    ClosureAttrs,
    HoursInterval,
    ServiceAttrs,
    utc_now_iso,
)

DENTAL_CLINIC_ID: Final[str] = "clinic-dental"
COSMETIC_CLINIC_ID: Final[str] = "clinic-cosmetic"

# `WEEKDAY_KEYS` is ordered Monday first (`schema.weekday_key`'s contract).
# Named here rather than spelled as literals in the two `hours` maps below.
MON, TUE, WED, THU, FRI, SAT, SUN = WEEKDAY_KEYS

# Digits only, no leading "+" -- `validation.normalise_phone`'s
# `country_code` shape. Both demo clinics are UK-based.
UK_COUNTRY_CODE: Final[str] = "44"


def _hours_interval(open_: str, close: str) -> dict[str, str]:
    return {HoursInterval.OPEN: open_, HoursInterval.CLOSE: close}


def _service(service_id: str, name: str, duration_minutes: int) -> dict[str, Any]:
    return {
        ServiceAttrs.ID: service_id,
        ServiceAttrs.NAME: name,
        ServiceAttrs.DURATION_MINUTES: duration_minutes,
    }


def _closure(date: str, label: str) -> dict[str, str]:
    return {ClosureAttrs.DATE: date, ClosureAttrs.LABEL: label}


def dental_clinic_item() -> dict[str, Any]:
    """Bright Smile Dental: Mon-Fri lunch break, short Sat morning, 15-min grid."""
    weekday = [_hours_interval("09:00", "13:00"), _hours_interval("14:00", "17:30")]
    now = utc_now_iso()
    return {
        ClinicAttrs.CLINIC_ID: DENTAL_CLINIC_ID,
        ClinicAttrs.NAME: "Bright Smile Dental",
        ClinicAttrs.CLINIC_TYPE: ClinicType.DENTAL.value,
        ClinicAttrs.TIMEZONE: "Europe/London",
        ClinicAttrs.HOURS: {
            MON: weekday,
            TUE: weekday,
            WED: weekday,
            THU: weekday,
            FRI: weekday,
            SAT: [_hours_interval("09:00", "12:00")],
            SUN: [],
        },
        ClinicAttrs.CLOSURES: [_closure("2026-12-25", "Christmas Day")],
        ClinicAttrs.SERVICES: [
            _service("checkup", "Check-up", 15),
            _service("cleaning", "Dental cleaning", 30),
        ],
        ClinicAttrs.SLOT_MINUTES: 15,
        ClinicAttrs.COUNTRY_CODE: UK_COUNTRY_CODE,
        ClinicAttrs.CONTACT_EMAIL: "hello@brightsmiledental.demo",
        ClinicAttrs.CONTACT_PHONE: "+44 20 7946 0001",
        ClinicAttrs.CREATED_AT: now,
        ClinicAttrs.UPDATED_AT: now,
    }


def cosmetic_clinic_item() -> dict[str, Any]:
    """Lumiere Aesthetics: Tue-Sat unbroken hours, 30-min grid, long services."""
    weekday = [_hours_interval("10:00", "18:00")]
    now = utc_now_iso()
    return {
        ClinicAttrs.CLINIC_ID: COSMETIC_CLINIC_ID,
        ClinicAttrs.NAME: "Lumiere Aesthetics",
        ClinicAttrs.CLINIC_TYPE: ClinicType.COSMETIC.value,
        ClinicAttrs.TIMEZONE: "Europe/London",
        ClinicAttrs.HOURS: {
            MON: [],
            TUE: weekday,
            WED: weekday,
            THU: weekday,
            FRI: weekday,
            SAT: weekday,
            SUN: [],
        },
        ClinicAttrs.CLOSURES: [_closure("2026-12-25", "Christmas Day")],
        ClinicAttrs.SERVICES: [
            _service("consult", "Consultation", 60),
            _service("treatment", "Treatment", 90),
        ],
        ClinicAttrs.SLOT_MINUTES: 30,
        ClinicAttrs.COUNTRY_CODE: UK_COUNTRY_CODE,
        ClinicAttrs.CONTACT_EMAIL: "hello@lumiereaesthetics.demo",
        ClinicAttrs.CONTACT_PHONE: "+44 20 7946 0002",
        ClinicAttrs.CREATED_AT: now,
        ClinicAttrs.UPDATED_AT: now,
    }


# The complete list `run_seed.py` writes. Order is display order only --
# `Clinics` has no sort key, so nothing about storage depends on it.
DEMO_CLINICS: Final[tuple[Any, ...]] = (dental_clinic_item, cosmetic_clinic_item)
