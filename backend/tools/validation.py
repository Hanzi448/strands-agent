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

from datetime import datetime
from enum import StrEnum

from .errors import ValidationError
from .schema import CLINIC_ID, ISO8601_FORMAT, to_iso8601

# DynamoDB caps an item at 400 KB. These bounds are far below that: they
# exist to stop a mis-generated tool argument (a model pasting a whole
# transcript into `notes`) from being stored, not to enforce a product
# rule.
MAX_IDENTIFIER_LENGTH = 128
MAX_TEXT_LENGTH = 2000

# E.164 allows at most 15 digits; 7 is the shortest plausible real number.
MIN_PHONE_DIGITS = 7
MAX_PHONE_DIGITS = 15


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
    """Validate a phone number and reduce it to one canonical form.

    The `by-phone` index does an equality match on the stored string, so a
    number spoken as "555 123 4567" and one seeded as "+15551234567" have
    to converge here or the caller lookup silently misses. Digits are
    kept, a leading ``+`` is kept, and every separator is dropped.

    This is storage normalisation, not validation of real-world
    reachability -- no country/carrier check is performed.

    Args:
        value: The candidate number, from speech or from a seed script.
        field: Attribute name, used in the error message.

    Returns:
        ``+`` (if present in the input) followed by digits only.

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
    return f"+{digits}" if raw.startswith("+") else digits
