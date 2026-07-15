"""Thin claimed-vs-contract rate preview (Module 03 acceptance harness, not full Module 04)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

from .contract_ingest import ingest_contract_file
from .submittal_schema import Submittal
from .vocabulary import MatchStatus


def _load_contracts(contracts_dir: Path) -> list[Any]:
    files = [contracts_dir] if contracts_dir.is_file() else sorted(contracts_dir.rglob("*.json"))
    out = []
    for f in files:
        try:
            out.append(ingest_contract_file(f))
        except Exception:
            continue
    return out


def _term_rate_for_formulary(contracts: list[Any], formulary_id: str, product_name: str) -> Optional[dict]:
    """Prefer an exact covered_formularies hit over a wildcard `*` contract."""
    product_u = product_name.strip().upper()
    wildcard: Optional[dict] = None
    for ingested in contracts:
        c = ingested.contract
        covered = set(c.covered_formularies)
        exact = formulary_id in covered
        star = "*" in covered
        if not exact and not star:
            continue
        for product in c.products:
            if product.product_name.strip().upper() != product_u:
                continue
            if not product.rebate_terms:
                continue
            term = product.rebate_terms[0]
            hit = {
                "contract_id": c.contract_id,
                "counterparty": c.counterparty.name,
                "term_id": term.term_id,
                "rebate_rate_pct": term.rebate_rate_pct,
                "covered_formularies": list(c.covered_formularies),
            }
            if exact:
                return hit
            if wildcard is None:
                wildcard = hit
    return wildcard


def preview_rate_discrepancies(
    submittal: Submittal,
    contracts_dir: Path,
    *,
    only_matched: bool = True,
    rates_overlay: dict[str, float] | None = None,
) -> List[dict]:
    """Compare rebate_rate_pct_claimed to Module 02 contract term rates.

    `rates_overlay` (formulary_id → pct) fills gaps for synthetic demo IDs
    that are not yet listed on a contract's covered_formularies.
    """
    contracts = _load_contracts(Path(contracts_dir)) if Path(contracts_dir).exists() else []
    overlay = rates_overlay or {}
    findings: list[dict] = []
    for line in submittal.lines:
        if only_matched and line.match_status != MatchStatus.matched:
            continue
        if line.rebate_rate_pct_claimed is None:
            continue
        if not line.resolved_formulary_id:
            findings.append(
                {
                    "line_id": line.line_id,
                    "status": "skipped_unresolved",
                    "plan_id_raw": line.plan_id_raw,
                    "match_status": line.match_status.value,
                }
            )
            continue
        # Demo overlay is authoritative for generated DEMO-* join keys.
        if line.resolved_formulary_id in overlay:
            term = {
                "contract_id": "rates_overlay",
                "counterparty": "demo_overlay",
                "term_id": "overlay",
                "rebate_rate_pct": overlay[line.resolved_formulary_id],
                "covered_formularies": [line.resolved_formulary_id],
            }
        else:
            term = _term_rate_for_formulary(
                contracts, line.resolved_formulary_id, line.product_name
            )
        if term is None:
            findings.append(
                {
                    "line_id": line.line_id,
                    "status": "no_contract_term",
                    "resolved_formulary_id": line.resolved_formulary_id,
                    "product_name": line.product_name,
                    "claimed_rate_pct": line.rebate_rate_pct_claimed,
                }
            )
            continue
        claimed = float(line.rebate_rate_pct_claimed)
        owed = float(term["rebate_rate_pct"])
        delta = round(claimed - owed, 4)
        status = "rate_mismatch" if abs(delta) > 1e-6 else "rate_match"
        findings.append(
            {
                "line_id": line.line_id,
                "status": status,
                "product_name": line.product_name,
                "plan_id_raw": line.plan_id_raw,
                "resolved_plan_id": line.resolved_plan_id,
                "resolved_formulary_id": line.resolved_formulary_id,
                "claimed_rate_pct": claimed,
                "contract_rate_pct": owed,
                "delta_pct": delta,
                "submittal_provenance": {
                    "source_file": submittal.submittal.source_file,
                    "raw_row": line.raw_row,
                },
                "contract_provenance": term,
            }
        )
    return findings


def write_findings(findings: List[dict], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(findings, indent=2) + "\n", encoding="utf-8")
    return path
