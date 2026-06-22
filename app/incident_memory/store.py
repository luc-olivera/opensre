"""pgvector-backed incident-note store (SRE-47).

Mirrors the psycopg2 usage in ``app/integrations/postgresql.py`` but connects
from a single libpq URI (``INCIDENT_MEMORY_DATABASE_URI``) — psycopg2 parses the
URI itself, so we never hand-parse credentials. One short-lived connection per
call (write frequency is one row per investigation; recall is one query).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.incident_memory.config import TABLE, MemoryConfig

logger = logging.getLogger(__name__)


@dataclass
class IncidentNote:
    symptom: str  # the embedded text: alert identity + symptoms
    root_cause: str | None = None
    root_cause_category: str | None = None
    remediation: str | None = None
    validity_score: float | None = None
    alert_name: str | None = None
    alert_source: str | None = None
    service_name: str | None = None


def _connect(cfg: MemoryConfig) -> Any:
    """Open a psycopg2 connection from the libpq URI. Caller must close."""
    import psycopg2  # lazy, matching app/integrations/postgresql.py

    return psycopg2.connect(
        cfg.database_uri,
        connect_timeout=cfg.connect_timeout,
        options=f"-c statement_timeout={cfg.connect_timeout * 1000}ms",
        application_name="opensre-incident-memory",
    )


def _vec_literal(embedding: list[float]) -> str:
    """Render a float list as a pgvector text literal: ``[1,2,3]``."""
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


def ensure_schema(cfg: MemoryConfig) -> None:
    """Create the extension, table and HNSW index if absent. Idempotent."""
    ddl_extension = "CREATE EXTENSION IF NOT EXISTS vector;"
    ddl_table = f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id                  BIGSERIAL PRIMARY KEY,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            alert_name          TEXT,
            alert_source        TEXT,
            service_name        TEXT,
            symptom             TEXT NOT NULL,
            root_cause          TEXT,
            root_cause_category TEXT,
            remediation         TEXT,
            validity_score      REAL,
            embedding_model     TEXT NOT NULL,
            embedding           VECTOR({cfg.embed_dim}) NOT NULL
        );
    """
    # HNSW: no lists tuning, good recall at small row counts (ivfflat degenerates
    # when rows are few). Cosine distance to match OpenAI embeddings.
    ddl_index = (
        f"CREATE INDEX IF NOT EXISTS {TABLE}_embedding_hnsw "
        f"ON {TABLE} USING hnsw (embedding vector_cosine_ops);"
    )
    conn = _connect(cfg)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(ddl_extension)
            cur.execute(ddl_table)
            cur.execute(ddl_index)
    finally:
        conn.close()


def insert_note(cfg: MemoryConfig, note: IncidentNote, embedding: list[float]) -> None:
    """Persist one incident note + its embedding."""
    sql = f"""
        INSERT INTO {TABLE}
            (alert_name, alert_source, service_name, symptom, root_cause,
             root_cause_category, remediation, validity_score, embedding_model, embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector);
    """
    conn = _connect(cfg)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    note.alert_name,
                    note.alert_source,
                    note.service_name,
                    note.symptom,
                    note.root_cause,
                    note.root_cause_category,
                    note.remediation,
                    note.validity_score,
                    cfg.embed_model,
                    _vec_literal(embedding),
                ),
            )
    finally:
        conn.close()


def search_similar(
    cfg: MemoryConfig, embedding: list[float], k: int | None = None
) -> list[dict[str, Any]]:
    """Return up to ``k`` most-similar past notes (cosine), same embedding model only."""
    limit = k if k is not None else cfg.top_k
    sql = f"""
        SELECT symptom, root_cause, root_cause_category, remediation,
               validity_score, created_at,
               1 - (embedding <=> %s::vector) AS similarity
        FROM {TABLE}
        WHERE embedding_model = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    vec = _vec_literal(embedding)
    conn = _connect(cfg)
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, (vec, cfg.embed_model, vec, limit))
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in rows]
    finally:
        conn.close()
