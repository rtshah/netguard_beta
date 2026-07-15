"""LLM dual-call consensus for ambiguous placement (Module 04 Step 3 fallback)."""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from .llm import TextLLM
from .placement_prompts import PROMPT_VERSION, SYSTEM_A, SYSTEM_B, user_prompt
from .verdict_cache import VerdictCache, cache_key, hash_payload
from .vocabulary import ConsensusStatus, InterpretedPosition


class PlacementLLMOutput(BaseModel):
    coverage_status: str = Field(description="covered | excluded | not_found")
    um_present: List[str] = Field(default_factory=list)
    interpreted_position: str = Field(
        description="exclusive|one_of_1|one_of_2|one_of_3|preferred|non_preferred|ambiguous"
    )
    confidence: float = Field(ge=0, le=1)
    reasoning: str = ""
    evidence_cited: dict = Field(default_factory=dict)


_VALID_POS = {p.value for p in InterpretedPosition}


def _normalize_reading(parsed: PlacementLLMOutput, call: int) -> dict[str, Any]:
    pos = parsed.interpreted_position.strip().lower().replace(" ", "_")
    if pos not in _VALID_POS:
        pos = InterpretedPosition.ambiguous.value
    um = [u for u in parsed.um_present if u in ("PA", "ST", "QL")]
    return {
        "call": call,
        "interpreted_position": pos,
        "um_present": um,
        "reasoning": parsed.reasoning or "",
        "confidence": float(parsed.confidence),
        "coverage_status": parsed.coverage_status,
    }


def interpret_placement_llm(
    llm: TextLLM,
    *,
    drug_name: str,
    tier: int | None,
    coverage_status: str,
    um_flags: list[str],
    raw_row_text: str | None,
    legend: dict[str, str],
    contract_position: str,
    contract_clause: str | None = None,
    page_ref: int | None = None,
    cache: Optional[VerdictCache] = None,
    model_name: str = "unknown",
) -> dict[str, Any]:
    """Two independent calls; agree → accept; disagree → ambiguous + both readings."""
    line_hash = hash_payload(
        {
            "drug": drug_name,
            "tier": tier,
            "cov": coverage_status,
            "um": sorted(um_flags or []),
            "raw": raw_row_text,
            "legend": legend,
        }
    )
    term_hash = hash_payload({"position": contract_position, "clause": contract_clause})
    key = cache_key(
        formulary_line_hash=line_hash,
        contract_term_hash=term_hash,
        prompt_version=PROMPT_VERSION,
        model=model_name,
    )
    if cache is not None:
        hit = cache.get(key)
        if hit is not None:
            hit = dict(hit)
            hit["source"] = "cache"
            hit["consensus"] = hit.get("consensus") or ConsensusStatus.cached.value
            return hit

    user = user_prompt(
        drug_name=drug_name,
        tier=tier,
        coverage_status=coverage_status,
        um_flags=list(um_flags or []),
        raw_row_text=raw_row_text,
        legend=legend or {},
        contract_position=contract_position,
        contract_clause=contract_clause,
    )
    # Independent prompts (not critique-of-first).
    r1 = _normalize_reading(llm.parse(SYSTEM_A, user, PlacementLLMOutput), 1)
    r2 = _normalize_reading(llm.parse(SYSTEM_B, user, PlacementLLMOutput), 2)

    agree = (
        r1["interpreted_position"] == r2["interpreted_position"]
        and sorted(r1["um_present"]) == sorted(r2["um_present"])
    )
    if agree:
        pos = r1["interpreted_position"]
        um = r1["um_present"]
        consensus = ConsensusStatus.agreed.value
        needs_review = False
        reasons: list[str] = []
        conf = min(r1["confidence"], r2["confidence"])
    else:
        pos = InterpretedPosition.ambiguous.value
        um = sorted(set(r1["um_present"]) | set(r2["um_present"]))
        consensus = ConsensusStatus.disagreed.value
        needs_review = True
        reasons = ["interpretation_disagreement"]
        conf = min(r1["confidence"], r2["confidence"])

    out = {
        "coverage_status": r1.get("coverage_status") or coverage_status,
        "um_present": um,
        "interpreted_position": pos,
        "confidence": conf,
        "reasoning": r1["reasoning"] if agree else "Dual-call disagreement; human review required.",
        "consensus": consensus,
        "readings": [r1, r2],
        "model": model_name,
        "prompt_version": PROMPT_VERSION,
        "needs_human_review": needs_review,
        "review_reasons": reasons,
        "source": "llm",
        "evidence_cited": {
            "page_ref": page_ref,
            "raw_row_text": raw_row_text,
            "clause": contract_clause,
        },
        "ambiguous": not agree or pos == InterpretedPosition.ambiguous.value,
    }
    if cache is not None:
        cache.set(key, out)
    return out
