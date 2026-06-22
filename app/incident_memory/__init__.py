"""Cross-investigation incident memory (SRE-47, CloudNation fork).

An additive package — not part of upstream OpenSRE. It gives the agent an
Azure-SRE-Agent-style memory: a structured note is written after each
investigation and semantically-similar past notes are recalled on future ones,
backed by pgvector on the existing ``opensre`` Postgres.

Surfaces (wired across phases):
- ``store`` / ``embeddings`` / ``config`` — the pgvector DAO + embedding client (Phase 1).
- ``save.save_incident_note_from_state`` — deterministic post-investigation write,
  called from ``app/delivery/publish_findings/node.py`` (Phase 2).
- ``tools.recall`` — the ``recall_similar_incidents`` tool, registered for the
  agent loop via ``register()`` (Phase 3).

Everything degrades safely: if memory is disabled or its backing services are
unreachable, callers must swallow errors so an investigation never breaks.
"""

from __future__ import annotations

import logging

from app.incident_memory.save import save_incident_note_from_state

logger = logging.getLogger(__name__)

__all__ = ["register", "save_incident_note_from_state"]

_registered = False


def register() -> None:
    """Register the recall tool package with OpenSRE's tool registry.

    Idempotent. Called once at process start (from ``app/remote/server.py``).
    Safe to call even if the tools subpackage is absent during early phases.
    """
    global _registered
    if _registered:
        return
    try:
        from app.tools.registry import register_external_tool_package

        from app.incident_memory import tools as _tools_pkg

        register_external_tool_package(_tools_pkg)
        _registered = True
    except Exception:  # never let registration break server startup
        logger.exception("[incident_memory] tool registration failed; recall disabled")
