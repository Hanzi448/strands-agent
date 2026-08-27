"""Availability: the start times a clinic can offer, for one service, one day.

`architecture.md` -> Storage Model ("Clinic availability config") fixes the
rules implemented here, and fixes them *entirely on the clinic's own item*:
`timezone`, `hours`, `closures`, `services`, `slot_minutes`. Nothing in this
module consults a global constant, an environment value, or a per-clinic
branch to decide whether a time is bookable -- that is what makes "the same
deployed agent serves two different clinics" (`project-overview.md` Goal 2)
a property of the data rather than a claim.

This module is also the project's only local/UTC conversion point. A clinic
opens at 09:00 wall-clock, not at an instant, so `hours` and `closures`
cannot be UTC without breaking across a DST boundary; `starts_at` is a
bytewise-ordered sort key, so storage cannot be local. Both facts meet here
and nowhere else -- no Lambda, dashboard, or agent prompt ever holds a
local-time value it might compare against a stored one.

Read-only: nothing here writes. A slot offered by `check_availability` can
be taken before the caller answers, so `book_appointment` re-checks the slot
it is finally given rather than trusting a list returned earlier.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .dynamo import appointments_table, clinics_table
from .errors import ConfigurationError, NotFoundError, ValidationError
from .schema import (
    ACTIVE_APPOINTMENT_STATUSES,
    APPOINTMENTS_BY_START_TIME_INDEX,
    CLINIC_ID,
    DATE_FORMAT,
    LOCAL_TIME_FORMAT,
    STARTS_AT,
    AppointmentAttrs,
    AppointmentStatus,
    ClinicAttrs,
    ClosureAttrs,
    HoursInterval,
    ServiceAttrs,
    from_iso8601,
    to_iso8601,
    weekday_key,
)
from .validation import (
    MAX_IDENTIFIER_LENGTH,
    require_clinic_id,
    require_date,
    require_text,
)

# The width of the clinic-local day the `by-start-time` query is bounded to.
_ONE_DAY = timedelta(days=1)


def check_availability(clinic_id: str, date: str, service: str) -> dict[str, Any]:
    """List the appointment start times a clinic can offer on one day.

    Reads the clinic's configured opening hours for that weekday, drops the
    day entirely if it is a whole-day closure, generates candidate starts on
    the clinic's slot grid, and removes any that would overlap an existing
    appointment. A candidate is offered only if the *whole* service duration
    fits inside a single opening interval, so a 60-minute consult is never
    offered at 12:30 against a 13:00 lunch break.

    Nothing is booked or changed by this call.

    Args:
        clinic_id: The clinic the caller is talking to. Required; never
            inferred or defaulted.
        date: The day to check, as ``YYYY-MM-DD``, in the clinic's own
            local calendar (not UTC).
        service: Which service the appointment is for, as either the
            service id or the service name the clinic uses for it. The
            service decides how long the appointment is, so it is required
            even to *look* at availability.

    Returns:
        A dict with:
          - ``clinic_id``, ``date`` (``YYYY-MM-DD``), ``timezone`` (IANA).
          - ``service``: ``{"id", "name", "duration_minutes"}`` as the
            clinic defines it -- use ``id`` when booking, ``name`` when
            speaking to the patient.
          - ``is_open``: whether the clinic opens at all that day.
          - ``closure_label``: the clinic's own label for the closure
            (e.g. a public holiday) when the day is closed for that
            reason, otherwise ``None``. ``is_open`` false with a null
            label means the clinic simply does not open on that weekday.
          - ``slots``: a list, earliest first, of
            ``{"starts_at", "ends_at", "local_start", "local_end"}``.
            ``starts_at``/``ends_at`` are UTC (``2026-08-27T14:30:00Z``)
            and are what a booking call takes; ``local_start``/
            ``local_end`` are ``HH:MM`` in the clinic's own time and are
            what to say out loud. An empty list with ``is_open`` true
            means the clinic is open but has nothing free -- which is a
            different answer from being closed.

    Raises:
        ValidationError: If `clinic_id`, `date`, or `service` is missing or
            malformed, or if the clinic does not offer that service (the
            message lists the ones it does).
        NotFoundError: If no clinic exists with that `clinic_id`.
        ConfigurationError: If the clinic's stored availability config is
            unusable (bad timezone, malformed hours). A seeding/deployment
            fault, never something to read out to a patient.
    """
    # Tenant boundary first, before any read (`code-standards.md` -> Python).
    clinic_id = require_clinic_id(clinic_id)
    local_date = require_date(date, "date")

    clinic = get_clinic(clinic_id)
    zone = clinic_timezone(clinic)
    service_entry = resolve_service(clinic, service)
    slot_minutes = _positive_int(
        clinic.get(ClinicAttrs.SLOT_MINUTES), ClinicAttrs.SLOT_MINUTES, clinic_id
    )

    closure_label = _closure_label(clinic, local_date)
    intervals = (
        []
        if closure_label is not None
        else opening_intervals(clinic, local_date, zone)
    )

    slots: list[dict[str, str]] = []
    if intervals:
        # Only read appointments if the day could offer something: a closed
        # day costs no query at all.
        day_start = datetime.combine(local_date, datetime.min.time(), tzinfo=zone)
        booked = _booked_spans(
            clinic_id,
            day_start.astimezone(timezone.utc),
            (day_start + _ONE_DAY).astimezone(timezone.utc),
        )
        slots = _compute_slots(
            intervals=intervals,
            duration_minutes=service_entry[ServiceAttrs.DURATION_MINUTES],
            slot_minutes=slot_minutes,
            booked=booked,
            zone=zone,
        )

    return {
        CLINIC_ID: clinic_id,
        "date": local_date.strftime(DATE_FORMAT),
        ClinicAttrs.TIMEZONE: str(zone),
        "service": service_entry,
        "is_open": bool(intervals),
        "closure_label": closure_label,
        "slots": slots,
    }


# --------------------------------------------------------------------------
# Clinic config reads
# --------------------------------------------------------------------------


def get_clinic(clinic_id: str) -> dict[str, Any]:
    """Fetch one clinic's item, the starting point of every scheduling read.

    Args:
        clinic_id: The tenant. Validated here, so callers cannot skip it.

    Returns:
        The raw `Clinics` item. Numeric attributes come back as `Decimal`,
        as DynamoDB stores them -- read them through `_positive_int` rather
        than assuming `int`.

    Raises:
        ValidationError: If `clinic_id` is missing or blank.
        NotFoundError: If no such clinic exists.
    """
    clinic_id = require_clinic_id(clinic_id)
    response = clinics_table().get_item(Key={CLINIC_ID: clinic_id})
    item = response.get("Item")
    if not item:
        raise NotFoundError(f"No clinic found with clinic_id {clinic_id!r}.")
    return item


def resolve_service(clinic: dict[str, Any], service: str) -> dict[str, Any]:
    """Match a requested service against the clinic's own `services` list.

    Accepts either the service id or its name, case-insensitively, because
    the value reaches a tool from speech: the model may hand back "cleaning"
    when the clinic stores ``{"id": "cleaning", "name": "Dental cleaning"}``.
    Ids are matched first, so one entry's name can never shadow another
    entry's id. A service the clinic does not offer is a validation error,
    not a default (`architecture.md` -> Storage Model).

    Args:
        clinic: A clinic item from `get_clinic`.
        service: The requested service id or name.

    Returns:
        ``{"id", "name", "duration_minutes"}``, with `duration_minutes`
        coerced to `int`.

    Raises:
        ValidationError: If `service` is blank or is not one the clinic
            offers. The message lists the clinic's services, since the
            caller is usually a model that guessed.
        ConfigurationError: If the clinic has no usable `services` list.
    """
    wanted = require_text(
        service, "service", max_length=MAX_IDENTIFIER_LENGTH
    ).casefold()
    clinic_id = str(clinic.get(CLINIC_ID, ""))
    entries = clinic.get(ClinicAttrs.SERVICES)
    if not isinstance(entries, list) or not entries:
        raise ConfigurationError(
            f"Clinic {clinic_id!r} has no {ClinicAttrs.SERVICES} configured."
        )

    for key in (ServiceAttrs.ID, ServiceAttrs.NAME):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            candidate = entry.get(key)
            if isinstance(candidate, str) and candidate.strip().casefold() == wanted:
                return _service_entry(entry, clinic_id)

    offered = ", ".join(
        str(entry.get(ServiceAttrs.NAME, entry.get(ServiceAttrs.ID, "?")))
        for entry in entries
        if isinstance(entry, dict)
    )
    raise ValidationError(
        f"This clinic does not offer {service!r}. It offers: {offered}."
    )


def clinic_timezone(clinic: dict[str, Any]) -> ZoneInfo:
    """The clinic's IANA timezone: the frame `hours` and `closures` are read in.

    Args:
        clinic: A clinic item from `get_clinic`.

    Returns:
        The clinic's `ZoneInfo`.

    Raises:
        ConfigurationError: If it is missing or is not a zone this system
            knows. On Windows the zone database ships as the `tzdata`
            package (see `backend/requirements.txt`); without it every
            clinic would look misconfigured.
    """
    name = clinic.get(ClinicAttrs.TIMEZONE)
    clinic_id = str(clinic.get(CLINIC_ID, ""))
    if not isinstance(name, str) or not name.strip():
        raise ConfigurationError(
            f"Clinic {clinic_id!r} has no {ClinicAttrs.TIMEZONE}; its hours cannot "
            "be read without one."
        )
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ConfigurationError(
            f"Clinic {clinic_id!r} has an unknown {ClinicAttrs.TIMEZONE} {name!r}; "
            "expected an IANA name such as 'Europe/London'."
        ) from exc


def opening_intervals(
    clinic: dict[str, Any], local_date: date_type, zone: ZoneInfo
) -> list[tuple[datetime, datetime]]:
    """The clinic's opening intervals for one local date, as UTC instants.

    Converted to UTC here so every later comparison -- against stored
    appointments, against candidate slots -- is between absolute instants.
    Doing slot arithmetic in local wall-clock time instead would give the
    wrong span on a DST-transition day.

    Closures are *not* applied here; `check_availability` checks those
    first, because "closed for a holiday" and "does not open on Sundays"
    are different answers to the patient.

    Args:
        clinic: A clinic item from `get_clinic`.
        local_date: The clinic-local calendar date.
        zone: The clinic's timezone, from `clinic_timezone`.

    Returns:
        `(start, end)` pairs in UTC, ascending. Empty if the clinic does
        not open on that weekday.

    Raises:
        ConfigurationError: If `hours` is malformed for that weekday. The
            spec guarantees ascending, non-overlapping intervals with
            `close` after `open`; a violation would silently produce
            duplicate or impossible slots, so it fails loudly instead.
    """
    clinic_id = str(clinic.get(CLINIC_ID, ""))
    hours = clinic.get(ClinicAttrs.HOURS)
    if not isinstance(hours, dict):
        raise ConfigurationError(
            f"Clinic {clinic_id!r} has no usable {ClinicAttrs.HOURS} map."
        )
    key = weekday_key(local_date)
    day = hours.get(key)
    if day is None:
        return []
    if not isinstance(day, list):
        raise ConfigurationError(
            f"Clinic {clinic_id!r} {ClinicAttrs.HOURS}[{key!r}] must be a list of "
            f"{{{HoursInterval.OPEN}, {HoursInterval.CLOSE}}} intervals."
        )

    intervals: list[tuple[datetime, datetime]] = []
    previous_close: datetime | None = None
    for entry in day:
        if not isinstance(entry, dict):
            raise ConfigurationError(
                f"Clinic {clinic_id!r} {ClinicAttrs.HOURS}[{key!r}] contains a "
                f"non-interval entry {entry!r}."
            )
        opens = _local_instant(
            entry.get(HoursInterval.OPEN), local_date, zone, clinic_id, key
        )
        closes = _local_instant(
            entry.get(HoursInterval.CLOSE), local_date, zone, clinic_id, key
        )
        if closes <= opens:
            raise ConfigurationError(
                f"Clinic {clinic_id!r} {ClinicAttrs.HOURS}[{key!r}] has an interval "
                f"whose {HoursInterval.CLOSE} is not after its {HoursInterval.OPEN}."
            )
        if previous_close is not None and opens < previous_close:
            raise ConfigurationError(
                f"Clinic {clinic_id!r} {ClinicAttrs.HOURS}[{key!r}] intervals must "
                "be ascending and non-overlapping."
            )
        previous_close = closes
        intervals.append(
            (opens.astimezone(timezone.utc), closes.astimezone(timezone.utc))
        )
    return intervals


def _local_instant(
    value: Any, local_date: date_type, zone: ZoneInfo, clinic_id: str, weekday: str
) -> datetime:
    """Turn one ``HH:MM`` wall-clock string into an aware clinic-local instant."""
    if not isinstance(value, str):
        raise ConfigurationError(
            f"Clinic {clinic_id!r} {ClinicAttrs.HOURS}[{weekday!r}] has a non-string "
            f"time {value!r}; expected 24-hour HH:MM."
        )
    try:
        parsed = datetime.strptime(value.strip(), LOCAL_TIME_FORMAT).time()
    except ValueError as exc:
        raise ConfigurationError(
            f"Clinic {clinic_id!r} {ClinicAttrs.HOURS}[{weekday!r}] has an invalid "
            f"time {value!r}; expected 24-hour HH:MM."
        ) from exc
    return datetime.combine(local_date, parsed, tzinfo=zone)


def _closure_label(clinic: dict[str, Any], local_date: date_type) -> str | None:
    """The clinic's label for a whole-day closure on `local_date`, if any.

    Returns `None` when the day is not closed, and the (possibly empty)
    label when it is -- the two are distinguishable, which is what lets
    `check_availability` report *why* a day has no slots. A closure entry
    with an unparseable date is ignored rather than fatal: one bad entry
    must not take a clinic's whole calendar offline.
    """
    entries = clinic.get(ClinicAttrs.CLOSURES)
    if not isinstance(entries, list):
        return None
    target = local_date.strftime(DATE_FORMAT)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get(ClosureAttrs.DATE, "")).strip() == target:
            label = entry.get(ClosureAttrs.LABEL)
            return label.strip() if isinstance(label, str) and label.strip() else ""
    return None


def _service_entry(entry: dict[str, Any], clinic_id: str) -> dict[str, Any]:
    """Normalise one `services` entry into the shape the tools hand around."""
    service_id = entry.get(ServiceAttrs.ID)
    if not isinstance(service_id, str) or not service_id.strip():
        raise ConfigurationError(
            f"Clinic {clinic_id!r} has a service with no {ServiceAttrs.ID}."
        )
    service_id = service_id.strip()
    name = entry.get(ServiceAttrs.NAME)
    return {
        ServiceAttrs.ID: service_id,
        ServiceAttrs.NAME: (
            name.strip() if isinstance(name, str) and name.strip() else service_id
        ),
        ServiceAttrs.DURATION_MINUTES: _positive_int(
            entry.get(ServiceAttrs.DURATION_MINUTES),
            f"{ClinicAttrs.SERVICES}[{service_id}].{ServiceAttrs.DURATION_MINUTES}",
            clinic_id,
        ),
    }


def _positive_int(value: Any, field: str, clinic_id: str) -> int:
    """Coerce a stored numeric config value to a positive `int`.

    DynamoDB hands numbers back as `Decimal`, so this is not optional
    tidying: `timedelta(minutes=Decimal("15"))` raises.

    Raises:
        ConfigurationError: If missing, non-numeric, or not positive.
    """
    if isinstance(value, bool) or not isinstance(value, (int, Decimal, float, str)):
        raise ConfigurationError(
            f"Clinic {clinic_id!r} has a missing or non-numeric {field}: {value!r}."
        )
    try:
        number = int(Decimal(str(value)))
    except (ArithmeticError, ValueError) as exc:
        raise ConfigurationError(
            f"Clinic {clinic_id!r} has a non-numeric {field}: {value!r}."
        ) from exc
    if number <= 0:
        raise ConfigurationError(
            f"Clinic {clinic_id!r} has a non-positive {field}: {value!r}."
        )
    return number


# --------------------------------------------------------------------------
# Existing appointments
# --------------------------------------------------------------------------


def _booked_spans(
    clinic_id: str, window_start: datetime, window_end: datetime
) -> list[tuple[datetime, datetime]]:
    """The `(start, end)` spans already occupied in one clinic's time window.

    Queries the `by-start-time` index, whose partition key is `clinic_id`
    itself -- the query cannot be widened past one tenant
    (`architecture.md` -> Invariants #1).

    Only `starts_at` is a key, so this finds appointments *starting* in the
    window. That is sufficient rather than lucky: an appointment must fit
    entirely inside one of its day's opening intervals, and an interval
    cannot cross local midnight (`close` is after `open` on the same date),
    so nothing starting before the window can still be running inside it.

    Statuses are filtered here rather than by a DynamoDB `FilterExpression`
    -- one clinic-day is a handful of items, and keeping the rule in
    `ACTIVE_APPOINTMENT_STATUSES` means adding a status stays one edit.
    """
    # Lazy, mirroring `dynamo._dynamodb_resource`: importing this module
    # must not require the AWS SDK, so the interval logic stays testable
    # without it.
    from boto3.dynamodb.conditions import Key  # noqa: PLC0415

    table = appointments_table()
    query: dict[str, Any] = {
        "IndexName": APPOINTMENTS_BY_START_TIME_INDEX,
        "KeyConditionExpression": Key(CLINIC_ID).eq(clinic_id)
        & Key(STARTS_AT).between(to_iso8601(window_start), to_iso8601(window_end)),
    }
    spans: list[tuple[datetime, datetime]] = []
    while True:
        response = table.query(**query)
        for item in response.get("Items", []):
            span = _appointment_span(item)
            if span is not None:
                spans.append(span)
        next_key = response.get("LastEvaluatedKey")
        if not next_key:
            return spans
        query["ExclusiveStartKey"] = next_key


def _appointment_span(item: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """One appointment's occupied span, or `None` if it does not occupy one.

    Cancelled, completed, and no-show appointments stay in the table as
    history but free their time (`ACTIVE_APPOINTMENT_STATUSES`).
    """
    raw_status = str(item.get(AppointmentAttrs.STATUS, "")).strip()
    try:
        status: AppointmentStatus | None = AppointmentStatus(raw_status)
    except ValueError:
        # An unrecognised status is treated as still occupying its slot:
        # offering a slot that is actually taken is the worse mistake.
        status = None
    if status is not None and status not in ACTIVE_APPOINTMENT_STATUSES:
        return None

    starts_at = item.get(AppointmentAttrs.STARTS_AT)
    if not isinstance(starts_at, str):
        return None
    start = from_iso8601(starts_at)
    ends_at = item.get(AppointmentAttrs.ENDS_AT)
    if isinstance(ends_at, str):
        try:
            return start, from_iso8601(ends_at)
        except ValidationError:
            pass
    # `book_appointment` always writes `ends_at`, so a missing one is bad
    # data rather than a supported shape. `_overlaps` blocks the slot
    # containing a degenerate span rather than dropping the appointment.
    return start, start


# --------------------------------------------------------------------------
# Slot composition
# --------------------------------------------------------------------------


def _compute_slots(
    *,
    intervals: list[tuple[datetime, datetime]],
    duration_minutes: int,
    slot_minutes: int,
    booked: list[tuple[datetime, datetime]],
    zone: ZoneInfo,
) -> list[dict[str, str]]:
    """Apply the composition rule from `architecture.md` -> Storage Model.

    Candidate starts are generated on the `slot_minutes` grid counted from
    each interval's own open; a candidate survives only if the whole
    `duration_minutes` fits inside *that same* interval and overlaps
    nothing booked. The grid places starts and the duration decides fit,
    which is why `duration_minutes` need not be a multiple of
    `slot_minutes`.
    """
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=slot_minutes)
    slots: list[dict[str, str]] = []
    for interval_start, interval_end in intervals:
        cursor = interval_start
        while cursor + duration <= interval_end:
            candidate_end = cursor + duration
            if not any(
                _overlaps(cursor, candidate_end, start, end) for start, end in booked
            ):
                slots.append(
                    {
                        AppointmentAttrs.STARTS_AT: to_iso8601(cursor),
                        AppointmentAttrs.ENDS_AT: to_iso8601(candidate_end),
                        "local_start": cursor.astimezone(zone).strftime(
                            LOCAL_TIME_FORMAT
                        ),
                        "local_end": candidate_end.astimezone(zone).strftime(
                            LOCAL_TIME_FORMAT
                        ),
                    }
                )
            cursor += step
    return slots


def _overlaps(
    candidate_start: datetime,
    candidate_end: datetime,
    booked_start: datetime,
    booked_end: datetime,
) -> bool:
    """Whether a candidate slot collides with an already-booked span.

    Half-open, so an appointment ending at 10:00 does not block one
    starting at 10:00. A degenerate booked span (bad data, no `ends_at`)
    still blocks the slot containing its start -- the conservative choice,
    since offering a taken slot is worse than withholding a free one.
    """
    if booked_end <= booked_start:
        return candidate_start <= booked_start < candidate_end
    return candidate_start < booked_end and booked_start < candidate_end
