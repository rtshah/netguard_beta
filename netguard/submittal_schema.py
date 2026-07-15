"""Canonical submittal / utilization schema — agent_instructions/agent_3.md §3."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .vocabulary import MatchStatus, RebateCycle, SourceFormat


class RebatePeriod(BaseModel):
    start: str
    end: str
    cycle: RebateCycle


class SubmittalMeta(BaseModel):
    source_file: str
    source_format: SourceFormat
    payer_or_pbm: str
    rebate_period: RebatePeriod
    ingested_at: datetime


class SubmittalLine(BaseModel):
    line_id: str
    ndc: Optional[str] = None
    product_name: str
    dosage: Optional[str] = None
    plan_id_raw: str
    plan_name_raw: Optional[str] = None
    address_raw: Optional[str] = None
    formulary_id_raw: Optional[str] = None
    utilization_units: Optional[float] = None
    rebate_amount_claimed: Optional[float] = None
    rebate_rate_pct_claimed: Optional[float] = None
    raw_row: str
    resolved_plan_id: Optional[str] = None
    resolved_formulary_id: Optional[str] = None
    match_confidence: Optional[float] = None
    match_status: MatchStatus = MatchStatus.unmatched
    leakage_candidate: bool = False
    match_audit: Optional[dict] = None


class Submittal(BaseModel):
    submittal: SubmittalMeta
    lines: List[SubmittalLine] = Field(default_factory=list)


class LLMExtractedLine(BaseModel):
    """LLM-facing line shape before provenance / resolution fields are wired."""

    line_id: Optional[str] = None
    ndc: Optional[str] = None
    product_name: str
    dosage: Optional[str] = None
    plan_id_raw: str
    plan_name_raw: Optional[str] = None
    address_raw: Optional[str] = None
    formulary_id_raw: Optional[str] = None
    utilization_units: Optional[float] = None
    rebate_amount_claimed: Optional[float] = None
    rebate_rate_pct_claimed: Optional[float] = None
    raw_row: str


class LLMExtractedSubmittal(BaseModel):
    payer_or_pbm: str
    source_format: SourceFormat
    rebate_period_start: str
    rebate_period_end: str
    rebate_cycle: RebateCycle = RebateCycle.quarterly
    lines: List[LLMExtractedLine]
    parse_notes: Optional[str] = None
