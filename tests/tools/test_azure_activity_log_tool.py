"""Tests for AzureActivityLogTool."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.tools.AzureActivityLogTool import query_activity_log
from tests.tools.conftest import BaseToolContract


def _registered_tool() -> Any:
    return cast(Any, query_activity_log).__opensre_registered_tool__


class TestAzureActivityLogToolContract(BaseToolContract):
    def get_tool_under_test(self):
        return _registered_tool()


def test_is_available() -> None:
    rt = _registered_tool()
    assert rt.is_available({"azure": {"connection_verified": True, "arm_access_token": "t", "subscription_id": "s"}}) is True
    assert rt.is_available({}) is False


def _mock_resp(json_body: Any) -> MagicMock:
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = json_body
    return r


def test_happy_path_window_and_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        captured["url"] = url
        captured["params"] = kwargs.get("params", {})
        return _mock_resp(
            {
                "value": [
                    {
                        "eventTimestamp": "2026-06-29T12:00:00Z",
                        "operationName": {"value": "Microsoft.App/containerApps/write"},
                        "status": {"value": "Succeeded"},
                        "caller": "user@cloudnation.nl",
                        "level": "Informational",
                        "resourceGroupName": "rg-cat-dev-sdc-01",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", fake_get)
    out = query_activity_log(arm_access_token="tok", subscription_id="sub", time_range_minutes=120, resource_group="rg-cat-dev-sdc-01")
    assert out["available"] is True and out["total_returned"] == 1
    assert out["rows"][0]["operationName"] == "Microsoft.App/containerApps/write"
    assert out["rows"][0]["caller"] == "user@cloudnation.nl"
    # mandatory eventTimestamp window + RG filter present
    assert "eventTimestamp ge" in captured["params"]["$filter"]
    assert "resourceGroupName eq 'rg-cat-dev-sdc-01'" in captured["params"]["$filter"]
    assert captured["params"]["api-version"] == "2015-04-01"


def test_window_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", lambda *a, **k: _mock_resp({"value": []}))
    out = query_activity_log(arm_access_token="tok", subscription_id="sub", time_range_minutes=999999)
    assert out["window_minutes"] == 7 * 24 * 60


def test_http_error_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    r = MagicMock()
    r.raise_for_status.side_effect = Exception("400 Bad Request")
    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", lambda *a, **k: r)
    out = query_activity_log(arm_access_token="tok", subscription_id="sub")
    assert out["available"] is False and "400" in out["error"]


def test_missing_creds() -> None:
    assert query_activity_log(arm_access_token="", subscription_id="")["available"] is False
