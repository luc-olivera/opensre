"""Read-only Azure Activity Log (control-plane audit) tool (CloudNation SRE-68).

Returns recent management-plane events (who deployed a revision, who changed/
revoked a role, who stopped an app) for a subscription, optionally filtered to a
resource group. Answers the "who/when did this change" question that logs and
resource config alone cannot.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.integrations.azure_arm import arm_extract_params, arm_get, arm_is_available
from app.tools.tool_decorator import tool

_API_VERSION = "2015-04-01"
_MAX_RESULTS = 50
_MAX_WINDOW_MIN = 7 * 24 * 60  # ARM Activity Log retains ~90d; cap the query window


def _summarize_event(ev: dict[str, Any]) -> dict[str, Any]:
    def _localized(v: Any) -> Any:
        return v.get("value") if isinstance(v, dict) else v

    return {
        "eventTimestamp": ev.get("eventTimestamp"),
        "operationName": _localized(ev.get("operationName")),
        "status": _localized(ev.get("status")),
        "caller": ev.get("caller"),
        "level": ev.get("level"),
        "resourceGroupName": ev.get("resourceGroupName"),
        "resourceId": ev.get("resourceId"),
    }


@tool(
    name="query_activity_log",
    description=(
        "Query the Azure Activity Log (control-plane audit, read-only) for recent "
        "management events — who deployed/updated a revision, changed or revoked a "
        "role assignment, or stopped a resource — within a time window. Use to "
        "establish who/when made a change behind an incident. Optionally filter to a "
        "resource group."
    ),
    source="azure",
    surfaces=("investigation",),
    requires=["arm_access_token", "subscription_id"],
    input_schema={
        "type": "object",
        "properties": {
            "time_range_minutes": {
                "type": "integer",
                "default": 120,
                "description": "Look-back window in minutes (capped at ~7 days).",
            },
            "resource_group": {
                "type": "string",
                "description": "Optional resource group to filter events to.",
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
def query_activity_log(
    arm_access_token: str = "",
    arm_endpoint: str = "https://management.azure.com",
    subscription_id: str = "",
    time_range_minutes: int = 120,
    resource_group: str = "",
    integration_id: str = "",
    timeout_seconds: float = 20.0,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Fetch recent Activity Log management events for the subscription."""
    token = arm_access_token.strip()
    sub = subscription_id.strip()
    if not token or not sub:
        return {"source": "azure", "available": False, "error": "Missing ARM credentials.", "rows": []}

    window = max(1, min(int(time_range_minutes or 120), _MAX_WINDOW_MIN))
    start = (datetime.now(UTC) - timedelta(minutes=window)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # eventTimestamp window is mandatory (ARM returns 400 without it).
    flt = f"eventTimestamp ge '{start}' and eventChannels eq 'Admin, Operation'"
    rg = (resource_group or "").strip()
    if rg:
        flt += f" and resourceGroupName eq '{rg}'"

    ok, body = arm_get(
        f"subscriptions/{sub}/providers/microsoft.insights/eventtypes/management/values",
        arm_endpoint=arm_endpoint,
        token=token,
        api_version=_API_VERSION,
        tool_name="query_activity_log",
        extra_params={"$filter": flt},
        timeout_seconds=timeout_seconds,
    )
    if not ok:
        return {"source": "azure", "available": False, "error": body, "rows": []}

    events = body.get("value", []) if isinstance(body, dict) else []
    rows = [_summarize_event(e) for e in events[:_MAX_RESULTS] if isinstance(e, dict)]
    return {
        "source": "azure",
        "available": True,
        "window_minutes": window,
        "resource_group": rg or None,
        "total_returned": len(rows),
        "rows": rows,
        "integration_id": integration_id,
    }
