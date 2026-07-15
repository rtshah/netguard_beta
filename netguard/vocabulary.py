"""Shared vocabulary for Modules 01–04 (extraction, contracts, invoices, compliance)."""

from __future__ import annotations

from enum import Enum


class FormularyPosition(str, Enum):
    exclusive = "exclusive"
    one_of_1 = "one_of_1"
    one_of_2 = "one_of_2"
    one_of_3 = "one_of_3"
    preferred = "preferred"
    non_preferred = "non_preferred"


class InterpretedPosition(str, Enum):
    """Placement positions including ambiguous (LLM disagreement / unclear tier)."""

    exclusive = "exclusive"
    one_of_1 = "one_of_1"
    one_of_2 = "one_of_2"
    one_of_3 = "one_of_3"
    preferred = "preferred"
    non_preferred = "non_preferred"
    ambiguous = "ambiguous"


class Verdict(str, Enum):
    compliant = "compliant"
    non_compliant = "non_compliant"
    indeterminate = "indeterminate"


class CheckResult(str, Enum):
    pass_ = "pass"
    fail = "fail"
    indeterminate = "indeterminate"
    not_evaluated = "not_evaluated"


class CheckName(str, Enum):
    coverage = "coverage"
    position = "position"
    prior_auth = "prior_auth"
    step_therapy = "step_therapy"
    quantity_limit = "quantity_limit"
    rate = "rate"


class CoverageObserved(str, Enum):
    covered = "covered"
    excluded = "excluded"
    not_found = "not_found"


class ConsensusStatus(str, Enum):
    agreed = "agreed"
    disagreed = "disagreed"
    rules_only = "rules_only"
    cached = "cached"


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
