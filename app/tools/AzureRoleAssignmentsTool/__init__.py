"""Read-only Azure RBAC role-assignment tool (CloudNation SRE-68).

Lists role assignments at a given scope so the agent can confirm an identity's
permissions — e.g. that a Container App's managed identity is MISSING `AcrPull`
on the registry (image-pull 401), instead of only inferring it from the error.
"""

from __future__ import annotations

from typing import Any

from app.integrations.azure_arm import arm_extract_params, arm_get, arm_is_available, role_name_for
from app.tools.tool_decorator import tool

_API_VERSION = "2022-04-01"
_MAX_RESULTS = 100


def _summarize_assignment(item: dict[str, Any]) -> dict[str, Any]:
    props = item.get("properties", {}) if isinstance(item, dict) else {}
    return {
        "roleDefinitionName": role_name_for(props.get("roleDefinitionId", "")),
        "principalId": props.get("principalId"),
        "principalType": props.get("principalType"),
        "scope": props.get("scope"),
    }


@tool(
    name="list_role_assignments",
    description=(
        "List Azure RBAC role assignments AT A GIVEN SCOPE (read-only). Use to "
        "confirm whether an identity has a role — e.g. check if a Container App's "
        "managed identity is missing 'AcrPull' on a registry (image-pull 401). "
        "Pass the resource scope (e.g. the registry's resource ID) and optionally a "
        "principal_id to filter. Note: results are assignments AT THIS SCOPE only "
        "(inherited grants from parent scopes are not listed)."
    ),
    source="azure",
    surfaces=("investigation",),
    requires=["arm_access_token", "subscription_id"],
    input_schema={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": (
                    "Resource ID to query assignments at, e.g. "
                    "'/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ContainerRegistry/registries/<acr>'. "
                    "Defaults to the configured subscription if omitted."
                ),
            },
            "principal_id": {
                "type": "string",
                "description": "Optional managed-identity/principal objectId to filter by.",
            },
            "arm_access_token": {"type": "string"},
            "arm_endpoint": {"type": "string"},
            "subscription_id": {"type": "string"},
            "integration_id": {"type": "string"},
            "timeout_seconds": {"type": "number", "default": 20.0},
        },
        "required": [],
    },
    is_available=arm_is_available,
    extract_params=arm_extract_params,
)
def list_role_assignments(
    arm_access_token: str = "",
    arm_endpoint: str = "https://management.azure.com",
    subscription_id: str = "",
    scope: str = "",
    principal_id: str = "",
    integration_id: str = "",
    timeout_seconds: float = 20.0,
    **_kwargs: Any,
) -> dict[str, Any]:
    """List role assignments at ``scope`` (defaults to the subscription)."""
    token = arm_access_token.strip()
    sub = subscription_id.strip()
    if not token or not sub:
        return {"source": "azure", "available": False, "error": "Missing ARM credentials.", "rows": []}

    eff_scope = (scope or "").strip() or f"subscriptions/{sub}"
    pid = principal_id.strip()
    # With a principal, use assignedTo('<pid>') at the (default subscription)
    # scope: it returns EVERY role that principal effectively has — including
    # inherited grants — so "does X have AcrPull anywhere" is answered correctly
    # without knowing the target resource's exact ID (SRE-68 mem18). Without a
    # principal, fall back to atScope() (assignments defined directly at scope).
    if pid:
        flt = f"assignedTo('{pid}')"
        note = "effective assignments for the principal across the scope, including inherited grants"
    else:
        flt = "atScope()"
        note = "assignments defined directly at this scope only (inherited grants not listed)"

    ok, body = arm_get(
        f"{eff_scope.lstrip('/')}/providers/Microsoft.Authorization/roleAssignments",
        arm_endpoint=arm_endpoint,
        token=token,
        api_version=_API_VERSION,
        tool_name="list_role_assignments",
        extra_params={"$filter": flt},
        timeout_seconds=timeout_seconds,
    )
    if not ok:
        return {"source": "azure", "available": False, "error": body, "rows": []}

    items = body.get("value", []) if isinstance(body, dict) else []
    rows = [_summarize_assignment(i) for i in items[:_MAX_RESULTS] if isinstance(i, dict)]
    return {
        "source": "azure",
        "available": True,
        "scope": eff_scope,
        "filtered_principal_id": pid or None,
        "note": note,
        "total_returned": len(rows),
        "rows": rows,
        "integration_id": integration_id,
    }
