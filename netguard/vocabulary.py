"""Shared vocabulary for Module 01 extraction codes and Module 02/04 contract terms."""

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


class ContractOrigin(str, Enum):
    generated_sample = "generated_sample"
    ingested_json = "ingested_json"


EXTRACTION_UM_TO_CONTRACT_KEY: dict[str, str] = {
    "PA": "prior_auth",
    "ST": "step_therapy",
    "QL": "quantity_limit",
}
