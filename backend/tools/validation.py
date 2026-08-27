"""Boundary checks every tool runs before it touches data.

`code-standards.md` -> Python makes two demands this module exists to
satisfy: every tool function validates that its `clinic_id` argument is
present and non-empty *before doing anything else* (the tenant-isolation
boundary), and all external input is validated at the boundary because
tool arguments are derived from patient speech and cannot be assumed
well-formed.

Every function here returns the cleaned value rather than just asserting,
so callers use the normalised form and cannot accidentally keep using the
raw one -- e.g. the phone number that reaches the `by-phone` index is
always the normalised string, never whatever the model transcribed.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from .errors import ValidationError
from .schema import CLINIC_ID, DATE_FORMAT, ISO8601_FORMAT, to_iso8601

# DynamoDB caps an item at 400 KB. These bounds are far below that: they
# exist to stop a mis-generated tool argument (a model pasting a whole
# transcript into `notes`) from being stored, not to enforce a product
# rule.
MAX_IDENTIFIER_LENGTH = 128
MAX_TEXT_LENGTH = 2000

# E.164 allows at most 15 digits; 7 is the shortest plausible real number.
MIN_PHONE_DIGITS = 7
MAX_PHONE_DIGITS = 15

# RFC 5321's cap on a whole address.
MAX_EMAIL_LENGTH = 254


def require_clinic_id(clinic_id: str | None) -> str:
    """Validate the tenant argument. Call this first in every tool function.

    This is the tenant-isolation boundary (`architecture.md` ->
    Invariants #1): a tool that ran with a blank or missing `clinic_id`
    would either fail confusingly or, worse, build a query key that
    matched another clinic's data.

    Args:
        clinic_id: The active session's clinic, passed explicitly by the
            caller. Never defaulted, never inferred.

    Returns:
        The trimmed clinic id.

    Raises:
        ValidationError: If it is missing, blank, or not a string.
    """
    return require_identifier(clinic_id, CLINIC_ID)


def require_identifier(value: str | None, field: str) -> str:
    """Validate an id-shaped argument (`clinic_id`, `patient_id`, ...).

    Args:
        value: The candidate id.
        field: Attribute name, used in the error message so a failure
            names the argument the model got wrong.

    Returns:
        The trimmed id.

    Raises:
        ValidationError: If it is missing, blank, not a string, or longer
            than `MAX_IDENTIFIER_LENGTH`.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required and must be a non-empty string.")
    cleaned = value.strip()
    if len(cleaned) > MAX_IDENTIFIER_LENGTH:
        raise ValidationError(
            f"{field} must be at most {MAX_IDENTIFIER_LENGTH} characters."
        )
    return cleaned


def require_text(value: str | None, field: str, *, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Validate a free-text argument (a service name, a note, a reason).

    Args:
        value: The candidate text.
        field: Attribute name, used in the error message.
        max_length: Upper bound, defaulting to `MAX_TEXT_LENGTH`.

    Returns:
        The trimmed text.

    Raises:
        ValidationError: If it is missing, blank, not a string, or too long.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required and must be a non-empty string.")
    cleaned = value.strip()
    if len(cleaned) > max_length:
        raise ValidationError(f"{field} must be at most {max_length} characters.")
    return cleaned


def require_timestamp(value: str | None, field: str) -> str:
    """Validate a timestamp argument and normalise it to `ISO8601_FORMAT`.

    Accepts any ISO-8601 string Python can parse (including a `Z` suffix
    or a numeric offset) and returns this project's single encoding, so a
    value that reaches a sort key is always comparable with the values
    already stored there. A naive value is read as UTC.

    Args:
        value: The candidate timestamp.
        field: Attribute name, used in the error message.

    Returns:
        The timestamp in `ISO8601_FORMAT`, e.g. ``2026-08-27T14:30:00Z``.

    Raises:
        ValidationError: If it is missing, not a string, or unparseable.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required and must be a non-empty string.")
    candidate = value.strip()
    try:
        # `fromisoformat` handles `Z` from Python 3.11 onward; this project
        # is pinned to 3.12+ (`code-standards.md` -> Python).
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValidationError(
            f"{field} must be an ISO-8601 timestamp such as "
            f"{datetime(2026, 1, 1).strftime(ISO8601_FORMAT)}; got {candidate!r}."
        ) from exc
    return to_iso8601(parsed)


def require_date(value: str | None, field: str) -> date:
    """Validate a calendar-date argument and return it as a `date`.

    A date is deliberately not a timestamp: "the 27th" means the clinic's
    local day, and only `tools.scheduling` may turn it into UTC instants
    (`architecture.md` -> Storage Model). Returning a `date` rather than a
    string is what stops a caller from accidentally comparing it against a
    stored UTC value.

    A full ISO-8601 timestamp is accepted and truncated to its date, since
    a model asked for "a date" often produces one.

    Args:
        value: The candidate date, e.g. ``2026-08-27``.
        field: Argument name, used in the error message.

    Returns:
        The parsed `datetime.date`.

    Raises:
        ValidationError: If it is missing, not a string, or unparseable.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required and must be a non-empty string.")
    candidate = value.strip()
    try:
        return datetime.strptime(candidate, DATE_FORMAT).date()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(candidate).date()
    except ValueError as exc:
        raise ValidationError(
            f"{field} must be a calendar date in the form "
            f"{datetime(2026, 1, 1).strftime(DATE_FORMAT)}; got {candidate!r}."
        ) from exc


def require_bounded_int(
    value: object, field: str, *, minimum: int, maximum: int, default: int
) -> int:
    """Validate an optional count argument against a hard range.

    Exists for arguments a model *chooses a number for* rather than reads
    off an item -- a look-ahead length, a page size. Three things follow
    from that and none of them are defensive padding:

    * `None` means "not supplied" and yields `default`, so a tool can keep
      a sensible single-unit behaviour when the model omits the argument.
    * A digit string or a `Decimal` is accepted, because a value can reach
      a tool as `"7"` from a model or as `Decimal("7")` from DynamoDB.
    * Out of range is a `ValidationError`, not a silent clamp: a model that
      asked for 365 has misunderstood the tool, and quietly answering for
      14 would hide that from it. The message states the range so the
      retry is informed.

    Args:
        value: The candidate count, or `None` to take the default.
        field: Argument name, used in the error message.
        minimum: Smallest accepted value, inclusive.
        maximum: Largest accepted value, inclusive.
        default: Returned when `value` is `None`.

    Returns:
        The count as an `int`.

    Raises:
        ValidationError: If it is not a whole number, or is outside
            `minimum`..`maximum`.
    """
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, Decimal, float, str)):
        raise ValidationError(f"{field} must be a whole number; got {value!r}.")
    try:
        number = Decimal(str(value).strip())
    except ArithmeticError as exc:
        raise ValidationError(
            f"{field} must be a whole number; got {value!r}."
        ) from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise ValidationError(f"{field} must be a whole number; got {value!r}.")
    count = int(number)
    if not minimum <= count <= maximum:
        raise ValidationError(
            f"{field} must be between {minimum} and {maximum}; got {count}."
        )
    return count


def require_enum[E: StrEnum](value: str | E | None, enum_cls: type[E], field: str) -> E:
    """Validate that a value is one of a fixed vocabulary in `schema`.

    Args:
        value: The candidate, as either the enum member or its string.
        enum_cls: The `StrEnum` defining the allowed values.
        field: Attribute name, used in the error message.

    Returns:
        The matching enum member.

    Raises:
        ValidationError: If the value is not in the vocabulary. The message
            lists the allowed values, since the caller is often a model
            that guessed.
    """
    if isinstance(value, str):
        try:
            return enum_cls(value.strip().lower())
        except ValueError:
            pass
    allowed = ", ".join(member.value for member in enum_cls)
    raise ValidationError(f"{field} must be one of: {allowed}; got {value!r}.")


def normalise_phone(value: str | None, field: str = "phone") -> str:
    """Validate a phone number and reduce it to one canonical form: its digits.

    The `by-phone` index does an equality match on the stored string, so
    every way of writing one number has to collapse to one key here or
    `patients.find_patients_by_phone` silently misses a returning caller.
    Digits are kept and everything else -- spaces, brackets, dashes, and a
    leading ``+`` -- is dropped.

    The ``+`` is dropped rather than preserved *because* it is not a digit:
    keeping it conditionally (as this function first did) made
    ``"+1 555 123 4567"`` and ``"1-555-123-4567"`` two different keys for
    one number, which is exactly the miss this normalisation exists to
    prevent. Nothing reads the stored value as an E.164 address -- it is a
    lookup key and a string staff may read -- so the marker costs a
    correctness bug and buys nothing.

    What this does **not** do is reconcile a national number with its
    international form: ``"555 123 4567"`` and ``"+1 555 123 4567"`` stay
    distinct, because turning the first into the second requires assuming
    a country, which no context file specifies. See `progress-tracker.md`
    -> Open Questions.

    This is storage normalisation, not validation of real-world
    reachability -- no country/carrier check is performed.

    Args:
        value: The candidate number, from speech or from a seed script.
        field: Attribute name, used in the error message.

    Returns:
        The number's digits, in order, with nothing else.

    Raises:
        ValidationError: If it is missing, or has an implausible number of
            digits (see `MIN_PHONE_DIGITS`/`MAX_PHONE_DIGITS`).
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field} is required and must be a non-empty string.")
    raw = value.strip()
    digits = "".join(character for character in raw if character.isdigit())
    if not MIN_PHONE_DIGITS <= len(digits) <= MAX_PHONE_DIGITS:
        raise ValidationError(
            f"{field} must contain between {MIN_PHONE_DIGITS} and "
            f"{MAX_PHONE_DIGITS} digits; got {raw!r}."
        )
    return digits


def normalise_email(value: str | None, field: str = "email") -> str:
    """Validate an email address and trim it, without pretending to verify it.

    A deliberately shallow check: one ``@``, something either side, no
    whitespace, within RFC 5321's length cap. It exists to stop a
    transcription artefact ("dave at gmail dot com") from being stored as
    a patient's contact address, not to decide whether mail would arrive
    -- only SES can answer that, and an over-strict regex here would
    reject valid addresses a patient actually owns.

    Args:
        value: The candidate address, from speech or from a seed script.
        field: Attribute name, used in the error message.

    Returns:
        The trimmed address, as given. Case is preserved: the local part
        of an address is case-sensitive by the standard, and nothing here
        needs to match two addresses against each other.

    Raises:
        ValidationError: If it is missing, blank, over-long, or not
            recognisably an address.
    """
    cleaned = require_text(value, field, max_length=MAX_EMAIL_LENGTH)
    local, separator, domain = cleaned.partition("@")
    if not separator or not local or not domain or "@" in domain:
        raise ValidationError(
            f"{field} must be an email address such as 'name@example.com'; "
            f"got {cleaned!r}."
        )
    if any(character.isspace() for character in cleaned):
        raise ValidationError(f"{field} must not contain spaces; got {cleaned!r}.")
    return cleaned
