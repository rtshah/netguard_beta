"""Deterministic plan→formulary fuzzy resolution (Module 03 Part C)."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Optional

from rapidfuzz import fuzz

from .roster_schema import Roster, RosterPlan
from .standardize import standardize_address, standardize_name
from .submittal_schema import Submittal, SubmittalLine
from .vocabulary import MATCH_CONFIDENCE_THRESHOLD, MatchStatus


def _impact(line: SubmittalLine) -> float:
    if line.rebate_amount_claimed is not None:
        return float(line.rebate_amount_claimed)
    if line.rebate_rate_pct_claimed is not None and line.utilization_units is not None:
        return float(line.rebate_rate_pct_claimed) * float(line.utilization_units)
    if line.utilization_units is not None:
        return float(line.utilization_units)
    return 0.0


def _norm_plan_id(value: str) -> str:
    v = (value or "").strip().lower().replace("_", "-")
    if v.endswith("x") and len(v) > 1:
        # Demo fuzzy suffix: ESI-0001X → ESI-0001
        v = v[:-1]
    return v


def _score(line: SubmittalLine, plan: RosterPlan) -> float:
    """Blend plan-id / name / address similarity into confidence 0–1."""
    plan_id_raw = (line.plan_id_raw or "").strip().lower()
    roster_id = (plan.plan_id or "").strip().lower()
    norm_raw = _norm_plan_id(plan_id_raw)
    norm_roster = _norm_plan_id(roster_id)

    if plan_id_raw and roster_id and (plan_id_raw == roster_id or norm_raw == norm_roster):
        id_score = 100.0
    elif plan_id_raw and roster_id:
        id_score = float(fuzz.ratio(norm_raw, norm_roster))
    else:
        id_score = 0.0

    name_raw = standardize_name(line.plan_name_raw)
    name_score = (
        float(fuzz.token_set_ratio(name_raw, plan.plan_name_standardized or ""))
        if name_raw
        else 0.0
    )

    addr_score = 0.0
    addr_raw = standardize_address(getattr(line, "address_raw", None))
    if addr_raw and plan.address_standardized:
        addr_score = float(fuzz.token_set_ratio(addr_raw, plan.address_standardized))

    # Weighted blend — plan ID dominates when present; name secondary; address tertiary.
    if plan_id_raw:
        blended = 0.55 * id_score + 0.35 * name_score + 0.10 * addr_score
    else:
        blended = 0.70 * name_score + 0.30 * addr_score
    return round(blended / 100.0, 4)


def _lives(plan: RosterPlan) -> float:
    return float(plan.lives) if plan.lives is not None else 0.0


def _formulary_rate_map(contract_rates: dict[str, float] | None) -> dict[str, float]:
    return contract_rates or {}


def resolve_line(
    line: SubmittalLine,
    roster: Roster,
    *,
    threshold: float = MATCH_CONFIDENCE_THRESHOLD,
    contract_rates_by_formulary: dict[str, float] | None = None,
) -> SubmittalLine:
    out = line.model_copy(deep=True)
    if not roster.plans:
        out.match_status = MatchStatus.unmatched
        out.match_audit = {"reason": "empty_roster"}
        return out

    scored: list[tuple[float, RosterPlan]] = [(_score(line, p), p) for p in roster.plans]
    scored.sort(key=lambda t: (t[0], _lives(t[1])), reverse=True)
    best_score, best_plan = scored[0]

    out.match_confidence = best_score
    if best_score < threshold:
        out.match_status = MatchStatus.other_bucket
        out.resolved_plan_id = None
        out.resolved_formulary_id = None
        out.match_audit = {
            "reason": "below_threshold",
            "threshold": threshold,
            "top_candidates": [
                {
                    "plan_id": p.plan_id,
                    "plan_name": p.plan_name,
                    "formulary_id": p.formulary_id,
                    "confidence": s,
                    "lives": p.lives,
                }
                for s, p in scored[:3]
            ],
        }
        return out

    # Candidates within a small band of the best score (same plan id or near-ties).
    near = [(s, p) for s, p in scored if s >= threshold and s >= best_score - 0.02]
    # Prefer exact / stripped-fuzzy plan_id matches among near-threshold candidates.
    raw_id = (line.plan_id_raw or "").strip().lower()
    exact_id = [
        (s, p)
        for s, p in near
        if _norm_plan_id(raw_id) == _norm_plan_id(p.plan_id or "")
    ]
    seed_pool = exact_id or near
    # Dual-formulary rosters list the same plan_id on multiple rows with different
    # formulary names — include every roster row for that plan_id once we have a
    # confident hit (do not require each row's name score to clear the threshold).
    if seed_pool:
        win_id = seed_pool[0][1].plan_id
        score_by_fid = {p.formulary_id: s for s, p in scored if p.plan_id == win_id}
        pool = [
            (score_by_fid.get(p.formulary_id, best_score), p)
            for p in roster.plans
            if p.plan_id == win_id
        ]
    else:
        pool = seed_pool

    rate_map = _formulary_rate_map(contract_rates_by_formulary)
    formularies = {p.formulary_id for _, p in pool if p.formulary_id}

    # Submitted formulary field may list multiple IDs ("A;B") — treat as leakage signal.
    raw_fids = [
        x.strip()
        for x in re.split(r"[;|]", out.formulary_id_raw or "")
        if x.strip()
    ]
    multi_submitted = len(raw_fids) > 1
    if multi_submitted:
        formularies |= set(raw_fids)

    rates = {rate_map[f] for f in formularies if f in rate_map}
    leakage = len(formularies) > 1 or multi_submitted

    def _rate_for(plan: RosterPlan) -> float:
        if plan.formulary_id and plan.formulary_id in rate_map:
            return rate_map[plan.formulary_id]
        return float("inf")

    if leakage:
        # Demo/prod rule for ambiguous multi-formulary: route to lower contract rate,
        # flag for human review (do not silently take the higher rebate).
        pool.sort(key=lambda t: (_rate_for(t[1]), -_lives(t[1]), -t[0]))
        rollup = "lowest_contract_rate"
    else:
        # Clean 1-to-many on same formulary: highest lives.
        pool.sort(key=lambda t: (_lives(t[1]), t[0]), reverse=True)
        rollup = "highest_lives" if len(pool) > 1 else "single"

    chosen_score, chosen = pool[0]

    out.match_status = MatchStatus.matched
    out.resolved_plan_id = chosen.plan_id
    if multi_submitted or not out.formulary_id_raw:
        out.resolved_formulary_id = chosen.formulary_id
    else:
        # Single submitted formulary ID — keep it when present.
        out.resolved_formulary_id = raw_fids[0] if raw_fids else chosen.formulary_id
    out.match_confidence = chosen_score
    out.leakage_candidate = leakage
    if leakage:
        out.match_audit = {
            "reason": "multi_formulary_leakage",
            "chosen_plan_id": chosen.plan_id,
            "chosen_formulary_id": chosen.formulary_id,
            "rollup": rollup,
            "needs_human_review": True,
            "candidate_formularies": sorted(f for f in formularies if f),
            "candidate_rates": sorted(rates) if rates else None,
            "submitted_formulary_ids": raw_fids or None,
            "top_candidates": [
                {
                    "plan_id": p.plan_id,
                    "plan_name": p.plan_name,
                    "formulary_id": p.formulary_id,
                    "confidence": s,
                    "lives": p.lives,
                    "contract_rate_pct": rate_map.get(p.formulary_id) if p.formulary_id else None,
                }
                for s, p in pool
            ],
        }
    else:
        out.match_audit = {
            "reason": "matched",
            "chosen_plan_id": chosen.plan_id,
            "chosen_formulary_id": out.resolved_formulary_id,
            "rollup": rollup,
            "recovered_formulary_from_roster": not bool(line.formulary_id_raw),
            "top_candidates": [
                {
                    "plan_id": p.plan_id,
                    "plan_name": p.plan_name,
                    "formulary_id": p.formulary_id,
                    "confidence": s,
                    "lives": p.lives,
                }
                for s, p in scored[:3]
            ],
        }

    if out.resolved_formulary_id is None:
        out.match_audit = {
            **(out.match_audit or {}),
            "enrollment_form_fallback": "flagged_for_review",
            "note": "roster could not supply formulary_id; enrollment-form fallback deferred",
        }

    return out


def resolve_submittal(
    submittal: Submittal,
    roster: Roster,
    *,
    threshold: float = MATCH_CONFIDENCE_THRESHOLD,
    contract_rates_by_formulary: dict[str, float] | None = None,
) -> Submittal:
    """Resolve lines ranked by rebate impact (high → low)."""
    out = deepcopy(submittal)
    indexed = list(enumerate(out.lines))
    indexed.sort(key=lambda t: _impact(t[1]), reverse=True)
    resolved_by_idx: dict[int, SubmittalLine] = {}
    for idx, line in indexed:
        resolved_by_idx[idx] = resolve_line(
            line,
            roster,
            threshold=threshold,
            contract_rates_by_formulary=contract_rates_by_formulary,
        )
    out.lines = [resolved_by_idx[i] for i in range(len(out.lines))]
    return out


def contract_rates_from_dir(contracts_dir: Optional[str] = None) -> dict[str, float]:
    """Build formulary_id → rebate_rate_pct from Module 02 sample contracts (first term)."""
    from pathlib import Path
    import json

    if not contracts_dir:
        return {}
    root = Path(contracts_dir)
    rates: dict[str, float] = {}
    if not root.exists():
        return rates
    files = [root] if root.is_file() else sorted(root.rglob("*.json"))
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        products = data.get("products") or []
        if not products:
            continue
        terms = products[0].get("rebate_terms") or []
        if not terms:
            continue
        rate = terms[0].get("rebate_rate_pct")
        if rate is None:
            continue
        for fid in data.get("covered_formularies") or []:
            if fid and fid != "*":
                rates.setdefault(str(fid), float(rate))
    return rates
