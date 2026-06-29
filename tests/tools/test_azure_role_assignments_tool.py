"""Tests for AzureRoleAssignmentsTool."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from app.tools.AzureRoleAssignmentsTool import list_role_assignments
from tests.tools.conftest import BaseToolContract


def _registered_tool() -> Any:
    return cast(Any, list_role_assignments).__opensre_registered_tool__


class TestAzureRoleAssignmentsToolContract(BaseToolContract):
    def get_tool_under_test(self):
        return _registered_tool()


def test_is_available() -> None:
    rt = _registered_tool()
    assert rt.is_available({"azure": {"connection_verified": True, "arm_access_token": "t", "subscription_id": "s"}}) is True
    assert rt.is_available({"azure": {"arm_access_token": "t", "subscription_id": "s"}}) is False


def _mock_resp(json_body: Any) -> MagicMock:
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = json_body
    return r


def test_resolves_acrpull_and_filters_principal(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_get(url: str, **kwargs: Any) -> MagicMock:
        captured["params"] = kwargs.get("params", {})
        return _mock_resp(
            {
                "value": [
                    {
                        "properties": {
                            # AcrPull well-known GUID
                            "roleDefinitionId": ".../7f951dda-4ed3-4680-a7ca-43fe172d538d",
                            "principalId": "p-1",
                            "principalType": "ServicePrincipal",
                            "scope": "/.../registries/crcatshared01",
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", fake_get)
    out = list_role_assignments(
        arm_access_token="tok",
        subscription_id="sub",
        scope="/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ContainerRegistry/registries/crcatshared01",
        principal_id="p-1",
    )
    assert out["available"] is True
    assert out["rows"][0]["roleDefinitionName"] == "AcrPull"
    assert "principalId eq 'p-1'" in captured["params"]["$filter"]
    assert captured["params"]["api-version"] == "2022-04-01"


def test_empty_assignments_means_role_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", lambda *a, **k: _mock_resp({"value": []}))
    out = list_role_assignments(arm_access_token="tok", subscription_id="sub", scope="/sub/rg/acr", principal_id="p-1")
    assert out["available"] is True and out["total_returned"] == 0
    assert "this scope only" in out["note"]


def test_http_error_fail_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    r = MagicMock()
    r.raise_for_status.side_effect = Exception("401 Unauthorized")
    monkeypatch.setattr("app.integrations.azure_arm.httpx.get", lambda *a, **k: r)
    out = list_role_assignments(arm_access_token="tok", subscription_id="sub")
    assert out["available"] is False and "401" in out["error"]


def test_missing_creds() -> None:
    assert list_role_assignments(arm_access_token="", subscription_id="")["available"] is False
