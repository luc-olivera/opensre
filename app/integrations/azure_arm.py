"""Shared helpers for the read-only Azure Resource Manager (control-plane) tools.

These tools ride the existing ``azure`` integration source (see
``app/integrations/_catalog_impl.py``), which carries an ``arm_access_token``
minted keylessly from the container's Managed Identity (scope
``https://management.azure.com``) plus the ``subscription_id``. They are
independent of Log Analytics — the source is available for ARM as long as the
ARM token + subscription are present. (CloudNation SRE-68.)
"""

from __future__ import annotations

from typing import Any

import httpx

from app.tools._telemetry import report_run_error

ARM_DEFAULT_ENDPOINT = "https://management.azure.com"

# Well-known built-in role definition GUIDs → names, so role-assignment output is
# readable without an extra GET per assignment. Unknown GUIDs are returned as-is.
_WELL_KNOWN_ROLES: dict[str, str] = {
    "7f951dda-4ed3-4680-a7ca-43fe172d538d": "AcrPull",
    "8311e382-0749-4cb8-b61a-304f252e45ec": "AcrPush",
    "acdd72a7-3385-48ef-bd42-f606fba81ae7": "Reader",
    "b24988ac-6180-42a0-ab88-20f7382dd24c": "Contributor",
    "73c42c96-874c-492b-b04d-ab87d138a893": "Log Analytics Reader",
    "43d0d8ad-25c7-4714-9337-8ba259a9fe05": "Monitoring Reader",
}


def arm_is_available(sources: dict[str, dict[str, Any]]) -> bool:
    """ARM tools are available when the azure source carries an ARM token + sub.

    Decoupled from Log Analytics: a workspace is NOT required. ``connection_verified``
    is synthesized for configured sources by the agent's availability view.
    """
    azure = sources.get("azure", {})
    return bool(
        azure.get("connection_verified")
        and azure.get("arm_access_token")
        and azure.get("subscription_id")
    )


def arm_extract_params(sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Connection params injected into every ARM tool call from the azure source."""
    azure = sources["azure"]
    return {
        "arm_access_token": str(azure.get("arm_access_token", "")).strip(),
        "arm_endpoint": str(azure.get("arm_endpoint", ARM_DEFAULT_ENDPOINT)).strip()
        or ARM_DEFAULT_ENDPOINT,
        "subscription_id": str(azure.get("subscription_id", "")).strip(),
        "resource_group": str(azure.get("arm_resource_group", "")).strip(),
        "integration_id": str(azure.get("integration_id", "")).strip(),
    }


def role_name_for(role_definition_id: str) -> str:
    """Map a roleDefinitionId (…/<guid>) to a friendly name, else the GUID."""
    guid = str(role_definition_id or "").rstrip("/").rsplit("/", 1)[-1].lower()
    return _WELL_KNOWN_ROLES.get(guid, guid or "unknown")


def arm_get(
    path: str,
    *,
    arm_endpoint: str,
    token: str,
    api_version: str,
    tool_name: str,
    extra_params: dict[str, str] | None = None,
    timeout_seconds: float = 20.0,
) -> tuple[bool, Any]:
    """GET an ARM path (read-only). Returns (ok, parsed_json | error_string).

    Fail-soft: any error is reported and surfaced as (False, message) so the tool
    returns ``available: False`` rather than raising into the investigation loop.
    """
    base = arm_endpoint.strip().rstrip("/") or ARM_DEFAULT_ENDPOINT
    url = f"{base}/{path.lstrip('/')}"
    params = {"api-version": api_version}
    if extra_params:
        params.update({k: v for k, v in extra_params.items() if v})
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        resp = httpx.get(url, headers=headers, params=params, timeout=max(1.0, timeout_seconds))
        resp.raise_for_status()
        return True, resp.json()
    except Exception as err:  # noqa: BLE001 - fail-soft by design
        report_run_error(
            err,
            tool_name=tool_name,
            source="azure",
            component="app.integrations.azure_arm",
            method="httpx.get",
            extras={"url": url},
        )
        return False, str(err)
