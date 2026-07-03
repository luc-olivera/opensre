"""Unit tests for the ProposedRemediation schema and related helpers in app.agent.result.

Run with:
    PYTHONPATH=. /Users/lucas.zago/mamba/envs/cn-ai/bin/python3 -m pytest \
        tests/agent/test_proposed_remediation_schema.py -q --noconftest
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Bootstrap: load app.agent.result directly, bypassing the heavy app.agent
# __init__.py import chain (which pulls in keyring, coralogix, etc.).
# ---------------------------------------------------------------------------
import importlib.util
import sys
import types

_BASE = "/Users/lucas.zago/CloudNation/opensre"


def _load(mod_name: str, rel_path: str) -> types.ModuleType:
    if mod_name in sys.modules:
        return sys.modules[mod_name]
    spec = importlib.util.spec_from_file_location(mod_name, f"{_BASE}/{rel_path}")
    m = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[mod_name] = m
    spec.loader.exec_module(m)  # type: ignore[union-attr]
    return m


def _bootstrap_result_module() -> None:
    """Register minimal stubs so app.agent.result can be imported in isolation."""
    if "app.agent.result" in sys.modules:
        return

    # Stub top-level app and app.agent to prevent __init__.py cascade.
    for mod_name in ("app", "app.agent"):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    # Load the real taxonomy (no heavy deps).
    if "app.types" not in sys.modules:
        sys.modules["app.types"] = types.ModuleType("app.types")
    _load(
        "app.types.root_cause_categories",
        "app/types/root_cause_categories.py",
    )

    # Load the real result module.
    _load("app.agent.result", "app/agent/result.py")


_bootstrap_result_module()

# ---------------------------------------------------------------------------
# Now safe to import from app.agent.result
# ---------------------------------------------------------------------------

import pydantic
import pytest

from app.agent.result import (
    InvestigationResult,
    ProposedRemediation,
    RemediationActionType,
    _build_diagnosis_schema,
)


# ---------------------------------------------------------------------------
# ProposedRemediation defaults
# ---------------------------------------------------------------------------


def test_proposed_remediation_default_action_type_is_none() -> None:
    p = ProposedRemediation()
    assert p.action_type == RemediationActionType.none


def test_proposed_remediation_default_target_is_empty_string() -> None:
    p = ProposedRemediation()
    assert p.target == ""


def test_proposed_remediation_default_parameters_is_empty_dict() -> None:
    p = ProposedRemediation()
    assert p.parameters == {}


def test_proposed_remediation_default_exact_command_is_empty_string() -> None:
    p = ProposedRemediation()
    assert p.exact_command == ""


def test_proposed_remediation_default_risk_is_low() -> None:
    p = ProposedRemediation()
    assert p.risk == "low"


def test_proposed_remediation_default_rationale_is_empty_string() -> None:
    p = ProposedRemediation()
    assert p.rationale == ""


def test_proposed_remediation_default_confidence_is_zero() -> None:
    p = ProposedRemediation()
    assert p.confidence == 0.0


# ---------------------------------------------------------------------------
# Backward-compat: model_validate({}) gives same defaults
# ---------------------------------------------------------------------------


def test_proposed_remediation_model_validate_empty_dict_action_none() -> None:
    p = ProposedRemediation.model_validate({})
    assert p.action_type == RemediationActionType.none


def test_proposed_remediation_model_validate_empty_dict_full_defaults() -> None:
    p = ProposedRemediation.model_validate({})
    assert p.target == ""
    assert p.parameters == {}
    assert p.exact_command == ""
    assert p.risk == "low"
    assert p.rationale == ""
    assert p.confidence == 0.0


# ---------------------------------------------------------------------------
# Round-trip: full valid dict
# ---------------------------------------------------------------------------


def test_proposed_remediation_round_trip_serializes_action_type_as_string() -> None:
    """model_dump(mode='json') must serialize the str Enum to a plain string."""
    data = {
        "action_type": "grant_acr_pull",
        "target": "myregistry.azurecr.io",
        "parameters": {"role": "AcrPull"},
        "exact_command": "az role assignment create --role AcrPull --assignee sp-id --scope /sub/...",
        "risk": "high",
        "rationale": "Service principal lacks AcrPull on the registry.",
        "confidence": 0.92,
    }
    p = ProposedRemediation.model_validate(data)
    dumped = p.model_dump(mode="json")

    assert dumped["action_type"] == "grant_acr_pull"
    assert isinstance(dumped["action_type"], str)
    assert dumped["target"] == "myregistry.azurecr.io"
    assert dumped["risk"] == "high"
    assert dumped["confidence"] == pytest.approx(0.92)


def test_proposed_remediation_round_trip_all_automatable_action_types() -> None:
    """Every non-none, non-manual action type must round-trip without error."""
    automatable = [
        RemediationActionType.rollback_revision,
        RemediationActionType.restart_revision,
        RemediationActionType.grant_acr_pull,
        RemediationActionType.remove_env_var,
        RemediationActionType.scale_revision,
    ]
    for action in automatable:
        p = ProposedRemediation(action_type=action)
        dumped = p.model_dump(mode="json")
        assert dumped["action_type"] == action.value


# ---------------------------------------------------------------------------
# Validation: invalid action_type raises pydantic.ValidationError
# ---------------------------------------------------------------------------


def test_proposed_remediation_invalid_action_type_raises_validation_error() -> None:
    with pytest.raises(pydantic.ValidationError):
        ProposedRemediation.model_validate({"action_type": "delete_everything"})


def test_proposed_remediation_invalid_action_type_message_mentions_input() -> None:
    with pytest.raises(pydantic.ValidationError) as exc_info:
        ProposedRemediation.model_validate({"action_type": "nuke_cluster"})
    assert "nuke_cluster" in str(exc_info.value) or "action_type" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _build_diagnosis_schema: proposed_remediation defaults to none
# ---------------------------------------------------------------------------


def test_build_diagnosis_schema_proposed_remediation_default_action_none() -> None:
    DiagnosisSchema = _build_diagnosis_schema(set())
    # Minimal valid instance: only required fields
    instance = DiagnosisSchema(root_cause="DB OOM", root_cause_category="unknown")
    assert instance.proposed_remediation.action_type == RemediationActionType.none


def test_build_diagnosis_schema_proposed_remediation_is_proposed_remediation_instance() -> None:
    DiagnosisSchema = _build_diagnosis_schema(set())
    instance = DiagnosisSchema(root_cause="x", root_cause_category="unknown")
    assert isinstance(instance.proposed_remediation, ProposedRemediation)


def test_build_diagnosis_schema_with_categories_includes_them_in_description() -> None:
    DiagnosisSchema = _build_diagnosis_schema({"connection_exhaustion", "oom_kill"})
    description = str(DiagnosisSchema.model_fields["root_cause_category"].description)
    assert "connection_exhaustion" in description or "oom_kill" in description


# ---------------------------------------------------------------------------
# InvestigationResult: proposed_remediation defaults to empty dict
# ---------------------------------------------------------------------------


def test_investigation_result_proposed_remediation_default_is_empty_dict() -> None:
    ir = InvestigationResult(root_cause="CPU spike", root_cause_category="resource_exhaustion")
    assert ir.proposed_remediation == {}


def test_investigation_result_proposed_remediation_can_be_set() -> None:
    proposal = {
        "action_type": "restart_revision",
        "target": "app--revision-1",
        "parameters": {},
        "exact_command": "az containerapp revision restart ...",
        "risk": "low",
        "rationale": "Revision OOMKilled; restart clears state.",
        "confidence": 0.85,
    }
    ir = InvestigationResult(
        root_cause="OOM",
        root_cause_category="oom_kill",
        proposed_remediation=proposal,
    )
    assert ir.proposed_remediation["action_type"] == "restart_revision"
