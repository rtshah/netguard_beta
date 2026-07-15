"""Canonical contract schema — agent_instructions/agent_2.md section 3."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from .vocabulary import ContractOrigin, EntityType, FormularyPosition, UMAllowance


class Counterparty(BaseModel):
    name: str
    entity_type: EntityType


class RebateCondition(BaseModel):
    formulary_position: FormularyPosition
    prior_auth: UMAllowance
    step_therapy: UMAllowance
    quantity_limit: UMAllowance


class RebateTerm(BaseModel):
    term_id: str
    condition: RebateCondition
    rebate_rate_pct: float = Field(gt=0, le=100)
    notes: Optional[str] = None


class Product(BaseModel):
    product_name: str
    ndc: Optional[str] = None
    therapeutic_class: str
    rebate_terms: List[RebateTerm] = Field(min_length=1)


class ContractSource(BaseModel):
    origin: ContractOrigin
    ingested_at: datetime


class Contract(BaseModel):
    contract_id: str
    contract_name: str
    manufacturer: str
    counterparty: Counterparty
    effective_start: str
    effective_end: str
    lookback_months: int = Field(ge=1, le=36)
    payment_terms_days: int = Field(ge=1, le=365)
    covered_formularies: List[str] = Field(min_length=1)
    products: List[Product] = Field(min_length=1)
    source: ContractSource

    @field_validator("effective_start", "effective_end")
    @classmethod
    def _date_format(cls, v: str) -> str:
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError(f"expected YYYY-MM-DD, got {v!r}")
        return v


class IngestedContract(BaseModel):
    contract: Contract
    join_keys: List[dict]
