"""Cognito-protected REST handlers for the staff dashboard.

`architecture.md` -> System Boundaries names this module as one of three
Lambda entrypoints; `architecture.md` -> Auth and Access Model requires
every route to be scoped to the authenticated staff member's own clinic.
It holds no business logic of its own, for the same reason
`background_scan.py` holds none of `tools.automation`'s: routing,
auth-claim extraction and response shaping live here, and every read or
write is one call into `backend/tools/` (`code-standards.md` -> General).

**How `clinic_id` reaches a route.** `architecture.md` -> Auth and Access
Model says routes are "scoped to the authenticated staff member's clinic"
without saying how the token carries that -- so this module fixes it, the
same way `tools.schema` fixes a shape `architecture.md` deferred: one
Cognito user pool, one demo account per clinic
(`architecture.md` -> Stack), each seeded with a custom attribute,
``custom:clinic_id``. API Gateway's Cognito authorizer puts every claim
from the verified token onto `requestContext.authorizer.claims` before
this handler ever runs, so `_clinic_id_from` reads it from there and
nowhere else -- never from a path, query, or body parameter, which is
what stops a staff member typing another clinic's id into a request and
reading its data.

**Routing is a plain dict, not a framework.** `(httpMethod, resource)` to
a small function taking `(clinic_id, event)`, matching the API Gateway
REST proxy-integration shape `agentcore_app.py`'s FastAPI app does not
use, since this is a plain Lambda, not one running behind AgentCore.
`resource` is the *template* API Gateway sends (``/escalations/{id}``),
not the literal path, so the table does not grow with every escalation id
ever requested.

Every response is the `{ "data": ..., "error": ... }` shape
`code-standards.md` -> API Routes requires, exactly one of the two
populated. A `ToolError` is mapped to its HTTP status by `_STATUS_BY_ERROR`
and its message returned verbatim -- these are already the messages
`backend/tools/` wrote for a reader to act on, staff rather than a
patient, so nothing here paraphrases them. An exception `backend/tools/`
did not raise is logged in full and replaced with one fixed message,
for the reason `agents/results.py` does the same for the voice path: the
dashboard is not the place to render a stack trace either.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Callable

from tools.appointments import list_appointments_for_clinic
from tools.errors import (
    ConfigurationError,
    ConflictError,
    NotFoundError,
    ToolError,
    ValidationError,
)
from tools.escalations import get_escalation, list_open_escalations, resolve_escalation

logger = logging.getLogger(__name__)

# The Cognito custom attribute every seeded staff account carries -- see
# this module's docstring. Cognito prefixes a custom attribute's name with
# `custom:` in the claims it issues; the attribute itself is defined
# without that prefix wherever the user pool is provisioned.
CLINIC_ID_CLAIM = "custom:clinic_id"

_STATUS_BY_ERROR: dict[type[ToolError], int] = {
    ValidationError: 400,
    NotFoundError: 404,
    ConflictError: 409,
    ConfigurationError: 500,
}

_GENERIC_FAILURE_MESSAGE = (
    "Something went wrong handling that request. Check CloudWatch logs."
)


class _RouteNotFound(Exception):
    """No handler is registered for this request's method and resource."""


def handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    """Route one API Gateway request to a dashboard read or write.

    Args:
        event: An API Gateway REST API (Lambda proxy integration) event,
            behind a Cognito user pool authorizer.
        context: The Lambda context object. Unused; accepted so this
            matches the shape the Lambda runtime calls.

    Returns:
        A Lambda proxy response: `statusCode`, `headers`, and a `body`
        JSON string of `{"data": ..., "error": ...}` -- exactly one
        populated.
    """
    try:
        clinic_id = _clinic_id_from(event)
        route = _match_route(event)
        return _response(200, data=route(clinic_id, event))
    except _RouteNotFound:
        return _response(404, error="No such route.")
    except ToolError as exc:
        logger.warning("Dashboard API request failed: %s", exc)
        return _response(_STATUS_BY_ERROR.get(type(exc), 500), error=exc.message)
    except Exception:
        logger.exception("Unhandled error in dashboard API request")
        return _response(500, error=_GENERIC_FAILURE_MESSAGE)


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


def _clinic_id_from(event: dict[str, Any]) -> str:
    """Pull the caller's clinic out of their verified Cognito token.

    See this module's docstring for why `custom:clinic_id` is the claim
    and why nothing else on the request is consulted.

    Raises:
        ConfigurationError: If the claim is missing or blank -- an
            authorizer or seed-data fault, not a request one: a token API
            Gateway's Cognito authorizer accepted should always carry it.
    """
    claims = (
        (event.get("requestContext") or {}).get("authorizer") or {}
    ).get("claims") or {}
    clinic_id = claims.get(CLINIC_ID_CLAIM)
    if not isinstance(clinic_id, str) or not clinic_id.strip():
        raise ConfigurationError(
            f"No {CLINIC_ID_CLAIM!r} claim on the authenticated request; check "
            "the Cognito authorizer and the staff user's custom attribute."
        )
    return clinic_id.strip()


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


def _list_appointments(clinic_id: str, event: dict[str, Any]) -> dict[str, Any]:
    params = event.get("queryStringParameters") or {}
    return list_appointments_for_clinic(
        clinic_id, params.get("date"), limit=params.get("limit")
    )


def _list_escalations(clinic_id: str, event: dict[str, Any]) -> list[dict[str, Any]]:
    params = event.get("queryStringParameters") or {}
    return list_open_escalations(clinic_id, limit=params.get("limit"))


def _get_escalation(clinic_id: str, event: dict[str, Any]) -> dict[str, Any]:
    escalation_id = (event.get("pathParameters") or {}).get("escalation_id")
    return get_escalation(clinic_id, escalation_id)


def _resolve_escalation(clinic_id: str, event: dict[str, Any]) -> dict[str, Any]:
    escalation_id = (event.get("pathParameters") or {}).get("escalation_id")
    return resolve_escalation(clinic_id, escalation_id)


# `resource` is API Gateway's route *template*, not the literal request
# path -- `/escalations/{escalation_id}`, not `/escalations/esc_123`.
_ROUTES: dict[tuple[str, str], Callable[[str, dict[str, Any]], Any]] = {
    ("GET", "/appointments"): _list_appointments,
    ("GET", "/escalations"): _list_escalations,
    ("GET", "/escalations/{escalation_id}"): _get_escalation,
    ("POST", "/escalations/{escalation_id}/resolve"): _resolve_escalation,
}


def _match_route(event: dict[str, Any]) -> Callable[[str, dict[str, Any]], Any]:
    key = (event.get("httpMethod"), event.get("resource"))
    try:
        return _ROUTES[key]
    except KeyError as exc:
        raise _RouteNotFound from exc


# --------------------------------------------------------------------------
# Response shaping
# --------------------------------------------------------------------------


class _DecimalEncoder(json.JSONEncoder):
    """`json.dumps` support for the `Decimal`s a DynamoDB item comes back with.

    Whole-valued (every duration and count this layer stores) becomes an
    `int`; anything else becomes a `float` rather than failing to encode.
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, Decimal):
            return int(o) if o == o.to_integral_value() else float(o)
        return super().default(o)


def _response(
    status_code: int, *, data: Any = None, error: str | None = None
) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Authorization,Content-Type",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
	    },
        "body": json.dumps({"data": data, "error": error}, cls=_DecimalEncoder),
    }
