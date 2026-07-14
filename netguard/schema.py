"""Pydantic models.

Two layers:
  1. LLM-output models used with OpenAI structured outputs. Strict mode forbids
     free-form dicts, so the legend is modeled as a list of entries here.
  2. Final result models shaped to agent_instructions/agent_1.md section 3, where
     the legend is a normal {CODE: meaning} object.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    commercial = "commercial"
    medicare_part_d = "medicare_part_d"
    medicaid = "medicaid"
    exchange = "exchange"
    unknown = "unknown"


class BrandOrGeneric(str, Enum):
    brand = "brand"
    branded_generic = "branded_generic"
    generic = "generic"
    unknown = "unknown"


class CoverageStatus(str, Enum):
    covered = "covered"
    excluded = "excluded"
    non_formulary = "non_formulary"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Layer 1: LLM structured-output models (strict-mode friendly, no free dicts)
# ---------------------------------------------------------------------------


class LegendEntry(BaseModel):
    code: str = Field(description="The symbol/abbreviation exactly as printed, e.g. 'PA', 'ST', 'QL', 'PA*'.")
    meaning: str = Field(description="The resolved meaning for THIS document.")


class DocumentMetaLLM(BaseModel):
    payer_or_pbm: Optional[str] = Field(description="e.g. 'Express Scripts', 'CVS Caremark', 'Optum Rx'.")
    formulary_name: Optional[str] = Field(description="e.g. 'National Preferred Formulary'.")
    formulary_id: Optional[str] = Field(description="Formulary ID/number if printed, else null.")
    document_type: DocumentType
    template_label: Optional[str] = Field(description="e.g. 'Value', 'Advanced Control', 'Basic Control'.")
    effective_start: Optional[str] = Field(description="YYYY-MM-DD or null.")
    effective_end: Optional[str] = Field(description="YYYY-MM-DD or null.")
    plan_year: Optional[int]
    updated_on: Optional[str] = Field(description="YYYY-MM-DD or null.")
    legend: List[LegendEntry] = Field(description="Every code/symbol defined in THIS document's key.")
    notes: Optional[str] = Field(description="Anything ambiguous or worth a human's attention.")


class DrugExtractionLLM(BaseModel):
    """What the vision model reports for one target drug from the screenshot(s)."""

    found: bool = Field(description="True only if this specific drug is visibly listed on the page image(s).")
    drug_name_raw: Optional[str] = Field(description="Exactly as printed (preserve casing/punctuation).")
    drug_name_normalized: Optional[str] = Field(description="Lowercase normalized ingredient/brand name.")
    brand_or_generic: BrandOrGeneric = Field(
        description="Infer from typography: ALL CAPS=brand, lowercase=generic, mixed/italic=branded_generic."
    )
    strength: Optional[str]
    dosage_form: Optional[str]
    therapeutic_class: Optional[str]
    therapeutic_subclass: Optional[str]
    coverage_status: CoverageStatus
    tier: Optional[int] = Field(description="Copay tier as printed (1-5+). Null if none shown. Do NOT infer.")
    um_flags: List[str] = Field(description="Utilization codes present on this drug's row (e.g. PA, ST, QL, SP).")
    um_detail: Optional[str] = Field(description="Parenthetical limit text, e.g. 'QL 60 caps / 30 days'.")
    footnotes: List[str] = Field(description="Footnote/marker symbols attached to this row.")
    is_exclusion: bool = Field(description="True if the drug appears in an exclusions/not-covered table.")
    preferred_alternatives: List[str] = Field(description="Only if shown in an exclusions table, else empty.")
    effective_note: Optional[str] = Field(description="Any date-scoped rule, e.g. 'excluded 7/1/2026'.")
    raw_row_text: Optional[str] = Field(description="The full row text as printed (provenance).")
    confidence: float = Field(description="0-1 confidence in this extraction.")
    notes: Optional[str] = Field(description="Ambiguities, multiple listings, or why unsure.")


# ---------------------------------------------------------------------------
# Layer 2: Final result models (section 3 shape)
# ---------------------------------------------------------------------------


class DocumentBlock(BaseModel):
    source_file: str
    source_file_hash: str
    payer_or_pbm: Optional[str] = None
    formulary_name: Optional[str] = None
    formulary_id: Optional[str] = None
    document_type: str = "unknown"
    template_label: Optional[str] = None
    effective_start: Optional[str] = None
    effective_end: Optional[str] = None
    plan_year: Optional[int] = None
    updated_on: Optional[str] = None
    legend: dict[str, str] = Field(default_factory=dict)
    extraction_confidence: float = 0.0
    needs_human_review: bool = False
    review_reasons: List[str] = Field(default_factory=list)


class Line(BaseModel):
    line_id: str
    drug_name_raw: str
    drug_name_normalized: Optional[str] = None
    brand_or_generic: str = "unknown"
    strength: Optional[str] = None
    dosage_form: Optional[str] = None
    therapeutic_class: Optional[str] = None
    therapeutic_subclass: Optional[str] = None
    coverage_status: str = "unknown"
    tier: Optional[int] = None
    um_flags: List[str] = Field(default_factory=list)
    um_detail: Optional[str] = None
    footnotes: List[str] = Field(default_factory=list)
    page_ref: int
    raw_row_text: str
    # Extension beyond section 3: screenshot provenance artifact.
    screenshot_path: Optional[str] = None
    # Per-line review handling for targeted validation.
    query_drug: Optional[str] = None
    needs_human_review: bool = False
    review_reasons: List[str] = Field(default_factory=list)
    extraction_confidence: float = 0.0


class Exclusion(BaseModel):
    drug_name_raw: str
    preferred_alternatives: List[str] = Field(default_factory=list)
    effective_note: Optional[str] = None
    page_ref: int
    screenshot_path: Optional[str] = None
    query_drug: Optional[str] = None
    raw_row_text: Optional[str] = None


class Result(BaseModel):
    document: DocumentBlock
    lines: List[Line] = Field(default_factory=list)
    exclusions: List[Exclusion] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
