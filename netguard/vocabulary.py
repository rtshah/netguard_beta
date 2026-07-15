"""Shared vocabulary for Modules 01–03 (extraction, contracts, invoices)."""

from __future__ import annotations

from enum import Enum


class FormularyPosition(str, Enum):
    exclusive = "exclusive"
    one_of_1 = "one_of_1"
    one_of_2 = "one_of_2"
    one_of_3 = "one_of_3"
    preferred = "preferred"
    non_preferred = "non_preferred"


class UMAllowance(str, Enum):
    allowed = "allowed"
    not_allowed = "not_allowed"


class EntityType(str, Enum):
    pbm = "pbm"
    health_plan = "health_plan"
    gpo = "gpo"


class ContractOrigin(str, Enum):
    generated_sample = "generated_sample"
    ingested_json = "ingested_json"


class SourceFormat(str, Enum):
    ncpdp = "ncpdp"
    rms_summary = "rms_summary"
    payer_custom = "payer_custom"


class MatchStatus(str, Enum):
    matched = "matched"
    other_bucket = "other_bucket"
    unmatched = "unmatched"


class RebateCycle(str, Enum):
    monthly = "monthly"
    quarterly = "quarterly"


EXTRACTION_UM_TO_CONTRACT_KEY: dict[str, str] = {
    "PA": "prior_auth",
    "ST": "step_therapy",
    "QL": "quantity_limit",
}

# Confidence threshold for plan→formulary joins (Module 03 Part C).
MATCH_CONFIDENCE_THRESHOLD = 0.80
