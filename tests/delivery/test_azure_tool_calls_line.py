"""Unit tests for _format_tool_calls_line — Azure ACTION_DEFS entries.

Run with:
    PYTHONPATH=. /Users/lucas.zago/mamba/envs/cn-ai/bin/python3 -m pytest \
        tests/delivery/test_azure_tool_calls_line.py -q --noconftest
"""

from __future__ import annotations

from tests.delivery._formatter_stubs import bootstrap_formatter_modules

bootstrap_formatter_modules()

import pytest

from app.delivery.publish_findings.formatters.evidence import _format_tool_calls_line


# Plain identity link_fn so labels render verbatim and we can assert exact substrings.
_LINK_FN = lambda label, url: label


def _ctx(actions: list[str], evidence: dict) -> dict:
    """Build minimal ReportContext dict for _format_tool_calls_line."""
    return {
        "executed_hypotheses": [{"actions": actions}],
        "evidence": evidence,
        "grafana_endpoint": "",
        "datadog_site": "datadoghq.com",
    }


# ---------------------------------------------------------------------------
# list_role_assignments
# ---------------------------------------------------------------------------


def test_list_role_assignments_3_assignments() -> None:
    ev = {"list_role_assignments": {"available": True, "total_returned": 3}}
    result = _format_tool_calls_line(_ctx(["list_role_assignments"], ev), link_fn=_LINK_FN)
    assert "Azure RBAC (3 assignments)" in result


def test_list_role_assignments_zero_allow_zero() -> None:
    ev = {"list_role_assignments": {"available": True, "total_returned": 0}}
    result = _format_tool_calls_line(_ctx(["list_role_assignments"], ev), link_fn=_LINK_FN)
    assert "Azure RBAC (0 assignments)" in result


# ---------------------------------------------------------------------------
# get_container_app — get mode
# ---------------------------------------------------------------------------


def test_get_container_app_get_mode_3_revisions() -> None:
    ev = {"get_container_app": {"available": True, "mode": "get", "revisions": [{}, {}, {}]}}
    result = _format_tool_calls_line(_ctx(["get_container_app"], ev), link_fn=_LINK_FN)
    assert "Azure Container App (3 revisions)" in result


def test_get_container_app_get_mode_empty_revisions() -> None:
    ev = {"get_container_app": {"available": True, "mode": "get", "revisions": []}}
    result = _format_tool_calls_line(_ctx(["get_container_app"], ev), link_fn=_LINK_FN)
    assert "Azure Container App (0 revisions)" in result


# ---------------------------------------------------------------------------
# get_container_app — list mode
# ---------------------------------------------------------------------------


def test_get_container_app_list_mode_5_apps() -> None:
    ev = {"get_container_app": {"available": True, "mode": "list", "total_returned": 5}}
    result = _format_tool_calls_line(_ctx(["get_container_app"], ev), link_fn=_LINK_FN)
    assert "Azure Container App (5 apps)" in result


def test_get_container_app_list_mode_zero_no_count() -> None:
    ev = {"get_container_app": {"available": True, "mode": "list", "total_returned": 0}}
    result = _format_tool_calls_line(_ctx(["get_container_app"], ev), link_fn=_LINK_FN)
    # zero in list mode → allow_zero=False → bare label, no count
    assert "Azure Container App" in result
    after = result.split("Azure Container App", 1)[1].split(",")[0]
    assert "(" not in after


# ---------------------------------------------------------------------------
# get_container_app — None / non-list edge cases (regression guards)
# ---------------------------------------------------------------------------


def test_get_container_app_value_none_no_crash() -> None:
    ev = {"get_container_app": None}
    result = _format_tool_calls_line(_ctx(["get_container_app"], ev), link_fn=_LINK_FN)
    assert "Azure Container App" in result
    assert "(0" not in result
    assert "(None" not in result


def test_get_container_app_revisions_not_list_get_mode() -> None:
    ev = {"get_container_app": {"available": True, "mode": "get", "revisions": None}}
    result = _format_tool_calls_line(_ctx(["get_container_app"], ev), link_fn=_LINK_FN)
    assert "Azure Container App (0 revisions)" in result


# ---------------------------------------------------------------------------
# query_activity_log
# ---------------------------------------------------------------------------


def test_query_activity_log_7_events() -> None:
    ev = {"query_activity_log": {"available": True, "total_returned": 7}}
    result = _format_tool_calls_line(_ctx(["query_activity_log"], ev), link_fn=_LINK_FN)
    assert "Azure Activity Log (7 events)" in result


def test_query_activity_log_zero_no_count() -> None:
    ev = {"query_activity_log": {"available": True, "total_returned": 0}}
    result = _format_tool_calls_line(_ctx(["query_activity_log"], ev), link_fn=_LINK_FN)
    assert "Azure Activity Log" in result
    assert "(0 events)" not in result


# ---------------------------------------------------------------------------
# query_azure_monitor_logs
# ---------------------------------------------------------------------------


def test_query_azure_monitor_logs_42_rows() -> None:
    ev = {"query_azure_monitor_logs": {"available": True, "total_returned": 42}}
    result = _format_tool_calls_line(_ctx(["query_azure_monitor_logs"], ev), link_fn=_LINK_FN)
    assert "Azure Monitor Logs (42 rows)" in result


# ---------------------------------------------------------------------------
# available=False → bare label, no count, no crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action, evidence_value",
    [
        ("list_role_assignments", {"available": False, "total_returned": 5}),
        ("get_container_app", {"available": False, "mode": "get", "revisions": [{}, {}]}),
        ("query_activity_log", {"available": False, "total_returned": 10}),
        ("query_azure_monitor_logs", {"available": False, "total_returned": 100}),
    ],
)
def test_available_false_bare_label(action: str, evidence_value: dict) -> None:
    ev = {action: evidence_value}
    result = _format_tool_calls_line(_ctx([action], ev), link_fn=_LINK_FN)
    after_queries = result.split("Queries: ", 1)[1]
    assert "(" not in after_queries


# ---------------------------------------------------------------------------
# Missing evidence entry → bare label, no crash
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    [
        "list_role_assignments",
        "get_container_app",
        "query_activity_log",
        "query_azure_monitor_logs",
    ],
)
def test_missing_evidence_entry_bare_label_no_crash(action: str) -> None:
    ev: dict = {}
    result = _format_tool_calls_line(_ctx([action], ev), link_fn=_LINK_FN)
    assert result != ""


# ---------------------------------------------------------------------------
# available=True but no total_returned → bare label
# ---------------------------------------------------------------------------


def test_no_total_returned_bare_label() -> None:
    ev = {"list_role_assignments": {"available": True}}
    result = _format_tool_calls_line(_ctx(["list_role_assignments"], ev), link_fn=_LINK_FN)
    assert "Azure RBAC" in result
    after = result.split("Azure RBAC", 1)[1].split(",")[0]
    assert "(" not in after


# ---------------------------------------------------------------------------
# Two Azure actions → "Queries: " prefix, both labels present
# ---------------------------------------------------------------------------


def test_two_azure_actions_prefix_and_both_labels() -> None:
    ev = {
        "list_role_assignments": {"available": True, "total_returned": 2},
        "query_activity_log": {"available": True, "total_returned": 3},
    }
    result = _format_tool_calls_line(
        _ctx(["list_role_assignments", "query_activity_log"], ev), link_fn=_LINK_FN
    )
    assert result.startswith("Queries: ")
    assert "Azure RBAC" in result
    assert "Azure Activity Log" in result


# ---------------------------------------------------------------------------
# executed_hypotheses missing / empty → empty string
# ---------------------------------------------------------------------------


def test_missing_executed_hypotheses_returns_empty() -> None:
    ctx: dict = {"evidence": {}, "grafana_endpoint": "", "datadog_site": "datadoghq.com"}
    result = _format_tool_calls_line(ctx, link_fn=_LINK_FN)
    assert result == ""


def test_empty_executed_hypotheses_returns_empty() -> None:
    ctx = _ctx([], {})
    result = _format_tool_calls_line(ctx, link_fn=_LINK_FN)
    assert result == ""


# ---------------------------------------------------------------------------
# Grafana / Datadog count helpers (exercised indirectly via action calls)
# ---------------------------------------------------------------------------


def test_query_grafana_logs_with_logs_and_errors() -> None:
    ev = {
        "grafana_logs": [{"message": "ok"}] * 3,
        "grafana_error_logs": [{"message": "err"}] * 2,
    }
    result = _format_tool_calls_line(_ctx(["query_grafana_logs"], ev), link_fn=_LINK_FN)
    assert "3 logs" in result
    assert "2 errors" in result


def test_query_grafana_logs_empty_returns_bare_label() -> None:
    ev: dict = {}
    result = _format_tool_calls_line(_ctx(["query_grafana_logs"], ev), link_fn=_LINK_FN)
    assert "Grafana Loki" in result
    assert "(" not in result.split("Grafana Loki")[1].split(",")[0]


def test_query_datadog_logs_with_logs_and_errors() -> None:
    ev = {
        "datadog_logs": [{}] * 5,
        "datadog_error_logs": [{}] * 1,
    }
    result = _format_tool_calls_line(_ctx(["query_datadog_logs"], ev), link_fn=_LINK_FN)
    assert "5 logs" in result
    assert "1 errors" in result


def test_query_datadog_all_with_monitors_and_events() -> None:
    ev = {
        "datadog_logs": [{}] * 2,
        "datadog_monitors": [{}] * 3,
        "datadog_events": [{}] * 4,
    }
    result = _format_tool_calls_line(_ctx(["query_datadog_all"], ev), link_fn=_LINK_FN)
    assert "2 logs" in result
    assert "3 monitors" in result
    assert "4 events" in result


def test_query_datadog_all_with_fetch_ms() -> None:
    ev = {
        "datadog_logs": [{}],
        "datadog_fetch_ms": {"query1": 1500, "query2": 3000},
    }
    result = _format_tool_calls_line(_ctx(["query_datadog_all"], ev), link_fn=_LINK_FN)
    assert "fetched in 3.0s" in result


def test_unknown_action_falls_back_to_humanized_name() -> None:
    result = _format_tool_calls_line(_ctx(["some_custom_tool"], {}), link_fn=_LINK_FN)
    assert "some custom tool" in result


def test_query_datadog_logs_empty_returns_bare_label() -> None:
    ev: dict = {}
    result = _format_tool_calls_line(_ctx(["query_datadog_logs"], ev), link_fn=_LINK_FN)
    assert "Datadog Logs" in result
    assert "(" not in result.split("Datadog Logs")[1].split(",")[0]


def test_query_datadog_all_empty_returns_bare_label() -> None:
    ev: dict = {}
    result = _format_tool_calls_line(_ctx(["query_datadog_all"], ev), link_fn=_LINK_FN)
    assert "Datadog" in result


def test_query_datadog_all_with_only_errors() -> None:
    ev = {"datadog_error_logs": [{}] * 2}
    result = _format_tool_calls_line(_ctx(["query_datadog_all"], ev), link_fn=_LINK_FN)
    assert "2 errors" in result


# ---------------------------------------------------------------------------
# format_cited_evidence_section — branch coverage
# ---------------------------------------------------------------------------


def _ctx_for_cited(catalog: dict, actions: list[str] | None = None, evidence: dict | None = None) -> dict:
    return {
        "evidence_catalog": catalog,
        "executed_hypotheses": [{"actions": actions or []}],
        "evidence": evidence or {},
        "grafana_endpoint": "",
        "datadog_site": "datadoghq.com",
    }


def test_format_cited_evidence_section_with_provenance_and_snippet() -> None:
    from app.delivery.publish_findings.formatters.evidence import format_cited_evidence_section

    catalog = {
        "evidence/grafana/logs": {
            "display_id": "E1",
            "label": "Grafana Loki",
            "url": None,
            "summary": "5 logs",
            "provenance": "instance=prod.grafana.net",
            "snippet": "Connection refused",
        }
    }
    ctx = _ctx_for_cited(catalog)
    result = format_cited_evidence_section(ctx)
    assert "Cited Evidence" in result
    assert "provenance: instance=prod.grafana.net" in result
    assert "Connection refused" in result


def test_format_cited_evidence_section_skips_failed_pod_entries() -> None:
    from app.delivery.publish_findings.formatters.evidence import format_cited_evidence_section

    catalog = {
        "evidence/datadog/failed_pod/pod-abc": {
            "display_id": "FP1",
            "label": "Failed Pod",
            "url": None,
            "summary": None,
            "provenance": None,
            "snippet": None,
        }
    }
    ctx = _ctx_for_cited(catalog)
    result = format_cited_evidence_section(ctx)
    assert result == ""


def test_format_cited_evidence_section_empty_catalog_and_no_tool_calls() -> None:
    from app.delivery.publish_findings.formatters.evidence import format_cited_evidence_section

    ctx = _ctx_for_cited({})
    result = format_cited_evidence_section(ctx)
    assert result == ""


def test_format_cited_evidence_section_with_tool_calls_line() -> None:
    from app.delivery.publish_findings.formatters.evidence import format_cited_evidence_section

    ev = {"list_role_assignments": {"available": True, "total_returned": 2}}
    ctx = _ctx_for_cited({}, actions=["list_role_assignments"], evidence=ev)
    result = format_cited_evidence_section(ctx)
    assert "Cited Evidence" in result
    assert "Azure RBAC" in result
