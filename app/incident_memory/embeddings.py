"""Embedding client for incident memory (SRE-47).

Routes through the same OpenAI-compatible base URL OpenSRE already uses for
inference (``OPENAI_BASE_URL`` → the internal LiteLLM proxy), so embeddings reach
Azure ``text-embedding-3-large`` over the private network with no new auth path
or egress. The logical model name is ``sre-embed`` (see config).
"""

from __future__ import annotations

import os

from app.incident_memory.config import MemoryConfig


def embed_text(text: str, cfg: MemoryConfig) -> list[float]:
    """Return the embedding vector for ``text`` at ``cfg.embed_dim`` dimensions.

    Raises on transport/SDK errors — callers (save/recall) are responsible for
    swallowing failures so memory never breaks an investigation.
    """
    from openai import OpenAI  # lazy: keeps the module importable without the SDK

    client = OpenAI(
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        api_key=os.getenv("OPENAI_API_KEY", ""),
    )
    resp = client.embeddings.create(
        model=cfg.embed_model,
        input=text,
        dimensions=cfg.embed_dim,
    )
    return list(resp.data[0].embedding)
