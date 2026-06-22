"""Configuration for the incident-memory store (SRE-47)."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Logical model name routed by LiteLLM to the Azure text-embedding-3-large
# deployment (see client-app/litellm/config.yaml). Embeddings stay in the EU
# data zone (DataZoneStandard), same posture as the chat deployments.
DEFAULT_EMBED_MODEL = "sre-embed"
# Pinned dimension: write and read MUST agree. text-embedding-3-large native is
# 3072; we request 1536 (the `dimensions` param) — cheaper/lighter for HNSW on a
# B1ms instance. The embedding_model column guards against mixing vector spaces.
DEFAULT_EMBED_DIM = 1536
DEFAULT_TOP_K = 5
# Don't memorize low-confidence or degraded investigations — keeps the corpus clean.
DEFAULT_MIN_VALIDITY = 0.4
DEFAULT_CONNECT_TIMEOUT = 10

TABLE = "incident_notes"

_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool
    database_uri: str
    embed_model: str
    embed_dim: int
    top_k: int
    min_validity: float
    connect_timeout: int

    @property
    def usable(self) -> bool:
        """True only when the feature is on AND a DB target is configured."""
        return self.enabled and bool(self.database_uri)


def load_config() -> MemoryConfig:
    """Build config from environment (all optional; defaults keep it disabled)."""
    return MemoryConfig(
        enabled=os.getenv("INCIDENT_MEMORY_ENABLED", "false").strip().lower() in _TRUTHY,
        database_uri=os.getenv("INCIDENT_MEMORY_DATABASE_URI", "").strip(),
        embed_model=os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL).strip() or DEFAULT_EMBED_MODEL,
        embed_dim=int(os.getenv("INCIDENT_MEMORY_EMBED_DIM", str(DEFAULT_EMBED_DIM))),
        top_k=int(os.getenv("INCIDENT_MEMORY_TOP_K", str(DEFAULT_TOP_K))),
        min_validity=float(os.getenv("INCIDENT_MEMORY_MIN_VALIDITY", str(DEFAULT_MIN_VALIDITY))),
        connect_timeout=int(os.getenv("INCIDENT_MEMORY_CONNECT_TIMEOUT", str(DEFAULT_CONNECT_TIMEOUT))),
    )
