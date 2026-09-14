"""Staff-editable clinic config: the Settings tab's read and write.

`architecture.md` -> Storage Model fixes the four availability
attributes (`hours`, `closures`, `services`, `slot_minutes`) and states
that nothing outside a clinic's own item may be consulted to decide
whether a time is bookable. This module is the one sanctioned way to
change them after seeding: the staff dashboard reads the current config
here and writes a new one here, so the validation lives in the tool
layer rather than in a route handler or a form (`Invariants #3` -- the
same reason the background Lambda calls `tools.automation`, not a copy
of it).

**Validation is eager, and that is the module's whole point.** A
malformed config today fails *lazily*, inside `check_availability`,
with a patient mid-call; a `ConfigurationError` raised there is the
availability tool doing its job. A bad edit that reached the table
would turn every later call into that failure, so `update_clinic_config`
checks every field against the exact shapes `architecture.md` specifies
*before* anything is written -- a refused edit writes nothing at all,
and every refusal is a `ValidationError` naming the field, because the
reader is a member of staff looking at a form, the same audience the
escalation messages are written for.

Semantics are full replacement, not patching: the dashboard sends the
whole edited config (all four fields, every weekday), and one
`update_item` lands it plus an `updated_at` stamp. Two staff saving at
once is last-write-wins -- the two-account demo does not need
optimistic locking, and a conditional write would only turn a lost
edit into an unexplained 409.
"""

from __future__ import annotations

import re
from datetime import date as date_type
from decimal import Decimal
from typing import Any

from .dynamo import clinics_table
from .errors import ValidationError
from .schema import (
    CLINIC_ID,
    DATE_FORMAT,
    ClinicAttrs,
    ClosureAttrs,
    HoursInterval,
    ServiceAttrs,
    WEEKDAY_KEYS,
    utc_now_iso,
)
from .scheduling import get_clinic
from .validation import require_clinic_id, require_date, require_identifier, require_text

# No service or slot can meaningfully be longer than a whole day, and an
# interval longer than a day could never fit inside an opening -- so one
# bound serves both fields as "longer than this is a mistake, not a
# choice".
MAX_MINUTES_PER_DAY = 24 * 60

# `HH:MM`, 24-hour, two digits each, exactly as the seeded configs and
# `architecture.md` spell it. Strict on purpose: a settings form is a
# *writer*, and "9:00" accepted here would be one more stored spelling
# the availability loop has to keep parsing.
_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def get_clinic_config(clinic_id: str) -> dict[str, Any]:
    """Read the config the Settings tab edits.

    Args:
        clinic_id: The clinic whose config is being read. Validated
            here, so callers cannot skip it.

    Returns:
        The clinic's `name` and `timezone` (displayed read-only -- they
        are set at seed time and not editable) plus the four editable
        fields, with `Decimal`s normalised to `int` so the dashboard's
        JSON needs no special casing.

    Raises:
        ValidationError: If `clinic_id` is missing or blank.
        NotFoundError: If no such clinic exists.
    """
    clinic_id = require_clinic_id(clinic_id)
    return _config_view(get_clinic(clinic_id))


def update_clinic_config(
    clinic_id: str,
    *,
    hours: Any,
    closures: Any,
    services: Any,
    slot_minutes: Any,
) -> dict[str, Any]:
    """Replace one clinic's availability config with a validated one.

    Every field is checked against the shapes `architecture.md` ->
    Storage Model fixes before anything is written; see the module
    docstring for why a bad edit must never reach the table.

    Args:
        clinic_id: The clinic being edited. Validated first, before any
            field, so a request with every argument wrong still names
            `clinic_id` -- the same ordering every tool enforces.
        hours: All seven weekday keys, each a list of
            ``{"open": "HH:MM", "close": "HH:MM"}`` intervals; an empty
            list means closed that day.
        closures: A list of ``{"date": "YYYY-MM-DD", "label": str}``
            whole-day closures, replacing the previous list wholesale.
        services: A non-empty list of
            ``{"id", "name", "duration_minutes"}`` -- the booking agent
            can offer nothing without at least one.
        slot_minutes: The grid candidate start times are offered on.

    Returns:
        The updated config, the same shape `get_clinic_config` gives,
        so the dashboard can refresh the form from the write's own
        response.

    Raises:
        ValidationError: If `clinic_id` is missing or blank, or any
            field is malformed. Nothing is written.
        NotFoundError: If no such clinic exists.
    """
    clinic_id = require_clinic_id(clinic_id)
    existing = get_clinic(clinic_id)
    clean_hours = _validate_hours(hours)
    clean_closures = _validate_closures(closures)
    clean_services = _validate_services(services)
    clean_slot_minutes = _validate_minutes(slot_minutes, ClinicAttrs.SLOT_MINUTES)

    clinics_table().update_item(
        Key={CLINIC_ID: clinic_id},
        # Every attribute through a `#name` alias, the discipline
        # `tools/appointments.py` follows for the reserved `status`.
        UpdateExpression=(
            "SET #hours = :hours, #closures = :closures, "
            "#services = :services, #slot_minutes = :slot_minutes, "
            "#updated_at = :updated_at"
        ),
        ExpressionAttributeNames={
            "#hours": ClinicAttrs.HOURS,
            "#closures": ClinicAttrs.CLOSURES,
            "#services": ClinicAttrs.SERVICES,
            "#slot_minutes": ClinicAttrs.SLOT_MINUTES,
            "#updated_at": ClinicAttrs.UPDATED_AT,
        },
        ExpressionAttributeValues={
            ":hours": clean_hours,
            ":closures": clean_closures,
            ":services": clean_services,
            ":slot_minutes": clean_slot_minutes,
            ":updated_at": utc_now_iso(),
        },
    )

    updated = {
        **existing,
        ClinicAttrs.HOURS: clean_hours,
        ClinicAttrs.CLOSURES: clean_closures,
        ClinicAttrs.SERVICES: clean_services,
        ClinicAttrs.SLOT_MINUTES: clean_slot_minutes,
    }
    return _config_view(updated)


# --------------------------------------------------------------------------
# Response shaping
# --------------------------------------------------------------------------


def _config_view(clinic: dict[str, Any]) -> dict[str, Any]:
    """The config the dashboard sees: two read-only fields and the four
    editable ones, with DynamoDB `Decimal`s normalised to `int`."""
    services = []
    for entry in clinic.get(ClinicAttrs.SERVICES) or []:
        if not isinstance(entry, dict):
            continue
        services.append(
            {
                ServiceAttrs.ID: entry.get(ServiceAttrs.ID),
                ServiceAttrs.NAME: entry.get(ServiceAttrs.NAME),
                ServiceAttrs.DURATION_MINUTES: _as_int(
                    entry.get(ServiceAttrs.DURATION_MINUTES)
                ),
            }
        )
    return {
        "name": clinic.get(ClinicAttrs.NAME),
        "timezone": clinic.get(ClinicAttrs.TIMEZONE),
        "hours": clinic.get(ClinicAttrs.HOURS) or {},
        "closures": clinic.get(ClinicAttrs.CLOSURES) or [],
        "services": services,
        "slot_minutes": _as_int(clinic.get(ClinicAttrs.SLOT_MINUTES)),
    }


def _as_int(value: Any) -> int | None:
    """A DynamoDB `Decimal` as an `int`, for the JSON a browser reads."""
    if isinstance(value, Decimal):
        return int(value)
    return value if isinstance(value, int) else None


# --------------------------------------------------------------------------
# Field validation
# --------------------------------------------------------------------------


def _validate_hours(hours: Any) -> dict[str, list[dict[str, str]]]:
    """All seven weekday keys, each a list of ordered, well-formed intervals.

    A missing key is refused rather than defaulted, because "closed
    every Monday" and "we forgot to send Monday" must not store the
    same way -- the form always sends all seven, an empty list being
    the honest spelling of closed.
    """
    if not isinstance(hours, dict):
        raise ValidationError(
            "hours must be an object with one key per weekday "
            "(mon, tue, wed, thu, fri, sat, sun); "
            'e.g. {"mon": [{"open": "09:00", "close": "17:00"}], ...}.'
        )
    missing = sorted(set(WEEKDAY_KEYS) - set(hours))
    if missing:
        raise ValidationError(
            f"hours is missing the weekday key(s) {', '.join(missing)}; all "
            "seven are required, an empty list meaning closed that day."
        )
    unexpected = sorted(set(hours) - set(WEEKDAY_KEYS))
    if unexpected:
        raise ValidationError(
            f"hours has key(s) {', '.join(unexpected)} that are not "
            f"weekdays; expected only {', '.join(WEEKDAY_KEYS)}."
        )
    return {
        weekday: _validate_intervals(hours[weekday], f"hours.{weekday}")
        for weekday in WEEKDAY_KEYS
    }


def _validate_intervals(intervals: Any, field: str) -> list[dict[str, str]]:
    """Intervals ascending, non-overlapping, each closing after it opens."""
    if not isinstance(intervals, list):
        raise ValidationError(
            f"{field} must be a list of open/close intervals, "
            'e.g. [{"open": "09:00", "close": "17:00"}]; got {intervals!r}.'
        )
    cleaned: list[dict[str, str]] = []
    previous_close: int | None = None
    for entry in intervals:
        if not isinstance(entry, dict):
            raise ValidationError(
                f"each interval in {field} must be an object with 'open' "
                f"and 'close'; got {entry!r}."
            )
        opened, open_text = _validate_time(entry.get(HoursInterval.OPEN), f"{field} open")
        closed, close_text = _validate_time(
            entry.get(HoursInterval.CLOSE), f"{field} close"
        )
        if closed <= opened:
            raise ValidationError(
                f"{field} must close strictly after it opens; "
                f"got {open_text}-{close_text}."
            )
        if previous_close is not None and opened < previous_close:
            raise ValidationError(
                f"intervals in {field} must be ascending and non-overlapping; "
                f"{open_text} starts before the previous interval closes at "
                f"{_minutes_as_time(previous_close)}."
            )
        cleaned.append({HoursInterval.OPEN: open_text, HoursInterval.CLOSE: close_text})
        previous_close = closed
    return cleaned


def _validate_time(value: Any, field: str) -> tuple[int, str]:
    """One `HH:MM` clinic-local wall-clock time, as minutes past midnight."""
    if not isinstance(value, str) or not _TIME_PATTERN.match(value.strip()):
        raise ValidationError(
            f'{field} must be a 24-hour time in the form HH:MM, e.g. "09:00"; '
            f"got {value!r}."
        )
    text = value.strip()
    hours, minutes = (int(part) for part in text.split(":"))
    return hours * 60 + minutes, text


def _minutes_as_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _validate_closures(closures: Any) -> list[dict[str, str]]:
    """Whole-day closures; a date may appear once, since two labels for
    one day is a form mistake, not two closures."""
    if not isinstance(closures, list):
        raise ValidationError(
            "closures must be a list of "
            '{"date": "YYYY-MM-DD", "label": str} entries; '
            f"got {closures!r}."
        )
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in closures:
        if not isinstance(entry, dict):
            raise ValidationError(
                "each closure must be an object with 'date' and 'label'; "
                f"got {entry!r}."
            )
        day: date_type = require_date(entry.get(ClosureAttrs.DATE), "closures date")
        date_text = day.strftime(DATE_FORMAT)
        if date_text in seen:
            raise ValidationError(
                f"closures has more than one entry for {date_text}; a date "
                "can be closed only once."
            )
        seen.add(date_text)
        cleaned.append(
            {
                ClosureAttrs.DATE: date_text,
                ClosureAttrs.LABEL: require_text(
                    entry.get(ClosureAttrs.LABEL), "closures label"
                ),
            }
        )
    return cleaned


def _validate_services(services: Any) -> list[dict[str, Any]]:
    """The treatments a booking can name; at least one, ids unique.

    An empty list is refused because `resolve_service` raises
    `ConfigurationError` for a clinic with no services -- a config the
    settings tab cannot save is one the agent never has to apologise
    for.
    """
    if not isinstance(services, list) or not services:
        raise ValidationError(
            "services must be a non-empty list of the treatments this clinic "
            "offers; a clinic with none cannot take a booking."
        )
    cleaned: list[dict[str, Any]] = []
    ids: set[str] = set()
    for entry in services:
        if not isinstance(entry, dict):
            raise ValidationError(
                "each service must be an object with 'id', 'name' and "
                f"'duration_minutes'; got {entry!r}."
            )
        service_id = require_identifier(entry.get(ServiceAttrs.ID), "services id")
        if service_id in ids:
            raise ValidationError(
                f"services has more than one entry with id {service_id!r}; "
                "ids must be unique."
            )
        ids.add(service_id)
        cleaned.append(
            {
                ServiceAttrs.ID: service_id,
                ServiceAttrs.NAME: require_text(
                    entry.get(ServiceAttrs.NAME), "services name"
                ),
                ServiceAttrs.DURATION_MINUTES: _validate_minutes(
                    entry.get(ServiceAttrs.DURATION_MINUTES),
                    "services duration_minutes",
                ),
            }
        )
    return cleaned


def _validate_minutes(value: Any, field: str) -> int:
    """A whole, positive number of minutes, up to a full day.

    Accepts an `int` from a form, a `Decimal` from a DynamoDB read, or
    a digit string from a form that did not parse its own number -- the
    same acceptance `validation.require_bounded_int` gives a count a
    model chooses, minus the default: both fields here are required.
    """
    if value is None or isinstance(value, bool):
        raise ValidationError(
            f"{field} is required and must be a whole number of minutes; "
            f"got {value!r}."
        )
    if not isinstance(value, (int, Decimal, float, str)):
        raise ValidationError(
            f"{field} must be a whole number of minutes; got {value!r}."
        )
    try:
        number = Decimal(str(value).strip())
    except ArithmeticError as exc:
        raise ValidationError(
            f"{field} must be a whole number of minutes; got {value!r}."
        ) from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValidationError(
            f"{field} must be a whole number of minutes; got {value!r}."
        )
    minutes = int(number)
    if not 1 <= minutes <= MAX_MINUTES_PER_DAY:
        raise ValidationError(
            f"{field} must be between 1 and {MAX_MINUTES_PER_DAY} minutes "
            f"(a full day); got {minutes}."
        )
    return minutes
