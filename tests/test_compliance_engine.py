"""Module 04 acceptance tests (deterministic path; LLM mocked)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from netguard.compliance_engine import assert_preconditions, evaluate_compliance
from netguard.contract_ingest import validate_contract
from netguard.contract_schema import Contract
from netguard.entities import UnknownCounterparty, resolve_counterparty
from netguard.placement_llm import PlacementLLMOutput, interpret_placement_llm
from netguard.schema import DocumentBlock
from netguard.verdict_cache import VerdictCache
from netguard.vocabulary import CheckName, CheckResult, Verdict

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "compliance"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _contract(name: str) -> Contract:
    # Skip formulary-id existence checks — fixture IDs are not in output/.
    return validate_contract(_load(name), known_formulary_ids=None)


def test_canonical_gpo_pbm_same_entity():
    assert resolve_counterparty("Ascent") == resolve_counterparty("Express Scripts") == "esi"
    assert resolve_counterparty("Zinc") == resolve_counterparty("CVS Caremark") == "cvs_zinc"


def test_unknown_counterparty_loud():
    with pytest.raises(UnknownCounterparty):
        resolve_counterparty("Totally Unknown GPO XYZ")


def test_gpo_pbm_precondition_passes():
    contract = _contract("contract_clean.json")
    formulary = _load("formulary_clean.json")
    doc = DocumentBlock.model_validate(formulary["document"])
    gate = assert_preconditions(contract, doc, "FIXTURE-ESI-CLEAN")
    assert gate.passed is True
    assert gate.contract_canonical_id == "esi"
    assert gate.formulary_canonical_id == "esi"


def test_clean_pass_compliant():
    result = evaluate_compliance(
        _contract("contract_clean.json"),
        _load("formulary_clean.json"),
        claimed_rate_by_product={"SYNTHROID": 32.5},
        formulary_id_override="FIXTURE-ESI-CLEAN",
    )
    assert result.scope_gate.passed
    assert len(result.product_results) == 1
    pr = result.product_results[0]
    assert pr.verdict == Verdict.compliant
    assert pr.observed.coverage_status.value == "covered"
    assert pr.observed.interpreted_position.value == "non_preferred"
    assert all(
        c.result == CheckResult.pass_
        for te in pr.term_evaluations
        for c in te.checks
        if c.result != CheckResult.not_evaluated
    )


def test_designed_st_discrepancy():
    result = evaluate_compliance(
        _contract("contract_st_fail.json"),
        _load("formulary_st.json"),
        claimed_rate_by_product={"SYNTHROID": 32.5},
        formulary_id_override="FIXTURE-ESI-ST",
    )
    assert result.scope_gate.passed
    pr = result.product_results[0]
    assert pr.verdict == Verdict.non_compliant
    st_checks = [
        c
        for te in pr.term_evaluations
        for c in te.checks
        if c.check == CheckName.step_therapy
    ]
    assert st_checks
    assert st_checks[0].result == CheckResult.fail
    assert "ST" in st_checks[0].observed
    assert pr.matched_formulary_line.page_ref == 1
    assert pr.matched_formulary_line.raw_row_text


def test_wrong_period_indeterminate():
    result = evaluate_compliance(
        _contract("contract_clean.json"),
        _load("formulary_wrong_period.json"),
        claimed_rate_by_product={"SYNTHROID": 32.5},
        formulary_id_override="FIXTURE-ESI-OLD",
    )
    assert result.scope_gate.passed is False
    assert result.scope_gate.reason == "effective_window_mismatch"
    assert result.product_results[0].verdict == Verdict.indeterminate


def test_unknown_counterparty_gate():
    result = evaluate_compliance(
        _contract("contract_unknown_counterparty.json"),
        _load("formulary_clean.json"),
        claimed_rate_by_product={"SYNTHROID": 32.5},
        formulary_id_override="FIXTURE-ESI-CLEAN",
    )
    assert result.scope_gate.passed is False
    assert result.scope_gate.reason == "unknown_counterparty"
    assert result.product_results[0].verdict == Verdict.indeterminate


def test_absent_product_not_found():
    result = evaluate_compliance(
        _contract("contract_clean.json"),
        _load("formulary_absent.json"),
        claimed_rate_by_product={"SYNTHROID": 32.5},
        formulary_id_override="FIXTURE-ESI-ABSENT",
    )
    assert result.scope_gate.passed
    pr = result.product_results[0]
    assert pr.observed.coverage_status.value == "not_found"
    assert pr.verdict == Verdict.non_compliant
    cov = [c for te in pr.term_evaluations for c in te.checks if c.check == CheckName.coverage]
    assert cov[0].result == CheckResult.fail


def test_consensus_agree_and_disagree(tmp_path):
    llm = MagicMock()
    agree = PlacementLLMOutput(
        coverage_status="covered",
        um_present=[],
        interpreted_position="non_preferred",
        confidence=0.8,
        reasoning="tier 3",
    )
    llm.parse.side_effect = [agree, agree]
    out = interpret_placement_llm(
        llm,
        drug_name="SYNTHROID",
        tier=3,
        coverage_status="covered",
        um_flags=[],
        raw_row_text="SYNTHROID 3",
        legend={},
        contract_position="non_preferred",
        model_name="mock",
        cache=VerdictCache(tmp_path / "cache.json"),
    )
    assert out["consensus"] == "agreed"
    assert out["interpreted_position"] == "non_preferred"
    assert llm.parse.call_count == 2

    # Cache hit — no re-inference
    llm.parse.reset_mock()
    out2 = interpret_placement_llm(
        llm,
        drug_name="SYNTHROID",
        tier=3,
        coverage_status="covered",
        um_flags=[],
        raw_row_text="SYNTHROID 3",
        legend={},
        contract_position="non_preferred",
        model_name="mock",
        cache=VerdictCache(tmp_path / "cache.json"),
    )
    assert out2["source"] == "cache"
    assert llm.parse.call_count == 0

    # Disagreement → ambiguous, both readings persisted, no third call
    a = PlacementLLMOutput(
        coverage_status="covered",
        um_present=[],
        interpreted_position="preferred",
        confidence=0.7,
        reasoning="could be preferred",
    )
    b = PlacementLLMOutput(
        coverage_status="covered",
        um_present=[],
        interpreted_position="non_preferred",
        confidence=0.7,
        reasoning="tier says non-preferred",
    )
    llm2 = MagicMock()
    llm2.parse.side_effect = [a, b]
    out3 = interpret_placement_llm(
        llm2,
        drug_name="SYNTHROID",
        tier=None,
        coverage_status="covered",
        um_flags=[],
        raw_row_text="SYNTHROID",
        legend={},
        contract_position="preferred",
        model_name="mock-dis",
    )
    assert out3["consensus"] == "disagreed"
    assert out3["interpreted_position"] == "ambiguous"
    assert out3["needs_human_review"] is True
    assert len(out3["readings"]) == 2
    assert llm2.parse.call_count == 2
