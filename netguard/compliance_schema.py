"""Module 04 compliance / validation output schema (agent_4 §4)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from .vocabulary import (
    CheckName,
    CheckResult,
    ConsensusStatus,
    CoverageObserved,
    InterpretedPosition,
    Verdict,
)


class DateWindow(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class ScopeGate(BaseModel):
    passed: bool
    reason: Optional[str] = None
    contract_canonical_id: Optional[str] = None
    formulary_canonical_id: Optional[str] = None


class MatchedFormularyLine(BaseModel):
    line_id: Optional[str] = None
    page_ref: Optional[int] = None
    raw_row_text: Optional[str] = None


class ObservedPlacement(BaseModel):
    coverage_status: CoverageObserved
    tier: Optional[int] = None
    interpreted_position: Optional[InterpretedPosition] = None
    um_present: List[str] = Field(default_factory=list)


class InterpretationReading(BaseModel):
    call: int
    interpreted_position: str
    um_present: List[str] = Field(default_factory=list)
    reasoning: str = ""


class InterpretationBlock(BaseModel):
    confidence: float = 0.0
    consensus: ConsensusStatus = ConsensusStatus.rules_only
    readings: List[InterpretationReading] = Field(default_factory=list)
    model: str = "rules"
    prompt_version: str = "rules-v1"
    source: str = "rules"  # rules | llm | cache


class CheckRecord(BaseModel):
    check: CheckName
    expected: str
    observed: str
    result: CheckResult
    rationale: str


class RequiredCondition(BaseModel):
    formulary_position: str
    prior_auth: str
    step_therapy: str
    quantity_limit: str
    rebate_rate_pct: float


class TermEvaluation(BaseModel):
    term_id: str
    required: RequiredCondition
    checks: List[CheckRecord]
    term_result: Verdict


class ProductResult(BaseModel):
    product_name: str
    ndc: Optional[str] = None
    matched_formulary_line: MatchedFormularyLine
    observed: ObservedPlacement
    interpretation: InterpretationBlock
    term_evaluations: List[TermEvaluation]
    best_matching_term_id: Optional[str] = None
    earned_rebate_rate_pct: Optional[float] = None
    claimed_rebate_rate_pct: Optional[float] = None
    verdict: Verdict
    needs_human_review: bool = False
    review_reasons: List[str] = Field(default_factory=list)


class ComplianceResult(BaseModel):
    contract_id: str
    formulary_id: str
    formulary_effective_window: DateWindow
    evaluated_at: str
    scope_gate: ScopeGate
    product_results: List[ProductResult] = Field(default_factory=list)
    # Orchestration context (optional; filled by CLI)
    plan_id: Optional[str] = None
    line_id: Optional[str] = None
    submitter_gpo: Optional[str] = None
