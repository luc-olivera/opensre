"""Shared stub/load helpers for delivery formatter tests.

All functions here are idempotent — safe to call from multiple test files
collected in the same pytest session (each file's module-level code runs once
during collection; calling _load twice for the same module name must not
replace the already-registered module object, or already-bound ``from ...
import`` references in earlier test files break unittest.mock.patch).

Usage (add this block BEFORE any ``from app...`` imports in each test file):

    from tests.delivery._formatter_stubs import bootstrap_formatter_modules
    bootstrap_formatter_modules()
"""

from __future__ import annotations

import importlib.util
import sys
import types

_BASE = "/Users/lucas.zago/CloudNation/opensre"

_LOADED = set()  # track which modules we've loaded


def _stub(*names: str) -> None:
    for n in names:
        if n not in sys.modules:
            sys.modules[n] = types.ModuleType(n)


def _load(mod_name: str, rel_path: str) -> types.ModuleType:
    """Load a module from file path — idempotent, skips if already in sys.modules."""
    if mod_name in sys.modules and mod_name in _LOADED:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, f"{_BASE}/{rel_path}")
    m = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)  # type: ignore[union-attr]
    _LOADED.add(mod_name)
    return m


def bootstrap_formatter_modules() -> None:
    """Register stubs and load the formatter modules. Idempotent."""
    # Guard: if the formatters are already loaded by an earlier test file, skip.
    if "app.delivery.publish_findings.formatters.report" in _LOADED:
        return

    _stub(
        "app",
        "app.delivery",
        "app.delivery.publish_findings",
        "app.delivery.publish_findings.formatters",
        "app.delivery.publish_findings.urls",
        "app.delivery.publish_findings.urls.aws",
        "app.delivery.publish_findings.formatters.infrastructure",
        "app.state",
    )

    _aws = sys.modules["app.delivery.publish_findings.urls.aws"]
    if not hasattr(_aws, "build_cloudwatch_url"):
        _aws.build_cloudwatch_url = lambda ctx: None  # type: ignore[attr-defined]
        _aws.build_datadog_logs_url = lambda q, site="": None  # type: ignore[attr-defined]
        _aws.build_grafana_explore_url = lambda ep, q="": None  # type: ignore[attr-defined]
        _aws.build_s3_console_url = lambda *a, **kw: None  # type: ignore[attr-defined]

    _infra = sys.modules["app.delivery.publish_findings.formatters.infrastructure"]
    if not hasattr(_infra, "build_investigation_trace"):
        _infra.build_investigation_trace = lambda ctx: []  # type: ignore[attr-defined]
        _infra.format_pod_line = lambda p, site, **kw: ""  # type: ignore[attr-defined]
        _infra.get_failed_pods = lambda ctx: []  # type: ignore[attr-defined]

    _state = sys.modules["app.state"]
    if not hasattr(_state, "InvestigationState"):
        _state.InvestigationState = dict  # type: ignore[attr-defined]

    # Stub report_context with just ReportContext = dict so evidence.py can import it
    if "app.delivery.publish_findings.report_context" not in sys.modules or not hasattr(
        sys.modules["app.delivery.publish_findings.report_context"], "build_report_context"
    ):
        _rc_stub = types.ModuleType("app.delivery.publish_findings.report_context")
        _rc_stub.ReportContext = dict  # type: ignore[attr-defined]
        sys.modules["app.delivery.publish_findings.report_context"] = _rc_stub

    _load(
        "app.delivery.publish_findings.formatters.base",
        "app/delivery/publish_findings/formatters/base.py",
    )
    _load(
        "app.delivery.publish_findings.formatters.evidence",
        "app/delivery/publish_findings/formatters/evidence.py",
    )
    _load(
        "app.delivery.publish_findings.formatters.report",
        "app/delivery/publish_findings/formatters/report.py",
    )

    # Replace the minimal rc_stub with the real report_context module
    if not hasattr(
        sys.modules.get("app.delivery.publish_findings.report_context", types.ModuleType("")),
        "build_report_context",
    ):
        if "app.delivery.publish_findings.report_context" in sys.modules:
            del sys.modules["app.delivery.publish_findings.report_context"]
        _load(
            "app.delivery.publish_findings.report_context",
            "app/delivery/publish_findings/report_context.py",
        )
