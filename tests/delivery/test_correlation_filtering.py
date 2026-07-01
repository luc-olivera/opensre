"""Unit tests for _format_correlation_lines filtering logic.

Run with:
    PYTHONPATH=. /Users/lucas.zago/mamba/envs/cn-ai/bin/python3 -m pytest \
        tests/delivery/test_correlation_filtering.py -q --noconftest
"""

from __future__ import annotations

from tests.delivery._formatter_stubs import bootstrap_formatter_modules

bootstrap_formatter_modules()

import pytest

from app.delivery.publish_findings.formatters.report import (
    _format_correlation_lines,
    build_slack_blocks,
    format_slack_message,
)
from app.delivery.publish_findings.report_context import build_report_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx_with_correlation(correlation: object) -> dict:
    return {"correlation": correlation}


def _make_signal(name: str = "sig", source: str = "dd", score: object = 0.95) -> dict:
    return {"name": name, "source": source, "score": score}


def _make_driver(name: str = "drv", confidence: object = 0.91, rationale: str = "r") -> dict:
    return {"name": name, "confidence": confidence, "rationale": rationale}


# ---------------------------------------------------------------------------
# Signal score boundary tests
# ---------------------------------------------------------------------------


def test_signal_score_0_4_survives() -> None:
    ctx = _ctx_with_correlation({"correlated_signals": [_make_signal(score=0.4)], "most_likely_causal_drivers": []})
    signals, _ = _format_correlation_lines(ctx)
    assert len(signals) == 1
    assert "score=0.40" in signals[0]


def test_signal_score_0_39_dropped() -> None:
    ctx = _ctx_with_correlation({"correlated_signals": [_make_signal(score=0.39)], "most_likely_causal_drivers": []})
    signals, _ = _format_correlation_lines(ctx)
    assert signals == []


def test_signal_score_0_int_dropped() -> None:
    ctx = _ctx_with_correlation({"correlated_signals": [_make_signal(score=0)], "most_likely_causal_drivers": []})
    signals, _ = _format_correlation_lines(ctx)
    assert signals == []


def test_signal_no_score_key_preserved() -> None:
    signal = {"name": "mysig", "source": "dd"}
    ctx = _ctx_with_correlation({"correlated_signals": [signal], "most_likely_causal_drivers": []})
    signals, _ = _format_correlation_lines(ctx)
    assert len(signals) == 1
    assert "mysig" in signals[0]
    assert "score=" not in signals[0]


def test_signal_score_none_preserved() -> None:
    ctx = _ctx_with_correlation({"correlated_signals": [_make_signal(score=None)], "most_likely_causal_drivers": []})
    signals, _ = _format_correlation_lines(ctx)
    assert len(signals) == 1
    assert "score=" not in signals[0]


def test_signal_score_string_preserved() -> None:
    ctx = _ctx_with_correlation({"correlated_signals": [_make_signal(score="high")], "most_likely_causal_drivers": []})
    signals, _ = _format_correlation_lines(ctx)
    assert len(signals) == 1
    assert "score=" not in signals[0]


# ---------------------------------------------------------------------------
# Driver confidence boundary tests
# ---------------------------------------------------------------------------


def test_driver_confidence_0_4_survives() -> None:
    ctx = _ctx_with_correlation({
        "correlated_signals": [],
        "most_likely_causal_drivers": [_make_driver(confidence=0.4)],
    })
    _, drivers = _format_correlation_lines(ctx)
    assert len(drivers) == 1
    assert "confidence=0.40" in drivers[0]
    assert "— r" in drivers[0]


def test_driver_confidence_0_39_dropped() -> None:
    ctx = _ctx_with_correlation({
        "correlated_signals": [],
        "most_likely_causal_drivers": [_make_driver(confidence=0.39)],
    })
    _, drivers = _format_correlation_lines(ctx)
    assert drivers == []


def test_driver_missing_confidence_preserved() -> None:
    driver = {"name": "mydrv", "rationale": "some reason"}
    ctx = _ctx_with_correlation({"correlated_signals": [], "most_likely_causal_drivers": [driver]})
    _, drivers = _format_correlation_lines(ctx)
    assert len(drivers) == 1
    assert "mydrv" in drivers[0]
    assert "confidence=" not in drivers[0]


def test_driver_confidence_none_preserved() -> None:
    ctx = _ctx_with_correlation({
        "correlated_signals": [],
        "most_likely_causal_drivers": [_make_driver(confidence=None)],
    })
    _, drivers = _format_correlation_lines(ctx)
    assert len(drivers) == 1
    assert "confidence=" not in drivers[0]


# ---------------------------------------------------------------------------
# Mixed signals: ordering preserved
# ---------------------------------------------------------------------------


def test_mixed_signals_order_preserved() -> None:
    signals = [
        _make_signal(name="high-sig", score=0.95),
        _make_signal(name="low-sig", score=0.39),
        {"name": "no-score-sig", "source": "dd"},  # no score → preserved
    ]
    ctx = _ctx_with_correlation({"correlated_signals": signals, "most_likely_causal_drivers": []})
    result_signals, _ = _format_correlation_lines(ctx)
    assert len(result_signals) == 2
    assert "high-sig" in result_signals[0]
    assert "no-score-sig" in result_signals[1]


# ---------------------------------------------------------------------------
# All below threshold → empty
# ---------------------------------------------------------------------------


def test_all_below_threshold_both_lists_empty() -> None:
    ctx = _ctx_with_correlation({
        "correlated_signals": [_make_signal(score=0.1)],
        "most_likely_causal_drivers": [_make_driver(confidence=0.1)],
    })
    signals, drivers = _format_correlation_lines(ctx)
    assert signals == []
    assert drivers == []


# ---------------------------------------------------------------------------
# Edge cases: bad correlation value
# ---------------------------------------------------------------------------


def test_correlation_not_a_dict_string() -> None:
    ctx = _ctx_with_correlation("nope")
    signals, drivers = _format_correlation_lines(ctx)
    assert signals == []
    assert drivers == []


def test_correlation_empty_dict() -> None:
    ctx = _ctx_with_correlation({})
    signals, drivers = _format_correlation_lines(ctx)
    assert signals == []
    assert drivers == []


def test_non_dict_entries_in_signals_list() -> None:
    valid = _make_signal(name="valid-sig", score=0.95)
    ctx = _ctx_with_correlation({
        "correlated_signals": [None, "x", valid],
        "most_likely_causal_drivers": [],
    })
    signals, _ = _format_correlation_lines(ctx)
    assert len(signals) == 1
    assert "valid-sig" in signals[0]


def test_non_dict_entries_in_drivers_list() -> None:
    valid = _make_driver(name="valid-drv", confidence=0.91)
    ctx = _ctx_with_correlation({
        "correlated_signals": [],
        "most_likely_causal_drivers": [None, "x", valid],
    })
    _, drivers = _format_correlation_lines(ctx)
    assert len(drivers) == 1
    assert "valid-drv" in drivers[0]


# ---------------------------------------------------------------------------
# Section omission in format_slack_message and build_slack_blocks
# ---------------------------------------------------------------------------


def _make_state_with_correlation(correlation: object) -> dict:
    return {
        "alert_name": "RDS CPU spike",
        "pipeline_name": "rds-postgres",
        "severity": "warning",
        "root_cause": "Root cause.",
        "root_cause_category": "application_tier_load_spike",
        "validated_claims": [],
        "non_validated_claims": [],
        "evidence": {},
        "available_sources": {},
        "investigation_started_at": 0.0,
        "correlation": correlation,
    }


def test_format_slack_message_omits_upstream_correlation_when_all_filtered() -> None:
    state = _make_state_with_correlation({
        "correlated_signals": [_make_signal(score=0.1)],
        "most_likely_causal_drivers": [_make_driver(confidence=0.1)],
    })
    ctx = build_report_context(state)
    message = format_slack_message(ctx)
    assert "Upstream Correlation" not in message


def test_format_slack_message_includes_upstream_correlation_when_signal_passes() -> None:
    state = _make_state_with_correlation({
        "correlated_signals": [_make_signal(name="orders-asg", score=0.95)],
        "most_likely_causal_drivers": [],
    })
    ctx = build_report_context(state)
    message = format_slack_message(ctx)
    assert "Upstream Correlation" in message
    assert "orders-asg" in message


def test_build_slack_blocks_omits_upstream_correlation_when_all_filtered() -> None:
    state = _make_state_with_correlation({
        "correlated_signals": [_make_signal(score=0.1)],
        "most_likely_causal_drivers": [_make_driver(confidence=0.1)],
    })
    ctx = build_report_context(state)
    blocks = build_slack_blocks(ctx)
    assert "Upstream Correlation" not in str(blocks)


def test_build_slack_blocks_includes_upstream_correlation_when_signal_passes() -> None:
    state = _make_state_with_correlation({
        "correlated_signals": [_make_signal(name="orders-asg", score=0.95)],
        "most_likely_causal_drivers": [],
    })
    ctx = build_report_context(state)
    blocks = build_slack_blocks(ctx)
    block_text = str(blocks)
    assert "Upstream Correlation" in block_text
    assert "orders-asg" in block_text
