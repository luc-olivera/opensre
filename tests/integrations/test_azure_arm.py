"""Tests for the shared Azure ARM helpers (auth/availability/request)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.integrations.azure_arm import (
    ARM_DEFAULT_ENDPOINT,
    arm_extract_params,
    arm_get,
    arm_is_available,
    role_name_for,
)


@pytest.mark.parametrize(
    "sources,expected",
    [
        ({"azure": {"connection_verified": True, "arm_access_token": "t", "subscription_id": "s"}}, True),
        ({"azure": {"connection_verified": True, "arm_access_token": "", "subscription_id": "s"}}, False),
        ({"azure": {"connection_verified": True, "arm_access_token": "t", "subscription_id": ""}}, False),
        ({"azure": {"connection_verified": False, "arm_access_token": "t", "subscription_id": "s"}}, False),
        ({}, False),
    ],
)
def test_arm_is_available(sources: dict, expected: bool) -> None:
    assert arm_is_available(sources) is expected


def test_arm_extract_params_defaults() -> None:
    p = arm_extract_params({"azure": {"arm_access_token": " tok ", "subscription_id": " sub ", "arm_resource_group": " rg "}})
    assert p["arm_access_token"] == "tok"
    assert p["subscription_id"] == "sub"
    assert p["resource_group"] == "rg"
    assert p["arm_endpoint"] == ARM_DEFAULT_ENDPOINT


def test_role_name_for_well_known_and_unknown() -> None:
    assert role_name_for("/subscriptions/x/.../7f951dda-4ed3-4680-a7ca-43fe172d538d") == "AcrPull"
    assert role_name_for("/.../acdd72a7-3385-48ef-bd42-f606fba81ae7") == "Reader"
    assert role_name_for("/.../00000000-0000-0000-0000-000000000000") == "00000000-0000-0000-0000-000000000000"
    assert role_name_for("") == "unknown"


def test_arm_get_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"ok": True}

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        captured["url"] = url
        captured["params"] = kwargs.get("params", {})
        captured["headers"] = kwargs.get("headers", {})
        return resp

    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", fake_get)
    ok, body = arm_get("subscriptions/s/x", arm_endpoint="https://management.azure.com", token="tok", api_version="2024-03-01", tool_name="t", extra_params={"$filter": "a", "empty": ""})
    assert ok is True and body == {"ok": True}
    assert captured["url"] == "https://management.azure.com/subscriptions/s/x"
    assert captured["params"]["api-version"] == "2024-03-01"
    assert captured["params"]["$filter"] == "a"
    assert "empty" not in captured["params"]  # blank values dropped
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_arm_get_error_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = MagicMock()
    resp.raise_for_status.side_effect = Exception("404 Not Found")
    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", lambda *a, **k: resp)
    ok, body = arm_get("subscriptions/s/missing", arm_endpoint="https://management.azure.com", token="tok", api_version="2024-03-01", tool_name="t")
    assert ok is False and "404" in body
