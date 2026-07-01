"""Unit tests for _dedup_remediation_steps.

Run with:
    PYTHONPATH=. /Users/lucas.zago/mamba/envs/cn-ai/bin/python3 -m pytest \
        tests/delivery/test_remediation_dedup.py -q --noconftest
"""

from __future__ import annotations

from tests.delivery._formatter_stubs import bootstrap_formatter_modules

bootstrap_formatter_modules()

from app.delivery.publish_findings.formatters.report import _dedup_remediation_steps


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_exact_and_case_and_bullet_duplicates() -> None:
    steps = ["Restart the app", "restart the app", "- Restart the app"]
    result = _dedup_remediation_steps(steps)
    assert result == ["Restart the app"]


def test_multiple_bullet_styles_all_same_key() -> None:
    steps = ["• Scale up", "* Scale up", "1. Scale up", "Scale up"]
    result = _dedup_remediation_steps(steps)
    assert len(result) == 1


def test_whitespace_collapse_first_original_preserved() -> None:
    steps = ["Roll   back\tnow", "Roll back now"]
    result = _dedup_remediation_steps(steps)
    assert len(result) == 1
    assert result[0] == "Roll   back\tnow"


def test_order_preserved_with_duplicates() -> None:
    steps = ["B step", "A step", "B step", "C step"]
    result = _dedup_remediation_steps(steps)
    assert result == ["B step", "A step", "C step"]


def test_empty_and_whitespace_only_skipped() -> None:
    steps = ["", "   ", "\t", "Do X"]
    result = _dedup_remediation_steps(steps)
    assert result == ["Do X"]


def test_bullet_only_entries_skipped() -> None:
    # After stripping the bullet prefix, the key becomes empty → skipped
    steps = ["-", "•", "1.", "Real step"]
    result = _dedup_remediation_steps(steps)
    assert result == ["Real step"]


def test_cap_12_distinct_returns_8() -> None:
    steps = [f"Step {i}" for i in range(12)]
    result = _dedup_remediation_steps(steps)
    assert len(result) == 8
    assert result == steps[:8]


def test_cap_exactly_8_returns_8() -> None:
    steps = [f"Step {i}" for i in range(8)]
    result = _dedup_remediation_steps(steps)
    assert len(result) == 8


def test_cap_9_returns_8() -> None:
    steps = [f"Step {i}" for i in range(9)]
    result = _dedup_remediation_steps(steps)
    assert len(result) == 8


def test_int_coercion() -> None:
    result = _dedup_remediation_steps([123, "123"])
    assert len(result) == 1


def test_empty_list() -> None:
    assert _dedup_remediation_steps([]) == []
