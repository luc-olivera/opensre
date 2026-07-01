"""Unit tests for _severity_slack_header_text and its integration in build_slack_blocks.

Run with:
    PYTHONPATH=. /Users/lucas.zago/mamba/envs/cn-ai/bin/python3 -m pytest \
        tests/delivery/test_slack_severity_header.py -q --noconftest
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Bootstrap formatter modules BEFORE any app imports.
# Uses the shared helper that is idempotent across multi-file pytest sessions.
# ---------------------------------------------------------------------------
from tests.delivery._formatter_stubs import bootstrap_formatter_modules

bootstrap_formatter_modules()

# ---------------------------------------------------------------------------
# Now safe to import from app
# ---------------------------------------------------------------------------

import pytest

from app.delivery.publish_findings.formatters.report import (
    _severity_slack_header_text,
    build_slack_blocks,
)


# ---------------------------------------------------------------------------
# Direct tests on _severity_slack_header_text
# ---------------------------------------------------------------------------


def test_critical_exact_output() -> None:
    ctx = {"severity": "critical", "alert_name": "DB down", "pipeline_name": "orders"}
    assert _severity_slack_header_text(ctx) == "🔴 DB down · orders"


@pytest.mark.parametrize(
    "severity, expected_emoji",
    [
        ("warning", "🟡"),
        ("high", "🟠"),
        ("error", "🟠"),
        ("info", "🟢"),
        ("low", "🟢"),
        ("none", "⚪"),
        ("healthy", "🟢"),
        ("normal", "🟢"),
    ],
)
def test_parametrized_emoji_map(severity: str, expected_emoji: str) -> None:
    ctx = {"severity": severity, "alert_name": "Alert", "pipeline_name": "pipe"}
    result = _severity_slack_header_text(ctx)
    assert result.startswith(expected_emoji), (
        f"Expected {expected_emoji} for severity={severity!r}, got {result!r}"
    )


def test_unknown_severity_bogus() -> None:
    ctx = {"severity": "bogus", "alert_name": "Alert", "pipeline_name": "pipe"}
    result = _severity_slack_header_text(ctx)
    assert result.startswith("⚠️")


def test_severity_none_value() -> None:
    ctx = {"severity": None, "alert_name": "Alert", "pipeline_name": "pipe"}
    result = _severity_slack_header_text(ctx)
    assert result.startswith("⚠️")


def test_missing_severity_key() -> None:
    ctx = {"alert_name": "Alert", "pipeline_name": "pipe"}
    result = _severity_slack_header_text(ctx)
    assert result.startswith("⚠️")


def test_severity_strip_and_lower() -> None:
    ctx = {"severity": "  CRITICAL  ", "alert_name": "Alert", "pipeline_name": "pipe"}
    result = _severity_slack_header_text(ctx)
    assert result.startswith("🔴")


def test_defaults_no_alert_no_pipeline() -> None:
    ctx: dict = {"severity": "info"}
    result = _severity_slack_header_text(ctx)
    assert result == "🟢 Alert · unknown"


def test_defaults_alert_none_pipeline_none_explicit() -> None:
    ctx = {"severity": "info", "alert_name": None, "pipeline_name": None}
    result = _severity_slack_header_text(ctx)
    assert result == "🟢 Alert · unknown"


def test_non_string_alert_name_coercion() -> None:
    ctx = {"severity": "info", "alert_name": 123, "pipeline_name": "pipe"}
    result = _severity_slack_header_text(ctx)
    assert "123" in result
    # Verify no exception was raised (we reached this point)


def test_truncation_over_150() -> None:
    # emoji(1) + " "(1) + alert(80) + " · "(3) + pipeline(80) = 165 chars → truncated
    long_alert = "A" * 80
    long_pipeline = "B" * 80
    ctx = {"severity": "info", "alert_name": long_alert, "pipeline_name": long_pipeline}
    result = _severity_slack_header_text(ctx)
    assert len(result) == 148
    assert result.endswith("…")


def test_truncation_boundary_exactly_150() -> None:
    # emoji(1) + " "(1) + alert(72) + " · "(3) + pipeline(73) = 150 chars → not truncated
    alert = "A" * 72
    pipeline = "B" * 73
    ctx = {"severity": "info", "alert_name": alert, "pipeline_name": pipeline}
    result = _severity_slack_header_text(ctx)
    assert len(result) == 150
    assert "…" not in result


# ---------------------------------------------------------------------------
# Integration: build_slack_blocks prepends the header block
# ---------------------------------------------------------------------------


def _minimal_ctx_for_blocks() -> dict:
    """Minimal ctx that build_slack_blocks can process without crashing."""
    return {
        "severity": "critical",
        "alert_name": "DB down",
        "pipeline_name": "orders",
        "evidence": {},
        "executed_hypotheses": [],
        "validated_claims": [],
        "non_validated_claims": [],
        "remediation_steps": [],
        "source_provenance": {},
        "evidence_catalog": {},
        "datadog_site": "datadoghq.com",
        "grafana_endpoint": "",
    }


def test_build_slack_blocks_header_block_structure() -> None:
    ctx = _minimal_ctx_for_blocks()
    blocks = build_slack_blocks(ctx)

    assert blocks[0]["type"] == "header"
    assert blocks[0]["text"]["type"] == "plain_text"
    assert blocks[0]["text"]["emoji"] is True
    assert blocks[0]["text"]["text"] == _severity_slack_header_text(ctx)


# ---------------------------------------------------------------------------
# build_slack_blocks branch coverage: conditional sections
# ---------------------------------------------------------------------------


def test_build_slack_blocks_with_validated_claims_shows_findings_header() -> None:
    ctx = _minimal_ctx_for_blocks()
    ctx["validated_claims"] = [
        {"claim": "The DB was overloaded.", "evidence_ids": [], "evidence_labels": []}
    ]
    blocks = build_slack_blocks(ctx)
    header_texts = [b.get("text", {}).get("text", "") for b in blocks if b.get("type") == "header"]
    assert any("Findings" in t for t in header_texts)


def test_build_slack_blocks_with_non_validated_claims_renders_inferred_section() -> None:
    ctx = _minimal_ctx_for_blocks()
    ctx["non_validated_claims"] = [{"claim": "Maybe the network was slow."}]
    blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "Inferred" in block_text


def test_build_slack_blocks_with_provenance_shows_provenance_header() -> None:
    ctx = _minimal_ctx_for_blocks()
    ctx["source_provenance"] = {
        "grafana": {"label": "Grafana", "summary": "instance=prod.grafana.net"}
    }
    blocks = build_slack_blocks(ctx)
    header_texts = [b.get("text", {}).get("text", "") for b in blocks if b.get("type") == "header"]
    assert any("Provenance" in t for t in header_texts)


def test_build_slack_blocks_with_remediation_shows_recommended_actions_header() -> None:
    ctx = _minimal_ctx_for_blocks()
    ctx["remediation_steps"] = ["Restart the service"]
    blocks = build_slack_blocks(ctx)
    header_texts = [b.get("text", {}).get("text", "") for b in blocks if b.get("type") == "header"]
    assert any("Recommended Actions" in t for t in header_texts)


def test_build_slack_blocks_with_duration_and_alert_id_shows_meta() -> None:
    ctx = _minimal_ctx_for_blocks()
    ctx["investigation_duration_seconds"] = 42
    ctx["alert_id"] = "alert-123"
    blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "42s" in block_text
    assert "alert-123" in block_text


def test_build_slack_blocks_with_evidence_catalog_shows_cited_section() -> None:
    ctx = _minimal_ctx_for_blocks()
    ctx["evidence_catalog"] = {
        "evidence/grafana/logs": {
            "display_id": "E1",
            "label": "Grafana Loki",
            "url": None,
            "summary": "5 logs",
            "provenance": None,
            "snippet": None,
        }
    }
    blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "E1" in block_text or "Grafana Loki" in block_text


def test_build_slack_blocks_top_log_in_evidence_appended_to_root_cause() -> None:
    ctx = _minimal_ctx_for_blocks()
    ctx["evidence"] = {"datadog_error_logs": [{"message": "connection refused"}]}
    blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "connection refused" in block_text


def test_build_slack_blocks_truncates_at_50_blocks() -> None:
    """When items produce many blocks, result stays ≤50."""
    ctx = _minimal_ctx_for_blocks()
    ctx["remediation_steps"] = [f"Step {i}" for i in range(8)]
    ctx["validated_claims"] = [
        {"claim": f"Claim {i}.", "evidence_ids": [], "evidence_labels": []} for i in range(10)
    ]
    ctx["source_provenance"] = {
        f"source_{i}": {"label": f"Source {i}", "summary": f"info={i}"} for i in range(10)
    }
    blocks = build_slack_blocks(ctx)
    assert len(blocks) <= 50


def test_build_slack_blocks_with_causal_driver_shows_driver_text() -> None:
    """Exercises the driver_lines section of build_slack_blocks (line 807)."""
    ctx = _minimal_ctx_for_blocks()
    ctx["correlation"] = {
        "correlated_signals": [],
        "most_likely_causal_drivers": [
            {"name": "web-tier", "confidence": 0.91, "rationale": "Time-aligned."}
        ],
    }
    blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "web-tier" in block_text


def test_build_slack_blocks_with_cloudwatch_url_shows_cw_link() -> None:
    """Exercises the CloudWatch link branch of build_slack_blocks (line 857)."""
    ctx = _minimal_ctx_for_blocks()
    ctx["cloudwatch_logs_url"] = "https://us-east-1.console.aws.amazon.com/cloudwatch/logs"
    blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "CloudWatch" in block_text


def test_build_slack_blocks_with_failed_pods_shows_failed_pods_section() -> None:
    """Exercises the Failed Pods branch of build_slack_blocks (lines 772-779)."""
    from unittest.mock import patch

    ctx = _minimal_ctx_for_blocks()
    with (
        patch(
            "app.delivery.publish_findings.formatters.report.get_failed_pods",
            return_value=[{"pod_name": "payments-pod-1"}],
        ),
        patch(
            "app.delivery.publish_findings.formatters.report.format_pod_line",
            return_value="• payments-pod-1",
        ),
    ):
        blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "Failed Pods" in block_text
    assert "payments-pod-1" in block_text


def test_build_slack_blocks_with_more_than_5_pods_shows_overflow_message() -> None:
    """Exercises the >5 pods overflow line of build_slack_blocks (line 770)."""
    from unittest.mock import patch

    pods = [{"pod_name": f"pod-{i}"} for i in range(7)]
    ctx = _minimal_ctx_for_blocks()
    with (
        patch(
            "app.delivery.publish_findings.formatters.report.get_failed_pods",
            return_value=pods,
        ),
        patch(
            "app.delivery.publish_findings.formatters.report.format_pod_line",
            return_value="• pod-name",
        ),
    ):
        blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "2 more pods" in block_text


def test_build_slack_blocks_with_investigation_trace_shows_trace_section() -> None:
    """Exercises the Investigation Trace branch of build_slack_blocks (lines 839-846)."""
    from unittest.mock import patch

    ctx = _minimal_ctx_for_blocks()
    with patch(
        "app.delivery.publish_findings.formatters.report.build_investigation_trace",
        return_value=["Step 1: queried Grafana", "Step 2: checked Datadog"],
    ):
        blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "Investigation Trace" in block_text
    assert "Step 1" in block_text


def test_build_slack_blocks_50_block_truncation_applied() -> None:
    """Exercises the '>50 blocks' truncation path (line 877)."""
    from unittest.mock import patch

    ctx = _minimal_ctx_for_blocks()
    ctx["validated_claims"] = [
        {"claim": f"Claim {i}.", "evidence_ids": [], "evidence_labels": []} for i in range(10)
    ]
    ctx["remediation_steps"] = [f"step {i}" for i in range(8)]
    ctx["source_provenance"] = {
        f"src_{i}": {"label": f"L{i}", "summary": f"s={i}"} for i in range(10)
    }
    ctx["investigation_duration_seconds"] = 60
    ctx["alert_id"] = "test-alert"
    with (
        patch(
            "app.delivery.publish_findings.formatters.report.build_investigation_trace",
            return_value=[f"trace step {i}" for i in range(30)],
        ),
        patch(
            "app.delivery.publish_findings.formatters.report.get_failed_pods",
            return_value=[{"pod_name": f"pod-{i}"} for i in range(5)],
        ),
        patch(
            "app.delivery.publish_findings.formatters.report.format_pod_line",
            return_value="• pod-name",
        ),
    ):
        blocks = build_slack_blocks(ctx)
    assert len(blocks) <= 50
