"""Unit tests for the recall tool + seed builder (SRE-47 Phase 3).

Fully mocked — no DB, no embedding SDK, no LLM client. ``store`` / ``embeddings``
are monkeypatched; the seed builder's lazy ``app.services.*`` imports are faked
via ``sys.modules`` so the suite runs without the production-only ``keyring`` /
LLM dependency chain.
"""

import sys
import types

import pytest

from app.incident_memory import config as cfg_mod
from app.incident_memory import embeddings, store
from app.incident_memory.tools import recall


def _cfg(**over):
    base = dict(
        enabled=True,
        database_uri="postgresql://u:p@h/opensre",
        embed_model="sre-embed",
        embed_dim=1536,
        top_k=5,
        min_validity=0.4,
        connect_timeout=10,
    )
    base.update(over)
    return cfg_mod.MemoryConfig(**base)


@pytest.fixture
def store_stub(monkeypatch):
    """Patch load_config (usable), embeddings and store; record calls."""
    rec = {"schema": 0, "embedded": [], "searched": [], "rows": []}
    monkeypatch.setattr(recall, "load_config", lambda: _cfg())
    monkeypatch.setattr(store, "ensure_schema", lambda cfg: rec.__setitem__("schema", rec["schema"] + 1))
    monkeypatch.setattr(embeddings, "embed_text", lambda text, cfg: rec["embedded"].append(text) or [0.1, 0.2])
    monkeypatch.setattr(
        store, "search_similar", lambda cfg, vec, k=None: rec["searched"].append((vec, k)) or rec["rows"]
    )
    return rec


# ── recall_similar_incidents: guard paths ────────────────────────────────────


def test_recall_disabled_returns_unavailable(monkeypatch):
    monkeypatch.setattr(recall, "load_config", lambda: _cfg(enabled=False))
    out = recall.recall_similar_incidents(symptom_text="x")
    assert out["available"] is False
    assert out["prior_incidents"] == []
    assert "disabled" in out["message"]


def test_recall_empty_symptom_returns_unavailable(store_stub):
    out = recall.recall_similar_incidents(symptom_text="   ")
    assert out["available"] is False
    assert "no symptom text" in out["message"]
    # never touches the store when there's nothing to match on
    assert store_stub["embedded"] == [] and store_stub["searched"] == []


def test_recall_store_failure_is_non_fatal(monkeypatch, store_stub):
    def _boom(text, cfg):
        raise RuntimeError("embed down")

    monkeypatch.setattr(embeddings, "embed_text", _boom)
    out = recall.recall_similar_incidents(symptom_text="latency high")
    assert out["available"] is False
    assert out["error"] == "embed down"


# ── recall_similar_incidents: happy path ─────────────────────────────────────


def test_recall_happy_path_embeds_searches_and_formats(store_stub):
    store_stub["rows"] = [
        {
            "alert_name": "[OpenSRE] cat-backend latency high",
            "symptom": "cat-backend latency high\n\nlatency p99 spiking",
            "root_cause": "cold start after scale-to-zero",
            "root_cause_category": "performance",
            "remediation": "set min_replicas=1",
            "validity_score": 0.71,
            "created_at": "2026-06-20T10:00:00+00:00",
            "similarity": 0.912345,
        }
    ]
    out = recall.recall_similar_incidents(symptom_text="cat-backend latency high", top_k=3)

    assert out["available"] is True
    assert out["count"] == 1
    assert "prior hypotheses" in out["guidance"]
    # embedded the provided symptom; searched with the returned vector + top_k
    assert store_stub["embedded"] == ["cat-backend latency high"]
    assert store_stub["searched"] == [([0.1, 0.2], 3)]
    assert store_stub["schema"] == 1  # ensure_schema ran (fresh-DB safety)

    note = out["prior_incidents"][0]
    assert note["similarity"] == 0.912  # rounded to 3dp
    assert note["alert_name"] == "[OpenSRE] cat-backend latency high"
    assert note["root_cause_category"] == "performance"
    assert note["prior_validity_score"] == 0.71


def test_recall_top_k_defaults_to_none_when_omitted(store_stub):
    store_stub["rows"] = []
    out = recall.recall_similar_incidents(symptom_text="something")
    assert out["available"] is True and out["count"] == 0
    assert store_stub["searched"] == [([0.1, 0.2], None)]


# ── _format_note ─────────────────────────────────────────────────────────────


def test_format_note_truncates_long_symptom():
    long_symptom = "x" * (recall._SYMPTOM_PREVIEW_CHARS + 50)
    note = recall._format_note({"symptom": long_symptom, "similarity": 0.5})
    assert note["past_symptom"].endswith("…")
    assert len(note["past_symptom"]) == recall._SYMPTOM_PREVIEW_CHARS + 1  # preview + ellipsis


def test_format_note_handles_datetime_and_none():
    class _DT:
        def isoformat(self):
            return "2026-06-22T00:00:00"

    assert recall._format_note({"created_at": _DT(), "similarity": None})["observed_at"] == (
        "2026-06-22T00:00:00"
    )
    # None similarity → None, not a crash
    assert recall._format_note({"created_at": None})["observed_at"] is None
    assert recall._format_note({"similarity": None})["similarity"] is None


# ── _recall_is_available ─────────────────────────────────────────────────────


def test_is_available_tracks_config_usable(monkeypatch):
    monkeypatch.setattr(recall, "load_config", lambda: _cfg(enabled=True))
    assert recall._recall_is_available({}) is True
    monkeypatch.setattr(recall, "load_config", lambda: _cfg(enabled=False))
    assert recall._recall_is_available({}) is False


def test_is_available_swallows_config_errors(monkeypatch):
    def _boom():
        raise RuntimeError("env broken")

    monkeypatch.setattr(recall, "load_config", _boom)
    assert recall._recall_is_available({}) is False


# ── build_recall_seed_call ───────────────────────────────────────────────────


class _FakeBedrockClient:
    pass


class _FakeOtherClient:
    pass


class _FakeToolCall:
    def __init__(self, id, name, input):
        self.id = id
        self.name = name
        self.input = input


@pytest.fixture
def fake_llm_services(monkeypatch):
    """Fake the lazy app.services imports the seed builder reaches for."""
    client_mod = types.ModuleType("app.services.agent_llm_client")
    client_mod.BedrockConverseAgentClient = _FakeBedrockClient
    client_mod.ToolCall = _FakeToolCall
    bedrock_mod = types.ModuleType("app.services.bedrock_converse")
    bedrock_mod.new_tool_use_id = lambda: "bedrock-generated-id"
    monkeypatch.setitem(sys.modules, "app.services.agent_llm_client", client_mod)
    monkeypatch.setitem(sys.modules, "app.services.bedrock_converse", bedrock_mod)


class _ToolStub:
    def __init__(self, name):
        self.name = name


def test_seed_call_none_when_disabled(monkeypatch, fake_llm_services):
    monkeypatch.setattr(recall, "load_config", lambda: _cfg(enabled=False))
    assert recall.build_recall_seed_call({}, [_ToolStub(recall.RECALL_TOOL_NAME)], _FakeOtherClient()) is None


def test_seed_call_none_when_tool_absent(monkeypatch, fake_llm_services):
    monkeypatch.setattr(recall, "load_config", lambda: _cfg())
    monkeypatch.setattr(recall, "_build_symptom", lambda state: "latency high")
    # tool list lacks recall → no seed
    assert recall.build_recall_seed_call({}, [_ToolStub("query_datadog_logs")], _FakeOtherClient()) is None


def test_seed_call_none_when_no_symptom(monkeypatch, fake_llm_services):
    monkeypatch.setattr(recall, "load_config", lambda: _cfg())
    monkeypatch.setattr(recall, "_build_symptom", lambda state: "")
    assert recall.build_recall_seed_call({}, [_ToolStub(recall.RECALL_TOOL_NAME)], _FakeOtherClient()) is None


def test_seed_call_built_with_symptom_input(monkeypatch, fake_llm_services):
    monkeypatch.setattr(recall, "load_config", lambda: _cfg())
    monkeypatch.setattr(recall, "_build_symptom", lambda state: "cat-backend latency high")
    tc = recall.build_recall_seed_call(
        {"alert_name": "x"}, [_ToolStub(recall.RECALL_TOOL_NAME)], _FakeOtherClient()
    )
    assert tc is not None
    assert tc.name == recall.RECALL_TOOL_NAME
    assert tc.input == {"symptom_text": "cat-backend latency high"}
    assert tc.id == f"seed_{recall.RECALL_TOOL_NAME}"  # deterministic id for non-Bedrock client


def test_seed_call_uses_bedrock_id_for_bedrock_client(monkeypatch, fake_llm_services):
    monkeypatch.setattr(recall, "load_config", lambda: _cfg())
    monkeypatch.setattr(recall, "_build_symptom", lambda state: "latency high")
    tc = recall.build_recall_seed_call(
        {}, [_ToolStub(recall.RECALL_TOOL_NAME)], _FakeBedrockClient()
    )
    assert tc.id == "bedrock-generated-id"
