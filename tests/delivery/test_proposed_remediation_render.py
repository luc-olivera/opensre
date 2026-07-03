"""Unit tests for the "guided remediation Phase 1 (propose-only)" rendering logic.

Tests cover _remediation_proposal_fields, build_slack_blocks, format_slack_message,
and format_telegram_message in app.delivery.publish_findings.formatters.report.

Run with:
    PYTHONPATH=. /Users/lucas.zago/mamba/envs/cn-ai/bin/python3 -m pytest \
        tests/delivery/test_proposed_remediation_render.py -q --noconftest
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Bootstrap formatter modules BEFORE any app imports (idempotent).
# ---------------------------------------------------------------------------
from tests.delivery._formatter_stubs import bootstrap_formatter_modules

bootstrap_formatter_modules()

# ---------------------------------------------------------------------------
# Now safe to import from app
# ---------------------------------------------------------------------------

import enum
import html

import pytest


class _FakeActionEnum(str, enum.Enum):
    """Mimics RemediationActionType: str(member) renders "ClassName.member",
    so this reproduces the enum-instance path the live run exposed."""

    grant_acr_pull = "grant_acr_pull"

from app.delivery.publish_findings.formatters.report import (
    _remediation_proposal_fields,
    build_slack_blocks,
    format_slack_message,
    format_telegram_message,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_ctx() -> dict:
    """Minimal ctx that all three renderers accept without crashing."""
    return {
        "severity": "high",
        "alert_name": "DB degraded",
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
        "root_cause": "Memory leak in worker thread.",
    }


def _ctx_with_proposal(action_type: str = "rollback_revision", **overrides) -> dict:
    ctx = _base_ctx()
    proposal: dict = {
        "action_type": action_type,
        "target": "app--revision-5",
        "exact_command": "az containerapp revision activate --revision app--revision-4",
        "risk": "medium",
        "rationale": "Bad deploy broke health check.",
        "confidence": 0.88,
    }
    proposal.update(overrides)
    ctx["proposed_remediation"] = proposal
    return ctx


def _header_texts(blocks: list[dict]) -> list[str]:
    return [b.get("text", {}).get("text", "") for b in blocks if b.get("type") == "header"]


def _block_index_for_header(blocks: list[dict], header_text: str) -> int | None:
    for i, block in enumerate(blocks):
        if block.get("type") == "header" and header_text in str(block):
            return i
    return None


# ---------------------------------------------------------------------------
# A. _remediation_proposal_fields
# ---------------------------------------------------------------------------


class TestRemediationProposalFields:
    def test_returns_none_for_empty_dict(self) -> None:
        assert _remediation_proposal_fields({"proposed_remediation": {}}) is None

    def test_returns_none_for_action_type_none(self) -> None:
        assert _remediation_proposal_fields({"proposed_remediation": {"action_type": "none"}}) is None

    def test_returns_none_for_empty_action_type_string(self) -> None:
        assert _remediation_proposal_fields({"proposed_remediation": {"action_type": ""}}) is None

    def test_returns_none_for_non_dict_proposal(self) -> None:
        assert _remediation_proposal_fields({"proposed_remediation": "rollback_revision"}) is None

    def test_returns_none_for_missing_key(self) -> None:
        assert _remediation_proposal_fields(_base_ctx()) is None

    def test_action_type_enum_instance_is_unwrapped(self) -> None:
        # Regression: a live run passed a RemediationActionType enum instance,
        # and str(enum).lower() rendered "remediationactiontype.grant_acr_pull".
        # The helper must unwrap via .value → "grant_acr_pull".
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {"action_type": _FakeActionEnum.grant_acr_pull}
        result = _remediation_proposal_fields(ctx)
        assert result is not None
        assert result["action"] == "grant_acr_pull"

    def test_returns_populated_dict_for_real_proposal(self) -> None:
        ctx = _ctx_with_proposal()
        result = _remediation_proposal_fields(ctx)
        assert result is not None
        assert result["action"] == "rollback_revision"
        assert result["target"] == "app--revision-5"
        assert result["command"] == "az containerapp revision activate --revision app--revision-4"
        assert result["risk"] == "medium"
        assert result["rationale"] == "Bad deploy broke health check."

    def test_risk_is_lowercased(self) -> None:
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {"action_type": "restart_revision", "risk": "HIGH"}
        result = _remediation_proposal_fields(ctx)
        assert result is not None
        assert result["risk"] == "high"

    def test_missing_risk_defaults_to_low(self) -> None:
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {"action_type": "restart_revision"}
        result = _remediation_proposal_fields(ctx)
        assert result is not None
        assert result["risk"] == "low"

    def test_action_is_lowercased_and_stripped(self) -> None:
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {"action_type": "  GRANT_ACR_PULL  "}
        result = _remediation_proposal_fields(ctx)
        assert result is not None
        assert result["action"] == "grant_acr_pull"

    def test_confidence_is_preserved(self) -> None:
        ctx = _ctx_with_proposal()
        result = _remediation_proposal_fields(ctx)
        assert result is not None
        assert result["confidence"] == pytest.approx(0.88)

    def test_none_action_type_value_from_normalized_none_string(self) -> None:
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {"action_type": "  none  "}
        assert _remediation_proposal_fields(ctx) is None


# ---------------------------------------------------------------------------
# B. build_slack_blocks — proposal present
# ---------------------------------------------------------------------------


class TestBuildSlackBlocksWithProposal:
    def test_proposed_remediation_header_block_present(self) -> None:
        blocks = build_slack_blocks(_ctx_with_proposal())
        assert any("Proposed Remediation" in t for t in _header_texts(blocks))

    def test_exact_command_in_code_fence(self) -> None:
        blocks = build_slack_blocks(_ctx_with_proposal())
        block_text = str(blocks)
        # Slack uses triple backtick code fences for commands
        assert "```" in block_text
        assert "az containerapp revision activate" in block_text

    def test_risk_shown_in_blocks(self) -> None:
        blocks = build_slack_blocks(_ctx_with_proposal())
        block_text = str(blocks)
        assert "medium" in block_text

    def test_not_executed_disclaimer_present(self) -> None:
        blocks = build_slack_blocks(_ctx_with_proposal())
        block_text = str(blocks)
        assert "not executed" in block_text

    @pytest.mark.parametrize(
        "action_type",
        [
            "rollback_revision",
            "restart_revision",
            "grant_acr_pull",
            "remove_env_var",
            "scale_revision",
            "manual",
        ],
    )
    def test_header_present_for_all_actionable_types(self, action_type: str) -> None:
        ctx = _ctx_with_proposal(action_type=action_type)
        if action_type == "manual":
            # manual typically has no command
            ctx["proposed_remediation"]["exact_command"] = ""
        blocks = build_slack_blocks(ctx)
        headers = _header_texts(blocks)
        assert any("Proposed Remediation" in t for t in headers), (
            f"Expected 'Proposed Remediation' header for action_type={action_type!r}"
        )

    def test_target_present_in_blocks_when_set(self) -> None:
        blocks = build_slack_blocks(_ctx_with_proposal())
        block_text = str(blocks)
        assert "app--revision-5" in block_text

    def test_rationale_present_in_blocks_when_set(self) -> None:
        blocks = build_slack_blocks(_ctx_with_proposal())
        block_text = str(blocks)
        assert "Bad deploy broke health check" in block_text


# ---------------------------------------------------------------------------
# B. build_slack_blocks — no/null proposal
# ---------------------------------------------------------------------------


class TestBuildSlackBlocksWithoutProposal:
    def test_empty_proposal_dict_no_header(self) -> None:
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {}
        blocks = build_slack_blocks(ctx)
        assert not any("Proposed Remediation" in t for t in _header_texts(blocks))

    def test_action_type_none_no_header(self) -> None:
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {"action_type": "none"}
        blocks = build_slack_blocks(ctx)
        assert not any("Proposed Remediation" in t for t in _header_texts(blocks))

    def test_missing_proposed_remediation_key_no_header(self) -> None:
        blocks = build_slack_blocks(_base_ctx())
        assert not any("Proposed Remediation" in t for t in _header_texts(blocks))


# ---------------------------------------------------------------------------
# B. Placement: Proposed Remediation is after Recommended Actions
# ---------------------------------------------------------------------------


class TestBlockPlacement:
    def test_proposed_remediation_after_recommended_actions(self) -> None:
        ctx = _ctx_with_proposal()
        ctx["remediation_steps"] = ["Restart the pod"]
        blocks = build_slack_blocks(ctx)

        pr_idx = _block_index_for_header(blocks, "Proposed Remediation")
        ra_idx = _block_index_for_header(blocks, "Recommended Actions")

        assert pr_idx is not None, "Proposed Remediation header not found"
        assert ra_idx is not None, "Recommended Actions header not found"
        assert pr_idx > ra_idx, (
            f"Expected Proposed Remediation ({pr_idx}) after Recommended Actions ({ra_idx})"
        )

    def test_proposed_remediation_before_investigation_trace(self) -> None:
        from unittest.mock import patch

        ctx = _ctx_with_proposal()
        ctx["remediation_steps"] = ["Restart the pod"]
        with patch(
            "app.delivery.publish_findings.formatters.report.build_investigation_trace",
            return_value=["Step 1: queried Grafana", "Step 2: checked Datadog"],
        ):
            blocks = build_slack_blocks(ctx)

        pr_idx = _block_index_for_header(blocks, "Proposed Remediation")
        tr_idx = _block_index_for_header(blocks, "Investigation Trace")

        assert pr_idx is not None, "Proposed Remediation header not found"
        assert tr_idx is not None, "Investigation Trace header not found"
        assert pr_idx < tr_idx, (
            f"Expected Proposed Remediation ({pr_idx}) before Investigation Trace ({tr_idx})"
        )


# ---------------------------------------------------------------------------
# C. format_slack_message (text)
# ---------------------------------------------------------------------------


class TestFormatSlackMessage:
    def test_proposal_present_includes_proposed_remediation_heading(self) -> None:
        msg = format_slack_message(_ctx_with_proposal())
        assert "Proposed Remediation" in msg

    def test_proposal_present_includes_command_in_backticks(self) -> None:
        msg = format_slack_message(_ctx_with_proposal())
        assert "`az containerapp revision activate" in msg

    def test_proposal_present_includes_not_executed(self) -> None:
        msg = format_slack_message(_ctx_with_proposal())
        assert "not executed" in msg

    def test_no_proposal_absent_from_message(self) -> None:
        msg = format_slack_message(_base_ctx())
        assert "Proposed Remediation" not in msg

    def test_action_type_none_absent_from_message(self) -> None:
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {"action_type": "none"}
        msg = format_slack_message(ctx)
        assert "Proposed Remediation" not in msg


# ---------------------------------------------------------------------------
# D. format_telegram_message (HTML)
# ---------------------------------------------------------------------------


class TestFormatTelegramMessage:
    def test_proposal_present_includes_proposed_remediation_heading(self) -> None:
        tel = format_telegram_message(_ctx_with_proposal())
        assert "Proposed Remediation" in tel

    def test_proposal_present_includes_code_tag_command(self) -> None:
        tel = format_telegram_message(_ctx_with_proposal())
        assert "<code>" in tel
        assert "az containerapp revision activate" in tel

    def test_proposal_present_includes_not_executed(self) -> None:
        tel = format_telegram_message(_ctx_with_proposal())
        assert "not executed" in tel

    def test_no_proposal_absent_from_telegram(self) -> None:
        tel = format_telegram_message(_base_ctx())
        assert "Proposed Remediation" not in tel

    def test_html_metachar_in_command_is_escaped(self) -> None:
        """Commands with shell/HTML special chars must be html.escaped in Telegram output."""
        dangerous_cmd = 'az rest --query "[?a>b]" & echo done'
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {
            "action_type": "grant_acr_pull",
            "target": "registry.io",
            "exact_command": dangerous_cmd,
            "risk": "low",
        }
        tel = format_telegram_message(ctx)
        expected = html.escape(dangerous_cmd)
        assert expected in tel, f"Expected html-escaped command in output. Got:\n{tel}"

    def test_html_metachar_raw_ampersand_not_in_telegram(self) -> None:
        """The raw ' & ' must not appear — only '&amp;' is acceptable."""
        dangerous_cmd = "cmd1 & cmd2"
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {
            "action_type": "restart_revision",
            "target": "rev-1",
            "exact_command": dangerous_cmd,
            "risk": "low",
        }
        tel = format_telegram_message(ctx)
        # Verify raw unescaped ampersand-space is absent
        assert " & " not in tel

    def test_action_type_none_absent_from_telegram(self) -> None:
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {"action_type": "none"}
        tel = format_telegram_message(ctx)
        assert "Proposed Remediation" not in tel


# ---------------------------------------------------------------------------
# E. Manual action (empty command + rationale)
# ---------------------------------------------------------------------------


class TestManualActionRendering:
    def _manual_ctx(self) -> dict:
        ctx = _base_ctx()
        ctx["proposed_remediation"] = {
            "action_type": "manual",
            "target": "",
            "exact_command": "",
            "risk": "high",
            "rationale": "Check Azure Activity Log for unexpected changes.",
            "confidence": 0.6,
        }
        return ctx

    def test_slack_blocks_shows_proposed_remediation_header(self) -> None:
        blocks = build_slack_blocks(self._manual_ctx())
        assert any("Proposed Remediation" in t for t in _header_texts(blocks))

    def test_slack_blocks_shows_rationale(self) -> None:
        blocks = build_slack_blocks(self._manual_ctx())
        block_text = str(blocks)
        assert "Check Azure Activity Log" in block_text

    def test_slack_blocks_shows_not_executed(self) -> None:
        blocks = build_slack_blocks(self._manual_ctx())
        block_text = str(blocks)
        assert "not executed" in block_text

    def test_slack_message_shows_rationale(self) -> None:
        msg = format_slack_message(self._manual_ctx())
        assert "Check Azure Activity Log" in msg

    def test_slack_message_shows_not_executed(self) -> None:
        msg = format_slack_message(self._manual_ctx())
        assert "not executed" in msg

    def test_telegram_shows_rationale(self) -> None:
        tel = format_telegram_message(self._manual_ctx())
        assert "Check Azure Activity Log" in tel

    def test_telegram_shows_not_executed(self) -> None:
        tel = format_telegram_message(self._manual_ctx())
        assert "not executed" in tel

    def test_slack_blocks_no_code_fence_when_command_empty(self) -> None:
        """When exact_command is empty, no triple-backtick code fence should appear."""
        blocks = build_slack_blocks(self._manual_ctx())
        # Find the proposal section block
        for block in blocks:
            if block.get("type") == "section":
                text = block.get("text", {}).get("text", "")
                if "manual" in text or "Proposed" in text or "Rationale" in text:
                    assert "```" not in text, (
                        f"Unexpected code fence in manual proposal block: {text!r}"
                    )
