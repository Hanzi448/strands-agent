"""Tests for the tool-failure translation in `agents/results.py`.

Two properties matter here, and both are about what a patient ends up
hearing.

*A refusal must arrive as a refusal.* Strands reads a returned dict as a
success unless it carries `status` and `content` itself, so a failure
that comes back in the ordinary payload shape is a failure the model is
told went fine. Every branch below is asserted on that shape, not only on
the text.

*A broken deployment must not reach the patient.* `ConfigurationError`
messages quote internal attribute paths (`services[checkup].
duration_minutes`), and an unexpected exception carries whatever the
traceback says. Both are replaced; the assertions check the original text
is *absent*, not merely that a message was returned.
"""

from __future__ import annotations

import logging

import pytest

from agents.results import INTERNAL_FAILURE_MESSAGE, call, error_result
from tools.errors import (
    ConfigurationError,
    ConflictError,
    NotFoundError,
    ToolError,
    ValidationError,
)


def test_error_result_is_the_shape_strands_passes_through() -> None:
    """`status` + `content` is what stops the decorator marking it success."""
    result = error_result("no")
    assert result == {"status": "error", "content": [{"text": "no"}]}


def test_success_is_returned_untouched() -> None:
    """A working tool's payload must not be reshaped on the way out."""
    payload = {"slots": [], "is_open": False}
    assert call("check_availability", lambda **_: payload) is payload


def test_arguments_are_passed_through_by_keyword() -> None:
    """Including the `clinic_id` the wrapper supplies from the session."""
    seen: dict[str, object] = {}

    def record(**kwargs: object) -> str:
        seen.update(kwargs)
        return "ok"

    assert call("book_appointment", record, clinic_id="c1", starts_at="t") == "ok"
    assert seen == {"clinic_id": "c1", "starts_at": "t"}


@pytest.mark.parametrize(
    "error",
    [
        ValidationError("This clinic does not offer 'whitening'."),
        NotFoundError("You have nothing coming up to move."),
        ConflictError("09:00 has gone. 09:15 and 10:00 are still free."),
    ],
)
def test_a_patient_answerable_failure_keeps_its_message(error: ToolError) -> None:
    """These three are things the *patient* can answer, and the tool layer
    already writes them for the model -- a conflict's even names the
    alternatives. Rewording them here would throw that away."""

    def fail(**_: object) -> object:
        raise error

    assert call("check_availability", fail) == error_result(error.message)


def test_a_broken_clinic_config_is_replaced_not_forwarded() -> None:
    """A seeding fault is not something to read out to a patient."""

    def fail(**_: object) -> object:
        raise ConfigurationError(
            "Clinic 'clinic-dental' has a non-positive services[checkup]."
            "duration_minutes: Decimal('0')."
        )

    result = call("check_availability", fail)
    assert result == error_result(INTERNAL_FAILURE_MESSAGE)
    assert "duration_minutes" not in result["content"][0]["text"]


def test_an_unexpected_exception_is_replaced_too() -> None:
    """Otherwise Strands hands the model `Error: KeyError - 'starts_at'`,
    and a speech model reads it out with the microphone open."""

    def fail(**_: object) -> object:
        raise KeyError("starts_at")

    result = call("book_appointment", fail)
    assert result == error_result(INTERNAL_FAILURE_MESSAGE)
    assert "KeyError" not in result["content"][0]["text"]


def test_the_internal_message_tells_the_model_what_to_do_instead() -> None:
    """It has to stop the retry, stop the invention, and leave the model
    something to say -- a bare "an error occurred" does none of those."""
    text = INTERNAL_FAILURE_MESSAGE.lower()
    assert "do not retry" in text
    assert "do not guess" in text
    assert "staff" in text


@pytest.mark.parametrize(
    ("error", "level"),
    [
        (ConfigurationError("bad config"), logging.ERROR),
        (RuntimeError("boom"), logging.ERROR),
        (ConflictError("that slot has gone"), logging.INFO),
    ],
)
def test_every_failure_is_logged_at_the_right_level(
    error: Exception, level: int, caplog: pytest.LogCaptureFixture
) -> None:
    """The detail the patient does not get still has to reach the log --
    that is the whole basis for saying the bug "still surfaces"."""

    def fail(**_: object) -> object:
        raise error

    with caplog.at_level(logging.INFO, logger="agents.results"):
        call("cancel_appointment", fail)

    record = next(entry for entry in caplog.records if entry.name == "agents.results")
    assert record.levelno == level
    assert "cancel_appointment" in record.getMessage()


def test_the_configuration_log_keeps_the_detail_the_model_lost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The attribute path is the only thing that makes a seeding fault
    fixable, so dropping it from the model's answer must not drop it."""

    def fail(**_: object) -> object:
        raise ConfigurationError("Clinic 'c1' has a malformed hours.mon entry.")

    with caplog.at_level(logging.ERROR, logger="agents.results"):
        call("check_availability", fail)

    assert "hours.mon" in caplog.text
