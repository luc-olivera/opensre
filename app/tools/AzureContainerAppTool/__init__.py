"""Read-only Azure Container Apps control-plane tool (CloudNation SRE-68).

Reads a container app's revisions — image, command/args, replicas, running state,
traffic — which Log Analytics cannot show. Closes the gap where the agent only saw
"exit code 1" in logs but not the revision's `command` (e.g. a bad `/bin/false`
override) or a 0-replica/stopped revision.
"""

from __future__ import annotations

from typing import Any

from app.integrations.azure_arm import arm_extract_params, arm_get, arm_is_available
from app.tools.tool_decorator import tool

_API_VERSION = "2024-03-01"
_MAX_REVISIONS = 20


def _summarize_app(app: dict[str, Any]) -> dict[str, Any]:
    props = app.get("properties", {}) if isinstance(app, dict) else {}
    cfg = props.get("configuration", {}) or {}
    # Expose the app's managed identity (incl. principalId) so the agent can chain
    # into list_role_assignments to confirm RBAC (e.g. a missing AcrPull behind a
    # pull 401) instead of only inferring it. (SRE-68 mem17)
    ident = app.get("identity", {}) if isinstance(app, dict) else {}
    user_assigned = [
        {"resourceId": rid, "principalId": (val or {}).get("principalId"), "clientId": (val or {}).get("clientId")}
        for rid, val in (ident.get("userAssignedIdentities") or {}).items()
    ]
    return {
        "name": app.get("name"),
        "provisioningState": props.get("provisioningState"),
        "runningStatus": props.get("runningStatus"),
        "activeRevisionsMode": cfg.get("activeRevisionsMode"),
        "latestRevisionName": props.get("latestRevisionName"),
        "identity": {
            "type": ident.get("type"),
            "userAssignedIdentities": user_assigned,
        },
    }


def _summarize_revision(rev: dict[str, Any]) -> dict[str, Any]:
    props = rev.get("properties", {}) if isinstance(rev, dict) else {}
    template = props.get("template", {}) or {}
    containers = [
        {
            "name": c.get("name"),
            "image": c.get("image"),
            "command": c.get("command"),
            "args": c.get("args"),
        }
        for c in (template.get("containers") or [])
        if isinstance(c, dict)
    ]
    return {
        "name": rev.get("name"),
        "active": props.get("active"),
        "replicas": props.get("replicas"),
        "trafficWeight": props.get("trafficWeight"),
        "runningState": props.get("runningState"),
        "createdTime": props.get("createdTime"),
        "containers": containers,
    }


@tool(
    name="get_container_app",
    description=(
        "Read an Azure Container App's control-plane config (read-only): its "
        "revisions, container image, command/args, replicas, running state and "
        "traffic. Use to inspect a suspected bad deploy/revision — e.g. confirm a "
        "broken startup command or a 0-replica/stopped revision — which logs alone "
        "cannot show. Omit app_name to list the container apps in the resource group."
    ),
    source="azure",
    surfaces=("investigation",),
    requires=["arm_access_token", "subscription_id"],
    input_schema={
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": (
                    "Container App resource name (e.g. 'ca-cat-back-dev-sdc-01'). "
                    "If omitted, lists the apps in the resource group so you can find it."
                ),
            },
            "resource_group": {
                "type": "string",
                "description": "Resource group; defaults to the agent's configured group.",
            },
            # Injected connection params (not model-supplied):
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
def get_container_app(
    arm_access_token: str = "",
    arm_endpoint: str = "https://management.azure.com",
    subscription_id: str = "",
    resource_group: str = "",
    app_name: str = "",
    integration_id: str = "",
    timeout_seconds: float = 20.0,
    **_kwargs: Any,
) -> dict[str, Any]:
    """List container apps in a resource group, or get one app + its revisions."""
    token = arm_access_token.strip()
    sub = subscription_id.strip()
    # resource_group is injected from the azure source (env AZURE_RESOURCE_GROUP)
    # unless the model overrides it.
    rg = (resource_group or "").strip()
    if not token or not sub:
        return {"source": "azure", "available": False, "error": "Missing ARM credentials.", "rows": []}
    if not rg:
        return {
            "source": "azure",
            "available": False,
            "error": "No resource_group given and no default configured.",
            "rows": [],
        }

    base_path = (
        f"subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/containerApps"
    )

    # List mode — no app_name: return the apps in the RG so the model can pick one.
    if not app_name.strip():
        ok, body = arm_get(
            base_path,
            arm_endpoint=arm_endpoint,
            token=token,
            api_version=_API_VERSION,
            tool_name="get_container_app",
            timeout_seconds=timeout_seconds,
        )
        if not ok:
            return {"source": "azure", "available": False, "error": body, "rows": []}
        apps = body.get("value", []) if isinstance(body, dict) else []
        return {
            "source": "azure",
            "available": True,
            "mode": "list",
            "resource_group": rg,
            "total_returned": len(apps),
            "rows": [_summarize_app(a) for a in apps if isinstance(a, dict)],
        }

    # Get mode — app_name given: the app + its recent revisions.
    name = app_name.strip()
    ok, app_body = arm_get(
        f"{base_path}/{name}",
        arm_endpoint=arm_endpoint,
        token=token,
        api_version=_API_VERSION,
        tool_name="get_container_app",
        timeout_seconds=timeout_seconds,
    )
    if not ok:
        return {"source": "azure", "available": False, "error": app_body, "app_name": name, "rows": []}

    rev_ok, rev_body = arm_get(
        f"{base_path}/{name}/revisions",
        arm_endpoint=arm_endpoint,
        token=token,
        api_version=_API_VERSION,
        tool_name="get_container_app",
        timeout_seconds=timeout_seconds,
    )
    revisions: list[dict[str, Any]] = []
    if rev_ok and isinstance(rev_body, dict):
        revisions = [
            _summarize_revision(r)
            for r in (rev_body.get("value") or [])[:_MAX_REVISIONS]
            if isinstance(r, dict)
        ]

    return {
        "source": "azure",
        "available": True,
        "mode": "get",
        "app": _summarize_app(app_body),
        "revisions": revisions,
        "integration_id": integration_id,
    }
