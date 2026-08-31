"""FAQ retrieval: passages from the clinic's own Bedrock Knowledge Base.

`backend/infra/agent_stack.py` provisions one Bedrock Knowledge Base per
demo clinic, isolated structurally (a separate Knowledge Base id per
clinic, never a shared one filtered by `clinic_id` --
`architecture.md` -> Invariants #1). This module is the tool-layer read
over it: `query_faq` resolves the caller's clinic to its own Knowledge
Base id and asks Bedrock Agent Runtime for the passages closest to the
question.

**`retrieve`, not `retrieve_and_generate`.** `progress-tracker.md` ->
Open Questions left this undecided pending this unit; resolved here in
`retrieve`'s favour, for the same reason every other function in
`backend/tools/` returns facts rather than phrased answers
(`code-standards.md` -> General, business logic never composes what a
patient hears -- that is the sub-agent's model's job). `retrieve_and_generate`
would put a second, hidden model choice inside this layer and a second
place an answer could drift from `ORCHESTRATOR_SYSTEM_PROMPT`'s honesty
rules. The cost is one more round trip inside `faq_agent`'s own turn
(retrieve, then let its model phrase the passages), which is the same
shape every other sub-agent already has.

**No relevant passage is a normal answer, not a failure.** An empty
result is returned with `found` false rather than raised as
`NotFoundError` -- exactly as `check_availability` returns an empty slot
list rather than failing, because "nothing matched" is a fact the
sub-agent's model has to hear and decide what to do with (answer plainly
that it does not know, or hand off to `escalation_agent`), not an
exception unwound past it.

**The Knowledge Base id is per-clinic configuration, not a query
filter.** It is read from one environment variable per clinic
(`knowledge_base_id_env_var`), the way `dynamo.table_name` reads a
table's name -- except a table is shared across every clinic and a
Knowledge Base is not, so the variable name is derived from the
`clinic_id` itself rather than being one of a fixed handful. A clinic
with nothing set is a `ConfigurationError`: unlike a table name, there is
no naming scheme this layer could derive a real Knowledge Base id from,
since the id does not exist until `agent_stack.py` deploys it.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from .errors import ConfigurationError
from .validation import require_bounded_int, require_clinic_id, require_text

# Env var prefix a clinic's Knowledge Base id is read from -- see
# `knowledge_base_id_env_var`.
KB_ID_ENV_PREFIX = "CLINICPILOT_KB_ID_"

# How many passages one `query_faq` call returns at most. A model can ask
# for fewer; asking for more than this is refused rather than silently
# clamped, for the reason `require_bounded_int` refuses `days=365` --
# `check_availability`'s look-ahead cap plays the same role.
DEFAULT_MAX_RESULTS = 3
MAX_MAX_RESULTS = 10


def knowledge_base_id_env_var(clinic_id: str) -> str:
    """The environment variable one clinic's Knowledge Base id is read from.

    Args:
        clinic_id: The clinic, e.g. ``clinic-dental``.

    Returns:
        ``CLINICPILOT_KB_ID_CLINIC_DENTAL`` for ``clinic-dental`` --
        `KB_ID_ENV_PREFIX` plus the id upper-cased with `-` turned to `_`,
        so `agent_stack.py`'s CDK deploy output has one obvious place to
        be exported to.
    """
    slug = clinic_id.strip().upper().replace("-", "_")
    return f"{KB_ID_ENV_PREFIX}{slug}"


def _resolve_knowledge_base_id(clinic_id: str) -> str:
    """Look up one clinic's Knowledge Base id, or fail loudly that none is set."""
    env_var = knowledge_base_id_env_var(clinic_id)
    kb_id = os.environ.get(env_var, "").strip()
    if not kb_id:
        raise ConfigurationError(
            f"No Bedrock Knowledge Base is configured for {clinic_id!r}; "
            f"set {env_var} to its Knowledge Base id."
        )
    return kb_id


@lru_cache(maxsize=1)
def _bedrock_agent_runtime_client():  # noqa: ANN202 - boto3 clients have no public type
    """The process-wide `bedrock-agent-runtime` client.

    Cached for the reason `dynamo._dynamodb_resource` is: building a boto3
    client is expensive enough to matter on a cold start and a voice turn.
    Imported lazily so this module stays importable -- and `query_faq`'s
    validation stays testable -- without the AWS SDK installed, exactly as
    `dynamo.py` imports `boto3` inside its own client builder.
    """
    import boto3  # noqa: PLC0415 - deliberate lazy import, see docstring

    return boto3.client("bedrock-agent-runtime")


def query_faq(clinic_id: str, question: str, max_results: object = None) -> dict[str, Any]:
    """Retrieve the passages from this clinic's Knowledge Base closest to a question.

    Use this for anything about prices, treatments, preparation, policies,
    or other information the clinic has published -- not for availability
    or booking, which `scheduling_agent` already answers precisely. This
    tool returns raw passages, not a phrased answer: read them and answer
    the patient in your own words, using only what they say. If nothing
    relevant comes back, say plainly that you do not have that
    information rather than guessing, and consider escalating if the
    patient needs a definite answer.

    Args:
        clinic_id: The clinic the caller is talking to. Required; never
            inferred or defaulted.
        question: The patient's question, as asked or lightly cleaned up.
        max_results: Optional. How many passages to return at most, up to
            `MAX_MAX_RESULTS`; defaults to `DEFAULT_MAX_RESULTS`.

    Returns:
        A dict with:
          - ``question``: the question as queried.
          - ``passages``: a list of ``{"text": str}`` entries, closest
            match first, empty when nothing relevant was found.
          - ``found``: whether `passages` is non-empty -- check this
            before answering rather than inferring it from an empty list.

    Raises:
        ValidationError: If `clinic_id` or `question` is missing or
            malformed, or `max_results` is out of range.
        ConfigurationError: If this clinic has no Knowledge Base id
            configured. A deployment fault; never read out to a patient.
    """
    # Tenant boundary first, before any read (`code-standards.md` -> Python).
    clinic_id = require_clinic_id(clinic_id)
    question_text = require_text(question, "question")
    wanted = require_bounded_int(
        max_results,
        "max_results",
        minimum=1,
        maximum=MAX_MAX_RESULTS,
        default=DEFAULT_MAX_RESULTS,
    )
    knowledge_base_id = _resolve_knowledge_base_id(clinic_id)

    response = _bedrock_agent_runtime_client().retrieve(
        knowledgeBaseId=knowledge_base_id,
        retrievalQuery={"text": question_text},
        retrievalConfiguration={
            "vectorSearchConfiguration": {"numberOfResults": wanted}
        },
    )

    passages = [
        {"text": text}
        for result in response.get("retrievalResults", [])
        if (text := _passage_text(result))
    ]
    return {
        "question": question_text,
        "passages": passages,
        "found": bool(passages),
    }


def _passage_text(result: dict[str, Any]) -> str:
    """Pull the readable text out of one `retrieve` result, or `""`."""
    content = result.get("content")
    text = content.get("text") if isinstance(content, dict) else None
    return text.strip() if isinstance(text, str) else ""
