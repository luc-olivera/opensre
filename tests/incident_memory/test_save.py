"""Unit tests for save_incident_note_from_state (SRE-47 Phase 2).

store/embeddings are monkeypatched — no DB, no OpenAI.
"""

import pytest

from app.incident_memory import config as cfg_mod
from app.incident_memory import embeddings, save, store


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
def captured(monkeypatch):
    """Patch config (usable), embeddings and store; capture inserts + schema calls."""
    rec = {"schema": 0, "inserted": [], "embedded": []}
    monkeypatch.setattr(save, "_schema_ready", False)
    monkeypatch.setattr(save, "load_config", lambda: _cfg())
    monkeypatch.setattr(store, "ensure_schema", lambda cfg: rec.__setitem__("schema", rec["schema"] + 1))
    monkeypatch.setattr(store, "insert_note", lambda cfg, note, vec: rec["inserted"].append((note, vec)))
    monkeypatch.setattr(embeddings, "embed_text", lambda text, cfg: rec["embedded"].append(text) or [0.1] * 4)
    return rec


def _good_state(**over):
    s = {
        "alert_name": "[OpenSRE] cat-backend latency high",
        "problem_md": "cat-backend p95 latency exceeded 0.5s for 5m",
        "root_cause": "cold start after scale-to-zero",
        "root_cause_category": "performance",
        "validity_score": 0.71,
        "remediation_steps": ["set min_replicas=1", "add a warmup probe"],
        "alert_source": "datadog",
        "pipeline_name": "cat-backend",
    }
    s.update(over)
    return s


def test_saves_good_investigation(captured):
    assert save.save_incident_note_from_state(_good_state()) is True
    assert captured["schema"] == 1
    assert len(captured["inserted"]) == 1
    note, vec = captured["inserted"][0]
    assert note.root_cause_category == "performance"
    assert note.service_name == "cat-backend"
    assert note.alert_source == "datadog"
    assert "set min_replicas=1" in note.remediation
    assert "cat-backend latency high" in note.symptom and "p95 latency" in note.symptom
    assert len(vec) == 4


def test_skips_when_not_usable(captured, monkeypatch):
    monkeypatch.setattr(save, "load_config", lambda: _cfg(enabled=False))
    assert save.save_incident_note_from_state(_good_state()) is False
    assert captured["inserted"] == []


def test_skips_low_validity(captured):
    assert save.save_incident_note_from_state(_good_state(validity_score=0.2)) is False
    assert captured["inserted"] == []


def test_skips_missing_validity(captured):
    assert save.save_incident_note_from_state(_good_state(validity_score=None)) is False
    assert captured["inserted"] == []


def test_skips_unknown_category(captured):
    assert save.save_incident_note_from_state(_good_state(root_cause_category="unknown")) is False
    assert captured["inserted"] == []


def test_skips_empty_symptom(captured):
    assert save.save_incident_note_from_state(
        _good_state(alert_name="", problem_md="", raw_alert={})
    ) is False
    assert captured["inserted"] == []


def test_schema_created_once_across_two_saves(captured):
    save.save_incident_note_from_state(_good_state())
    save.save_incident_note_from_state(_good_state())
    assert captured["schema"] == 1          # ensure_schema only on first
    assert len(captured["inserted"]) == 2


def test_never_raises_on_store_failure(captured, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "insert_note", boom)
    # Must swallow and return False, not propagate.
    assert save.save_incident_note_from_state(_good_state()) is False
