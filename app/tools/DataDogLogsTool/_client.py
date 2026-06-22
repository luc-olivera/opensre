"""Shared Datadog client factories and call helpers for tool actions."""

from __future__ import annotations

import os
from typing import Any

from app.services.datadog import DatadogClient, DatadogConfig
from app.services.datadog.client import DatadogAsyncClient

_DEFAULT_SITE = "datadoghq.com"


def _effective_site(site: str | None) -> str:
    """Resolve the Datadog site, honoring the operator's DD_SITE env (SRE-47 fork fix).

    The per-tool ``site`` is derived from the resolved integration dict, which
    falls back to the hardcoded ``datadoghq.com`` when it carries no site — so a
    deployment configured for the EU data zone via ``DD_SITE=datadoghq.eu`` still
    hit ``api.datadoghq.com`` and 403'd. An explicitly-set ``DD_SITE`` is the
    operator's declared region and must win over that default.
    """
    env_site = os.getenv("DD_SITE", "").strip()
    if env_site:
        return env_site
    return (site or "").strip() or _DEFAULT_SITE


def _config(api_key: str, app_key: str, site: str) -> DatadogConfig:
    return DatadogConfig(api_key=api_key, app_key=app_key, site=_effective_site(site))


def make_client(
    api_key: str | None,
    app_key: str | None,
    site: str = _DEFAULT_SITE,
) -> DatadogClient | None:
    if not api_key or not app_key:
        return None
    return DatadogClient(_config(api_key, app_key, site))  # type: ignore[arg-type]


def make_async_client(
    api_key: str | None,
    app_key: str | None,
    site: str = _DEFAULT_SITE,
) -> DatadogAsyncClient | None:
    if not api_key or not app_key:
        return None
    return DatadogAsyncClient(_config(api_key, app_key, site))  # type: ignore[arg-type]


def unavailable(source: str, empty_key: str, error: str, **extra: Any) -> dict[str, Any]:
    """Standardised unavailable response."""
    return {"source": source, "available": False, "error": error, empty_key: [], **extra}
