"""``recall_similar_incidents`` tool — cross-investigation memory recall (SRE-47 Phase 3).

The tool embeds the current alert's symptoms, queries the pgvector store for the
most semantically-similar past incidents, and returns them as **prior
hypotheses** — explicitly framed as leads to verify against live evidence, never
as established facts. This anti-anchoring framing is the whole point: a stale or
coincidental match must not short-circuit a fresh diagnosis.

Two entry points, one body:
- ``build_recall_seed_call`` — builds a deterministic pre-loop seed call (run by
  ``app/agent/investigation.py`` before the LLM loop, so a recall result always
  enters the evidence trace regardless of what the model would have chosen).
- ``recall_similar_incidents`` — the ``@tool`` the model may also call itself
  mid-investigation, supplying the symptom text it wants to match on.

Degrades safely: if memory is disabled or the store is unreachable, the tool
returns an ``available: False`` payload instead of raising, so an investigation
never breaks on a memory failure.
"""

from __future__ import annotations

import logging
from typing import Any

from app.incident_memory.config import load_config
from app.incident_memory.save import _build_symptom
from app.tools.tool_decorator import tool

logger = logging.getLogger(__name__)

RECALL_TOOL_NAME = "recall_similar_incidents"

# How much of a past symptom to surface back to the model — enough to recognise
# the incident, short enough to keep the seeded tool result cheap in tokens.
_SYMPTOM_PREVIEW_CHARS = 400


def _recall_is_available(_sources: dict[str, dict]) -> bool:
    """Offer the tool only when incident memory is enabled and a DB is configured.

    Reads env-backed config (cheap). When memory is off the tool is hidden from
    the planner and never seeded, matching the safe-degrade contract.
    """
    try:
        return load_config().usable
    except Exception:  # never let availability checks break tool filtering
        return False


def _format_note(row: dict[str, Any]) -> dict[str, Any]:
    """Render one store row as a prior-hypothesis dict for the model."""
    sim = row.get("similarity")
    created = row.get("created_at")
    symptom = row.get("symptom") or ""
    if len(symptom) > _SYMPTOM_PREVIEW_CHARS:
        symptom = symptom[:_SYMPTOM_PREVIEW_CHARS] + "…"
    return {
        "similarity": round(float(sim), 3) if sim is not None else None,
        "alert_name": row.get("alert_name"),
        "past_symptom": symptom,
        "root_cause": row.get("root_cause"),
        "root_cause_category": row.get("root_cause_category"),
        "remediation": row.get("remediation"),
        "prior_validity_score": row.get("validity_score"),
        "observed_at": created.isoformat() if hasattr(created, "isoformat") else created,
    }


def _empty(message: str, **extra: Any) -> dict[str, Any]:
    return {"source": "incident_memory", "available": False, "prior_incidents": [], "message": message, **extra}


@tool(
    name=RECALL_TOOL_NAME,
    display_name="Similar past incidents",
    source="knowledge",
    description=(
        "Recall past investigations whose symptoms are semantically similar to the "
        "current alert. Returns prior root causes and remediations as HYPOTHESES to "
        "verify against live evidence — not established facts. Useful first step to "
        "check whether this incident has been seen before."
    ),
    use_cases=[
        "Checking whether a similar alert was investigated before",
        "Retrieving the root cause and remediation of past look-alike incidents",
        "Forming initial hypotheses to confirm or rule out with live tools",
    ],
    examples=[
        "Match the current latency alert against past latency incidents on the same service.",
    ],
    anti_examples=[
        "Do not report a recalled root cause as the current root cause without confirming it against fresh evidence.",
    ],
    tags=("safe", "fast", "no-credentials"),
    cost_tier="cheap",
    side_effect_level="read_only",
    evidence_type="other",
    surfaces=("investigation",),
    input_schema={
        "type": "object",
        "properties": {
            "symptom_text": {
                "type": "string",
                "description": (
                    "The current alert's symptoms to match on — alert name plus the "
                    "problem description or error text."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of past incidents to return (defaults to the configured top_k).",
            },
        },
        "required": ["symptom_text"],
    },
    is_available=_recall_is_available,
)
def recall_similar_incidents(
    symptom_text: str = "",
    top_k: int | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Return up to ``top_k`` past incidents similar to ``symptom_text``."""
    cfg = load_config()
    if not cfg.usable:
        return _empty("incident memory disabled")

    text = (symptom_text or "").strip()
    if not text:
        return _empty("no symptom text provided to match on")

    try:
        from app.incident_memory import embeddings, store

        # Idempotent; also handles the very first recall on a fresh DB (no rows
        # yet) by ensuring the table exists so the search returns [] cleanly.
        store.ensure_schema(cfg)
        vector = embeddings.embed_text(text, cfg)
        rows = store.search_similar(cfg, vector, top_k)
    except Exception as exc:  # never break an investigation on a memory failure
        logger.warning("[incident_memory] recall failed (non-fatal): %s", exc)
        return _empty("recall unavailable", error=str(exc))

    notes = [_format_note(r) for r in rows]
    logger.warning(
        "[incident_memory] recall: %d prior incident(s) for symptom len=%d",
        len(notes),
        len(text),
    )
    return {
        "source": "incident_memory",
        "available": True,
        "count": len(notes),
        "prior_incidents": notes,
        "guidance": (
            "These are PAST incidents with similar symptoms, retrieved from memory. "
            "Treat their root causes and remediations as prior hypotheses to verify "
            "against the current evidence — they may be stale, partial, or unrelated. "
            "Do not conclude a root cause solely because it matches a past incident."
        ),
    }


def build_recall_seed_call(state: dict[str, Any], tools: list[Any], llm: Any) -> Any | None:
    """Build a deterministic pre-loop seed call for recall, or ``None`` to skip.

    Returns ``None`` when memory is disabled, the recall tool is not in the
    available set, or the alert carries no usable symptom text. Mirrors the id
    scheme of ``_build_seed_calls`` so synthetic-assistant-turn construction is
    consistent across LLM backends.
    """
    cfg = load_config()
    if not cfg.usable:
        return None
    if not any(getattr(t, "name", None) == RECALL_TOOL_NAME for t in tools):
        return None

    symptom = _build_symptom(state)
    if not symptom:
        return None

    from app.services.agent_llm_client import BedrockConverseAgentClient, ToolCall
    from app.services.bedrock_converse import new_tool_use_id

    tool_id = new_tool_use_id() if isinstance(llm, BedrockConverseAgentClient) else f"seed_{RECALL_TOOL_NAME}"
    return ToolCall(id=tool_id, name=RECALL_TOOL_NAME, input={"symptom_text": symptom})


__all__ = ["recall_similar_incidents", "build_recall_seed_call", "RECALL_TOOL_NAME"]
