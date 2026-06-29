"""Tests for AzureContainerAppTool (function-based, @tool decorated)."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.tools.AzureContainerAppTool import get_container_app
from tests.tools.conftest import BaseToolContract


def _registered_tool() -> Any:
    return cast(Any, get_container_app).__opensre_registered_tool__


class TestAzureContainerAppToolContract(BaseToolContract):
    def get_tool_under_test(self):
        return _registered_tool()


@pytest.mark.parametrize(
    "sources,expected",
    [
        ({"azure": {"connection_verified": True, "arm_access_token": "t", "subscription_id": "s"}}, True),
        ({"azure": {"connection_verified": False, "arm_access_token": "t", "subscription_id": "s"}}, False),
        ({"azure": {"connection_verified": True, "arm_access_token": "", "subscription_id": "s"}}, False),
        ({"azure": {"connection_verified": True, "arm_access_token": "t", "subscription_id": ""}}, False),
        ({}, False),
    ],
)
def test_is_available(sources: dict, expected: bool) -> None:
    assert _registered_tool().is_available(sources) is expected


def test_extract_params_maps_arm_fields() -> None:
    params = _registered_tool().extract_params(
        {
            "azure": {
                "arm_access_token": " tok ",
                "arm_endpoint": " https://management.azure.com ",
                "subscription_id": " sub-1 ",
                "arm_resource_group": " rg-cat-dev-sdc-01 ",
            }
        }
    )
    assert params["arm_access_token"] == "tok"
    assert params["subscription_id"] == "sub-1"
    assert params["resource_group"] == "rg-cat-dev-sdc-01"


def _mock_resp(json_body: Any) -> MagicMock:
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = json_body
    return r


def test_list_mode_lists_apps(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        captured["url"] = url
        captured["params"] = kwargs.get("params", {})
        captured["headers"] = kwargs.get("headers", {})
        return _mock_resp({"value": [{"name": "ca-cat-back-dev-sdc-01", "properties": {"runningStatus": "Running"}}]})

    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", fake_get)
    out = get_container_app(arm_access_token="tok", subscription_id="sub", resource_group="rg-cat-dev-sdc-01")
    assert out["available"] is True and out["mode"] == "list"
    assert out["rows"][0]["name"] == "ca-cat-back-dev-sdc-01"
    assert captured["params"]["api-version"] == "2024-03-01"
    assert captured["headers"]["Authorization"] == "Bearer tok"


def test_get_mode_returns_command(monkeypatch: pytest.MonkeyPatch) -> None:
    # First call → the app; second call → its revisions (with the /bin/false command).
    responses = [
        _mock_resp({"name": "ca-cat-back-dev-sdc-01", "properties": {"runningStatus": "Running"}}),
        _mock_resp(
            {
                "value": [
                    {
                        "name": "ca-cat-back-dev-sdc-01--brokencmd",
                        "properties": {
                            "active": True,
                            "replicas": 0,
                            "runningState": "Failed",
                            "template": {"containers": [{"name": "backend", "image": "img", "command": ["/bin/false"]}]},
                        },
                    }
                ]
            }
        ),
    ]
    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", lambda *a, **k: responses.pop(0))
    out = get_container_app(arm_access_token="tok", subscription_id="sub", resource_group="rg", app_name="ca-cat-back-dev-sdc-01")
    assert out["available"] is True and out["mode"] == "get"
    assert out["revisions"][0]["containers"][0]["command"] == ["/bin/false"]
    assert out["revisions"][0]["replicas"] == 0


def test_http_error_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    r = MagicMock()
    r.raise_for_status.side_effect = Exception("403 Forbidden")
    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", lambda *a, **k: r)
    out = get_container_app(arm_access_token="tok", subscription_id="sub", resource_group="rg")
    assert out["available"] is False and "403" in out["error"]


def test_missing_creds() -> None:
    assert get_container_app(arm_access_token="", subscription_id="")["available"] is False


def test_missing_resource_group() -> None:
    out = get_container_app(arm_access_token="tok", subscription_id="sub", resource_group="")
    assert out["available"] is False and "resource_group" in out["error"]
