"""Canonical payer roster schema — agent_instructions/agent_3.md §4."""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class RosterPlan(BaseModel):
    plan_id: str
    plan_name: str
    plan_name_standardized: str
    address: Optional[str] = None
    address_standardized: Optional[str] = None
    formulary_id: Optional[str] = None
    lives: Optional[float] = None
    alt_ids: Dict[str, str] = Field(default_factory=dict)


class Roster(BaseModel):
    payer_or_pbm: str
    roster_period: str
    source_file: str
    plans: List[RosterPlan] = Field(default_factory=list)
