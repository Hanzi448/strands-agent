"""What a tool hands back to the model when the tool layer refuses.

`tools/errors.py` says tools raise rather than return error strings, and
that "the agent wrappers in `backend/agents/` translate them into
model-readable responses". This is that translation, in one place so
every sub-agent refuses in the same voice.

Two rules shape it.

**A refusal must reach the model as a refusal.** Strands treats whatever
a `@tool` function returns as a success unless the returned dict carries
`status` and `content` itself, in which case it is passed through
verbatim (`strands/tools/decorator.py`). So a failure is returned in that
shape rather than as an ordinary payload -- a model handed
`{"error": ...}` under a green "success" is a model that may read it out
as an answer.

**A deployment fault is not a patient's business.** `ValidationError`,
`NotFoundError` and `ConflictError` are all things the *patient* can
answer -- a name that does not match, a slot that has gone, an
appointment that needs naming -- and the tool layer already writes their
messages for the model, naming the alternatives. `ConfigurationError` is
none of those: it means the clinic's stored config is broken, and its
message quotes internal attribute paths. It is logged and replaced.

An unexpected exception is treated the same way. Letting it escape would
hand Strands' own handler a `f"Error: {type} - {message}"` string built
from the traceback, which then goes to a speech model with a microphone
open. Catching it here is a boundary concern, not a workaround for a bug:
the bug still surfaces, in the log, with its stack.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from tools.errors import ConfigurationError, ToolError

logger = logging.getLogger(__name__)

# What the model is told when the failure is ours rather than the
# patient's. It has to do three jobs: stop the model retrying (a broken
# clinic config is broken on the second call too), stop it inventing an
# answer, and leave it holding something to say out loud. It does not
# tell the model to escalate: raising an escalation is the Orchestrator's
# decision via the Escalation sub-agent, not a sub-agent's to take on its
# own (`architecture.md` -> Invariants #2 and #6).
INTERNAL_FAILURE_MESSAGE = (
    "This clinic's booking system could not complete that request, for a"
    " reason the patient cannot do anything about. Do not retry it and do"
    " not guess an answer. Tell the patient you are not able to do that"
    " right now and that a member of staff will follow up, and report back"
    " that this needs a human."
)


def error_result(message: str) -> dict[str, Any]:
    """Wrap `message` as a tool result the model reads as a failure.

    Args:
        message: What the model should be told. Written for the model --
            the tool layer's own messages already are.

    Returns:
        A partial Strands `ToolResult`. `toolUseId` is filled in by the
        `@tool` decorator when it recognises this shape.
    """
    return {"status": "error", "content": [{"text": message}]}


def call[T](
    tool_name: str, function: Callable[..., T], /, **kwargs: Any
) -> T | dict[str, Any]:
    """Run one `backend/tools/` function and translate any failure.

    The single entry point every `@tool` wrapper goes through, so no
    wrapper can forget the translation or invent its own wording.

    Args:
        tool_name: The model-facing tool name, for the log line only.
        function: The tool-layer function to call.
        **kwargs: Its arguments, including the `clinic_id` the wrapper
            supplies from the session -- never from the model.

    Returns:
        Whatever `function` returned, on success; otherwise an
        `error_result`.
    """
    try:
        return function(**kwargs)
    except ConfigurationError:
        # A seeding or deployment fault. Logged with its message, which
        # names the offending attribute; the model gets none of that.
        logger.exception("%s: clinic configuration is unusable", tool_name)
        return error_result(INTERNAL_FAILURE_MESSAGE)
    except ToolError as error:
        # Validation, not-found and conflict: the message is already
        # written for the model, and a conflict's names the alternatives.
        logger.info("%s refused: %s", tool_name, error.message)
        return error_result(error.message)
    except Exception:
        logger.exception("%s failed unexpectedly", tool_name)
        return error_result(INTERNAL_FAILURE_MESSAGE)
