"""Exception vocabulary for the tool layer.

Tools raise these rather than returning error strings, so a caller that
forgets to check a result fails loudly instead of feeding an error
message to a patient as if it were an answer. The agent wrappers in
`backend/agents/` translate them into model-readable responses.

Every error carries a stable `code` so the wrappers can branch on the
kind of failure without matching on message text.
"""

from __future__ import annotations


class ToolError(Exception):
    """Base class for every failure raised by `backend/tools/`."""

    code: str = "tool_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(ToolError):
    """A tool argument was missing, empty, or malformed.

    Raised at the boundary, before any data is read or written --
    `code-standards.md` -> Python requires speech-derived arguments to be
    validated before they reach business logic.
    """

    code = "validation_error"


class NotFoundError(ToolError):
    """The requested clinic, patient, or appointment does not exist.

    Also raised when an item exists under a *different* `clinic_id`: from
    the caller's side those cases are indistinguishable, and they must
    stay that way (`architecture.md` -> Invariants #1).
    """

    code = "not_found"


class ConflictError(ToolError):
    """The request is well-formed but conflicts with current state.

    For example, booking a slot that was taken between the availability
    check and the write, or cancelling an already-cancelled appointment.
    """

    code = "conflict"


class ConfigurationError(ToolError):
    """The process is missing configuration it cannot run without.

    A deployment fault, not a patient-request fault: a missing table-name
    environment variable, for instance. Never surfaced to a patient.
    """

    code = "configuration_error"
