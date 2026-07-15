"""Deterministic tier → formulary position interpretation (Module 04 Step 3 rules path)."""

from __future__ import annotations

from typing import Any, Optional

from .vocabulary import CoverageObserved, InterpretedPosition


# Better (lower rank) → worse (higher rank). Ambiguous has no rank.
POSITION_RANK: dict[str, int] = {
    InterpretedPosition.exclusive.value: 0,
    InterpretedPosition.one_of_1.value: 1,
    InterpretedPosition.one_of_2.value: 2,
    InterpretedPosition.one_of_3.value: 3,
    InterpretedPosition.preferred.value: 4,
    InterpretedPosition.non_preferred.value: 5,
}


def position_satisfies(required: str, observed: str) -> Optional[bool]:
    """True if observed is at least as good as required. None if either is ambiguous."""
    if observed == InterpretedPosition.ambiguous.value or required == InterpretedPosition.ambiguous.value:
        return None
    req_r = POSITION_RANK.get(required)
    obs_r = POSITION_RANK.get(observed)
    if req_r is None or obs_r is None:
        return None
    return obs_r <= req_r


def interpret_placement_rules(
    *,
    coverage_status: str,
    tier: Optional[int],
    um_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Return structured interpretation from formulary line fields (no LLM).

    Rules (demo-coarse):
      - excluded / non_formulary → coverage excluded; position N/A
      - covered + tier 1–2 → preferred
      - covered + tier >= 3 → non_preferred
      - covered + tier missing → ambiguous
      - unknown coverage → ambiguous
    """
    um = [u for u in (um_flags or []) if u in ("PA", "ST", "QL")]
    cov = (coverage_status or "").lower().strip()

    if cov in ("excluded", "non_formulary"):
        return {
            "coverage_status": CoverageObserved.excluded.value,
            "um_present": um,
            "interpreted_position": InterpretedPosition.ambiguous.value,
            "confidence": 1.0,
            "reasoning": f"Formulary coverage_status={cov!r}; product not on formulary access terms.",
            "ambiguous": False,
            "source": "rules",
        }

    if cov == "covered":
        if tier is None:
            return {
                "coverage_status": CoverageObserved.covered.value,
                "um_present": um,
                "interpreted_position": InterpretedPosition.ambiguous.value,
                "confidence": 0.4,
                "reasoning": "Covered but tier missing — cannot map to preferred vs non_preferred.",
                "ambiguous": True,
                "source": "rules",
            }
        if tier <= 2:
            pos = InterpretedPosition.preferred.value
            why = f"Covered on tier {tier} (≤2) → preferred."
        else:
            pos = InterpretedPosition.non_preferred.value
            why = f"Covered on tier {tier} (≥3) → non_preferred."
        return {
            "coverage_status": CoverageObserved.covered.value,
            "um_present": um,
            "interpreted_position": pos,
            "confidence": 0.9,
            "reasoning": why,
            "ambiguous": False,
            "source": "rules",
        }

    return {
        "coverage_status": CoverageObserved.covered.value
        if cov == "covered"
        else CoverageObserved.excluded.value,
        "um_present": um,
        "interpreted_position": InterpretedPosition.ambiguous.value,
        "confidence": 0.3,
        "reasoning": f"Unclear coverage_status={coverage_status!r}; treating placement as ambiguous.",
        "ambiguous": True,
        "source": "rules",
    }
