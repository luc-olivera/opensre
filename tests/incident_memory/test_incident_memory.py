"""Unit tests for the incident-memory store/embeddings (SRE-47).

No live Postgres or OpenAI: `_connect` is monkeypatched to a fake psycopg2
connection, and the embedding SDK is faked via sys.modules.
"""

import sys
import types

import pytest

from app.incident_memory import config as cfg_mod
from app.incident_memory import embeddings, store


def _cfg(**over):
    base = dict(
        enabled=True,
        database_uri="postgresql://u:p@h:5432/opensre",
        embed_model="sre-embed",
        embed_dim=1536,
        top_k=5,
        min_validity=0.4,
        connect_timeout=10,
    )
    base.update(over)
    return cfg_mod.MemoryConfig(**base)


# ── Fake psycopg2 connection ────────────────────────────────────────────────


class _FakeCursor:
    def __init__(self, rows=None, description=None):
        self.executed = []  # list of (sql, params)
        self._rows = rows or []
        self.description = description or []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


@pytest.fixture
def fake_conn(monkeypatch):
    cur = _FakeCursor()
    conn = _FakeConn(cur)
    monkeypatch.setattr(store, "_connect", lambda cfg: conn)
    return conn, cur


# ── config ──────────────────────────────────────────────────────────────────


def test_config_disabled_by_default(monkeypatch):
    for k in ("INCIDENT_MEMORY_ENABLED", "INCIDENT_MEMORY_DATABASE_URI"):
        monkeypatch.delenv(k, raising=False)
    c = cfg_mod.load_config()
    assert c.enabled is False and c.usable is False


def test_config_usable_when_enabled_with_uri(monkeypatch):
    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("INCIDENT_MEMORY_DATABASE_URI", "postgresql://u:p@h/opensre")
    c = cfg_mod.load_config()
    assert c.enabled is True and c.usable is True and c.embed_dim == 1536


def test_config_enabled_without_uri_is_not_usable(monkeypatch):
    monkeypatch.setenv("INCIDENT_MEMORY_ENABLED", "1")
    monkeypatch.delenv("INCIDENT_MEMORY_DATABASE_URI", raising=False)
    assert cfg_mod.load_config().usable is False


# ── vector literal ────────────────────────────────────────────────────────────


def test_vec_literal_format():
    assert store._vec_literal([0.1, 0.2]) == "[0.10000000,0.20000000]"


# ── ensure_schema / insert / search ───────────────────────────────────────────


def test_ensure_schema_runs_extension_table_index(fake_conn):
    _, cur = fake_conn
    store.ensure_schema(_cfg())
    sqls = " ".join(s for s, _ in cur.executed)
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sqls
    assert "VECTOR(1536)" in sqls
    assert "USING hnsw" in sqls and "vector_cosine_ops" in sqls


def test_ensure_schema_honors_dimension(fake_conn):
    _, cur = fake_conn
    store.ensure_schema(_cfg(embed_dim=3072))
    assert any("VECTOR(3072)" in s for s, _ in cur.executed)


def test_insert_note_binds_all_fields(fake_conn):
    _, cur = fake_conn
    note = store.IncidentNote(
        symptom="cat-backend latency high",
        root_cause="cold start",
        root_cause_category="performance",
        remediation="set min_replicas=1",
        validity_score=0.71,
        alert_name="[OpenSRE] cat-backend latency high",
        alert_source="datadog",
        service_name="cat-backend",
    )
    store.insert_note(_cfg(), note, [0.1, 0.2, 0.3])
    sql, params = cur.executed[-1]
    assert "INSERT INTO incident_notes" in sql
    assert params[3] == "cat-backend latency high"  # symptom
    assert params[8] == "sre-embed"                 # embedding_model
    assert params[9] == "[0.10000000,0.20000000,0.30000000]"  # vector literal


def test_search_similar_returns_dicts_with_similarity(fake_conn):
    conn, cur = fake_conn
    cur._rows = [("sym", "rc", "performance", "fix", 0.7, "2026-06-22", 0.93)]
    cur.description = [
        ("symptom",), ("root_cause",), ("root_cause_category",), ("remediation",),
        ("validity_score",), ("created_at",), ("similarity",),
    ]
    out = store.search_similar(_cfg(), [0.1, 0.2], k=3)
    assert out == [
        {
            "symptom": "sym", "root_cause": "rc", "root_cause_category": "performance",
            "remediation": "fix", "validity_score": 0.7, "created_at": "2026-06-22",
            "similarity": 0.93,
        }
    ]
    # k propagated as the LIMIT bind
    _, params = cur.executed[-1]
    assert params[-1] == 3


# ── embeddings ────────────────────────────────────────────────────────────────


def test_embed_text_requests_pinned_dimension(monkeypatch):
    calls = {}

    class _Emb:
        def create(self, *, model, input, dimensions):
            calls.update(model=model, input=input, dimensions=dimensions)
            return types.SimpleNamespace(data=[types.SimpleNamespace(embedding=[0.5] * dimensions)])

    class _Client:
        def __init__(self, *a, **k):
            self.embeddings = _Emb()

    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = _Client
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    vec = embeddings.embed_text("some symptom", _cfg(embed_dim=1536))
    assert calls == {"model": "sre-embed", "input": "some symptom", "dimensions": 1536}
    assert len(vec) == 1536
