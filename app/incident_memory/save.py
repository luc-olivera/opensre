"""Deterministic post-investigation write of an incident note (SRE-47 Phase 2).

Called from ``app/delivery/publish_findings/node.py`` after the investigation
completes, when the parsed diagnosis (root_cause / category / validity /
remediation) is present on the state. This is NOT a model-invoked tool — the save
must not depend on the LLM choosing to call it.

Best-effort by contract: never raises. A memory failure (DB down, embedding
error, bad config) must never break report delivery.
"""

from __future__ import annotations

import logging
from typing import Any

from app.incident_memory.config import load_config

logger = logging.getLogger(__name__)

# Schema is created lazily on the first successful save, once per process.
_schema_ready = False

# Categories not worth memorizing (no actionable root cause to recall later).
_SKIP_CATEGORIES = {None, "", "unknown"}


def _build_symptom(state: dict[str, Any]) -> str:
    """The text we embed for similarity: alert identity + the framed problem."""
    parts: list[str] = []
    name = state.get("alert_name")
    if name:
        parts.append(str(name))
    problem = state.get("problem_md")
    if problem:
        parts.append(str(problem))
    if not problem:
        raw = state.get("raw_alert") or {}
        if isinstance(raw, dict):
            msg = (
                raw.get("message")
                or raw.get("text")
                or (raw.get("commonAnnotations") or {}).get("summary")
            )
            if msg:
                parts.append(str(msg))
    return "\n\n".join(p for p in parts if p).strip()


def _remediation_text(state: dict[str, Any]) -> str | None:
    steps = state.get("remediation_steps")
    if isinstance(steps, list):
        joined = "\n".join(f"- {s}" for s in steps if s)
        return joined or None
    return str(steps) if steps else None


def save_incident_note_from_state(state: dict[str, Any]) -> bool:
    """Embed + persist a note for this completed investigation.

    Returns True if a note was written, False if skipped/failed. Never raises.
    """
    global _schema_ready
    try:
        cfg = load_config()
        logger.info(
            "[incident_memory] save hook invoked (enabled=%s, db_uri_set=%s)",
            cfg.enabled,
            bool(cfg.database_uri),
        )
        if not cfg.usable:
            logger.info(
                "[incident_memory] skip save: not usable (enabled=%s, db_uri_set=%s)",
                cfg.enabled,
                bool(cfg.database_uri),
            )
            return False

        validity = state.get("validity_score")
        category = state.get("root_cause_category")
        if validity is None or float(validity) < cfg.min_validity:
            logger.info(
                "[incident_memory] skip save: validity=%s < min=%s", validity, cfg.min_validity
            )
            return False
        if category in _SKIP_CATEGORIES:
            logger.info("[incident_memory] skip save: category=%s", category)
            return False

        symptom = _build_symptom(state)
        if not symptom:
            logger.info("[incident_memory] skip save: empty symptom text")
            return False

        from app.incident_memory import embeddings, store

        if not _schema_ready:
            store.ensure_schema(cfg)
            _schema_ready = True

        raw = state.get("raw_alert") if isinstance(state.get("raw_alert"), dict) else {}
        note = store.IncidentNote(
            symptom=symptom,
            root_cause=state.get("root_cause"),
            root_cause_category=category,
            remediation=_remediation_text(state),
            validity_score=float(validity),
            alert_name=state.get("alert_name"),
            alert_source=state.get("alert_source") or (raw or {}).get("alert_source"),
            service_name=state.get("pipeline_name"),
        )
        vector = embeddings.embed_text(symptom, cfg)
        store.insert_note(cfg, note, vector)
        logger.info(
            "[incident_memory] saved note: alert=%s category=%s validity=%.2f",
            note.alert_name,
            category,
            float(validity),
        )
        return True
    except Exception:
        logger.exception("[incident_memory] save failed (non-fatal)")
        return False
