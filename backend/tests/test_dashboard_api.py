"""Tests for `lambda/dashboard_api.py`, the staff dashboard's REST entrypoint.

`lambda` is a Python keyword, so this suite reaches the package through
`importlib.import_module`, as `test_background_scan.py` does. The handler
holds no business logic of its own -- it routes, pulls `clinic_id` off the
Cognito claims, and shapes a response -- so every test here monkeypatches
the tool-layer function a route calls rather than building a fake
DynamoDB table; `list_appointments_for_clinic` itself is exercised
against one in `test_appointments.py`.

Three properties carry the weight: `clinic_id` always comes from the
verified token and never from anything the caller supplied in the
request, a `ToolError` is translated to the right HTTP status without its
message being rewritten, and anything else -- a bug, not a tool failure --
never reaches the response as raw text.
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import pytest

from tools.errors import ConflictError, NotFoundError, ValidationError

dashboard_api = importlib.import_module("lambda.dashboard_api")

CLINIC_ID = "clinic-dental"


def cognito_event(
    method: str,
    resource: str,
    *,
    clinic_id: str | None = CLINIC_ID,
    path_params: dict[str, str] | None = None,
    query_params: dict[str, str] | None = None,
    claims_override: dict[str, Any] | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """One API Gateway REST proxy-integration event behind a Cognito authorizer."""
    claims: dict[str, Any] = {} if clinic_id is None else {"custom:clinic_id": clinic_id}
    if claims_override is not None:
        claims = claims_override
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": path_params,
        "queryStringParameters": query_params,
        "body": body,
        "requestContext": {"authorizer": {"claims": claims}},
    }


def body_of(response: dict[str, Any]) -> dict[str, Any]:
    return json.loads(response["body"])


# --------------------------------------------------------------------------
# Auth: clinic_id comes from the token, and only from the token
# --------------------------------------------------------------------------


def test_missing_clinic_claim_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dashboard_api, "list_open_escalations", lambda clinic_id, limit=None: []
    )
    response = dashboard_api.handler(
        cognito_event("GET", "/escalations", clinic_id=None)
    )
    assert response["statusCode"] == 500
    body = body_of(response)
    assert body["data"] is None
    assert "custom:clinic_id" in body["error"]


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_clinic_claim_is_also_a_configuration_error(
    blank: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = dashboard_api.handler(
        cognito_event("GET", "/escalations", claims_override={"custom:clinic_id": blank})
    )
    assert response["statusCode"] == 500


def test_a_clinic_id_smuggled_into_the_query_string_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the token's claim reaches the tool layer -- `architecture.md` -> #1."""
    captured: dict[str, Any] = {}

    def fake_list(clinic_id: str, limit: object = None) -> list[dict[str, Any]]:
        captured["clinic_id"] = clinic_id
        return []

    monkeypatch.setattr(dashboard_api, "list_open_escalations", fake_list)
    dashboard_api.handler(
        cognito_event(
            "GET",
            "/escalations",
            clinic_id="clinic-dental",
            query_params={"clinic_id": "clinic-cosmetic"},
        )
    )
    assert captured["clinic_id"] == "clinic-dental"


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------


def test_list_appointments_route_forwards_clinic_id_and_query_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_list(
        clinic_id: str, date: str | None = None, *, limit: object = None
    ) -> dict[str, Any]:
        captured.update(clinic_id=clinic_id, date=date, limit=limit)
        return {"appointments": [{"appointment_id": "apt_1"}]}

    monkeypatch.setattr(dashboard_api, "list_appointments_for_clinic", fake_list)
    response = dashboard_api.handler(
        cognito_event(
            "GET",
            "/appointments",
            query_params={"date": "2026-07-01", "limit": "5"},
        )
    )
    assert response["statusCode"] == 200
    assert captured == {"clinic_id": CLINIC_ID, "date": "2026-07-01", "limit": "5"}
    assert body_of(response) == {
        "data": {"appointments": [{"appointment_id": "apt_1"}]},
        "error": None,
    }


def test_list_appointments_route_defaults_date_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `date` query param -- the tool layer resolves the clinic's "today"."""
    captured: dict[str, Any] = {}

    def fake_list(
        clinic_id: str, date: str | None = None, *, limit: object = None
    ) -> dict[str, Any]:
        captured["date"] = date
        return {"appointments": []}

    monkeypatch.setattr(dashboard_api, "list_appointments_for_clinic", fake_list)
    dashboard_api.handler(cognito_event("GET", "/appointments"))
    assert captured["date"] is None


def test_list_escalations_route(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_list(clinic_id: str, limit: object = None) -> list[dict[str, Any]]:
        captured.update(clinic_id=clinic_id, limit=limit)
        return [{"escalation_id": "esc_1"}]

    monkeypatch.setattr(dashboard_api, "list_open_escalations", fake_list)
    response = dashboard_api.handler(cognito_event("GET", "/escalations"))
    assert response["statusCode"] == 200
    assert captured == {"clinic_id": CLINIC_ID, "limit": None}
    assert body_of(response) == {"data": [{"escalation_id": "esc_1"}], "error": None}


def test_get_escalation_route_forwards_the_path_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_get(clinic_id: str, escalation_id: str) -> dict[str, Any]:
        captured.update(clinic_id=clinic_id, escalation_id=escalation_id)
        return {"escalation_id": escalation_id}

    monkeypatch.setattr(dashboard_api, "get_escalation", fake_get)
    response = dashboard_api.handler(
        cognito_event(
            "GET", "/escalations/{escalation_id}", path_params={"escalation_id": "esc_1"}
        )
    )
    assert response["statusCode"] == 200
    assert captured == {"clinic_id": CLINIC_ID, "escalation_id": "esc_1"}


def test_resolve_escalation_route_forwards_the_path_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_resolve(clinic_id: str, escalation_id: str) -> dict[str, Any]:
        captured.update(clinic_id=clinic_id, escalation_id=escalation_id)
        return {"escalation_id": escalation_id, "status": "resolved"}

    monkeypatch.setattr(dashboard_api, "resolve_escalation", fake_resolve)
    response = dashboard_api.handler(
        cognito_event(
            "POST",
            "/escalations/{escalation_id}/resolve",
            path_params={"escalation_id": "esc_1"},
        )
    )
    assert response["statusCode"] == 200
    assert captured == {"clinic_id": CLINIC_ID, "escalation_id": "esc_1"}
    assert body_of(response)["data"]["status"] == "resolved"


def test_unknown_route_is_a_404(monkeypatch: pytest.MonkeyPatch) -> None:
    response = dashboard_api.handler(cognito_event("DELETE", "/appointments"))
    assert response["statusCode"] == 404
    assert body_of(response)["data"] is None


def test_missing_escalation_id_path_parameter_is_a_validation_error() -> None:
    """No path parameter reaches the real `get_escalation`, unmocked.

    `require_identifier` rejects `None` before any table read, so this
    reaches `tools.escalations.get_escalation` itself rather than a fake --
    proving the route does not need its own presence check.
    """
    response = dashboard_api.handler(
        cognito_event("GET", "/escalations/{escalation_id}", path_params=None)
    )
    assert response["statusCode"] == 400


# --------------------------------------------------------------------------
# Error mapping
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ValidationError("bad limit"), 400),
        (NotFoundError("no such escalation"), 404),
        (ConflictError("already resolved"), 409),
    ],
)
def test_tool_errors_map_to_their_status_and_keep_their_message(
    error: Exception, status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_list(clinic_id: str, limit: object = None) -> list[dict[str, Any]]:
        raise error

    monkeypatch.setattr(dashboard_api, "list_open_escalations", fake_list)
    response = dashboard_api.handler(cognito_event("GET", "/escalations"))
    assert response["statusCode"] == status
    body = body_of(response)
    assert body["data"] is None
    assert body["error"] == str(error)


def test_an_unexpected_exception_never_reaches_the_response_as_raw_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_list(clinic_id: str, limit: object = None) -> list[dict[str, Any]]:
        raise KeyError("starts_at")

    monkeypatch.setattr(dashboard_api, "list_open_escalations", fake_list)
    response = dashboard_api.handler(cognito_event("GET", "/escalations"))
    assert response["statusCode"] == 500
    body = body_of(response)
    assert body["data"] is None
    assert "starts_at" not in body["error"]


# --------------------------------------------------------------------------
# Response shape
# --------------------------------------------------------------------------


def test_decimal_values_serialise_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal

    def fake_list(clinic_id: str, limit: object = None) -> list[dict[str, Any]]:
        return [{"duration_minutes": Decimal("30"), "rate": Decimal("2.5")}]

    monkeypatch.setattr(dashboard_api, "list_open_escalations", fake_list)
    response = dashboard_api.handler(cognito_event("GET", "/escalations"))
    body = body_of(response)
    assert body["data"] == [{"duration_minutes": 30, "rate": 2.5}]


def test_success_response_always_has_a_null_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        dashboard_api, "list_open_escalations", lambda clinic_id, limit=None: []
    )
    response = dashboard_api.handler(cognito_event("GET", "/escalations"))
    assert body_of(response)["error"] is None


# --------------------------------------------------------------------------
# Settings routes: the clinic config the Settings tab reads and writes
# --------------------------------------------------------------------------

SETTINGS_BODY = {
    "hours": {
        "mon": [{"open": "09:00", "close": "17:00"}],
        "tue": [{"open": "09:00", "close": "17:00"}],
        "wed": [],
        "thu": [{"open": "09:00", "close": "17:00"}],
        "fri": [{"open": "09:00", "close": "17:00"}],
        "sat": [],
        "sun": [],
    },
    "closures": [],
    "services": [{"id": "checkup", "name": "Check-up", "duration_minutes": 20}],
    "slot_minutes": 20,
}


def test_get_settings_returns_the_config_for_the_token_clinic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_get(clinic_id: str) -> dict[str, Any]:
        captured["clinic_id"] = clinic_id
        return {"name": "Bright Smile Dental", "slot_minutes": 15}

    monkeypatch.setattr(dashboard_api, "get_clinic_config", fake_get)
    response = dashboard_api.handler(cognito_event("GET", "/settings"))
    assert response["statusCode"] == 200
    assert captured["clinic_id"] == CLINIC_ID
    assert body_of(response)["data"]["slot_minutes"] == 15


def test_put_settings_forwards_the_four_fields_and_the_token_clinic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_update(clinic_id: str, **fields: Any) -> dict[str, Any]:
        captured.update(clinic_id=clinic_id, **fields)
        return {"name": "Bright Smile Dental", **fields}

    monkeypatch.setattr(dashboard_api, "update_clinic_config", fake_update)
    response = dashboard_api.handler(
        cognito_event("PUT", "/settings", body=json.dumps(SETTINGS_BODY))
    )
    assert response["statusCode"] == 200
    assert captured == {"clinic_id": CLINIC_ID, **SETTINGS_BODY}
    assert body_of(response)["data"]["slot_minutes"] == 20


def test_a_clinic_id_in_the_settings_body_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same rule as the query-string test above: only the token's claim
    reaches the tool layer (`architecture.md` -> Invariants #1)."""
    captured: dict[str, Any] = {}

    def fake_update(clinic_id: str, **fields: Any) -> dict[str, Any]:
        captured.update(clinic_id=clinic_id, fields=fields)
        return {}

    monkeypatch.setattr(dashboard_api, "update_clinic_config", fake_update)
    smuggled = {**SETTINGS_BODY, "clinic_id": "clinic-cosmetic"}
    dashboard_api.handler(
        cognito_event("PUT", "/settings", body=json.dumps(smuggled))
    )
    assert captured["clinic_id"] == CLINIC_ID
    assert "clinic_id" not in captured["fields"]


@pytest.mark.parametrize("body", [None, "", "{not json"])
def test_an_unparseable_settings_body_is_a_400_not_a_500(
    body: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route owns its own body parsing, so an unreadable body is the
    caller's fault, not an internal error."""
    monkeypatch.setattr(
        dashboard_api, "update_clinic_config", lambda *a, **k: pytest.fail(
            "no write should happen for an unreadable body"
        )
    )
    response = dashboard_api.handler(cognito_event("PUT", "/settings", body=body))
    assert response["statusCode"] == 400
    assert body_of(response)["data"] is None


def test_settings_validation_errors_reach_the_form_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool layer's message is what the form shows next to the field,
    so it passes through untranslated, like every other tool error here."""

    def fake_update(clinic_id: str, **fields: Any) -> dict[str, Any]:
        raise ValidationError("hours.mon must close strictly after it opens.")

    monkeypatch.setattr(dashboard_api, "update_clinic_config", fake_update)
    response = dashboard_api.handler(
        cognito_event("PUT", "/settings", body=json.dumps(SETTINGS_BODY))
    )
    assert response["statusCode"] == 400
    assert (
        body_of(response)["error"] == "hours.mon must close strictly after it opens."
    )


def test_every_response_allows_put_in_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    """The settings save is a PUT; a CORS allow-list without it would make
    every save fail in the browser with a preflight error no amount of
    frontend code can catch."""
    monkeypatch.setattr(
        dashboard_api, "get_clinic_config", lambda clinic_id: {}
    )
    response = dashboard_api.handler(cognito_event("GET", "/settings"))
    assert "PUT" in response["headers"]["Access-Control-Allow-Methods"]
