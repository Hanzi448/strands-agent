"""Tests for `lambda/background_scan.py`, the EventBridge entrypoint.

`lambda` is a Python keyword, so this suite reaches the package through
`importlib.import_module` rather than an ordinary `import`/`from`
statement -- see `architecture.md` -> System Boundaries. That is the only
thing unusual here: the handler itself is asserted the same way
`agentcore_app.py`'s thin routing is -- that it forwards to the tool layer
and does nothing else, and that a failure is logged before it propagates
rather than swallowed.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

import pytest

from tools.errors import ConfigurationError, ValidationError

background_scan = importlib.import_module("lambda.background_scan")


def test_clinic_id_is_forwarded_from_the_event(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_scan(clinic_id: str) -> dict[str, Any]:
        captured["clinic_id"] = clinic_id
        return {"clinic_id": clinic_id, "scanned": 0}

    monkeypatch.setattr(background_scan, "run_daily_scan", fake_scan)
    result = background_scan.handler({"clinic_id": "clinic-dental"})
    assert captured["clinic_id"] == "clinic-dental"
    assert result == {"clinic_id": "clinic-dental", "scanned": 0}


def test_missing_clinic_id_raises_and_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_scan(clinic_id: str) -> dict[str, Any]:
        raise ValidationError("clinic_id is required and must be a non-empty string.")

    monkeypatch.setattr(background_scan, "run_daily_scan", fake_scan)
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValidationError):
            background_scan.handler({})
    assert "Daily scan failed" in caplog.text


def test_a_deployment_fault_propagates_rather_than_being_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken clinic config must fail the invocation, not return quietly."""

    def fake_scan(clinic_id: str) -> dict[str, Any]:
        raise ConfigurationError("Clinic 'clinic-dental' has no timezone.")

    monkeypatch.setattr(background_scan, "run_daily_scan", fake_scan)
    with pytest.raises(ConfigurationError):
        background_scan.handler({"clinic_id": "clinic-dental"})
