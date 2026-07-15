"""Generate compliant demo contract JSON files from master templates."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set

from .contract_catalog import MASTER_TEMPLATES, all_mapped_stems
from .contract_ingest import _normalize_formulary_id


def _slug(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower())
    return s.strip("-") or "contract"


def _load_formulary_index(formulary_dir: Path) -> Dict[str, dict]:
    index: Dict[str, dict] = {}
    for jf in sorted(formulary_dir.glob("*.json")):
        data = json.loads(jf.read_text())
        index[jf.stem] = data.get("document", {})
    return index


def _formulary_ids_for_stems(stems: Set[str], index: Dict[str, dict]) -> tuple[List[str], List[str]]:
    ids: Set[str] = set()
    files_without_id: List[str] = []
    for stem in sorted(stems):
        doc = index.get(stem, {})
        fid = _normalize_formulary_id(doc.get("formulary_id"))
        if fid:
            ids.add(fid)
        elif stem in index:
            files_without_id.append(stem)
    return sorted(ids), files_without_id


def _compliant_term(rebate_rate_pct: float, notes: str) -> dict:
    return {
        "term_id": "open-access-nonpreferred",
        "condition": {
            "formulary_position": "non_preferred",
            "prior_auth": "allowed",
            "step_therapy": "allowed",
            "quantity_limit": "allowed",
        },
        "rebate_rate_pct": rebate_rate_pct,
        "notes": notes,
    }


def build_contract_dict(tmpl, formulary_ids: List[str], files_without_id: List[str]) -> dict:
    if tmpl.placeholder or not tmpl.stems:
        covered = ["*"]
        member_note = "Placeholder — no demo formularies mapped yet."
    elif files_without_id and not formulary_ids:
        covered = ["*"]
        member_note = f"Wildcard join; demo files: {', '.join(files_without_id)}."
    elif files_without_id:
        covered = formulary_ids
        member_note = (
            f"IDs listed for joinable formularies. Additional demo files without printed IDs: "
            f"{', '.join(files_without_id)}."
        )
    else:
        covered = formulary_ids if formulary_ids else ["*"]
        member_note = f"Demo formularies: {', '.join(sorted(tmpl.stems))}."

    return {
        "contract_id": tmpl.contract_id,
        "contract_name": tmpl.contract_name,
        "manufacturer": "AbbVie Inc.",
        "counterparty": {"name": tmpl.counterparty, "entity_type": tmpl.entity_type},
        "effective_start": "2026-01-01",
        "effective_end": "2026-12-31",
        "lookback_months": tmpl.lookback_months,
        "payment_terms_days": tmpl.payment_terms_days,
        "covered_formularies": covered,
        "products": [
            {
                "product_name": "SYNTHROID",
                "ndc": None,
                "therapeutic_class": "Thyroid Hormones",
                "rebate_terms": [
                    _compliant_term(
                        tmpl.rebate_rate_pct,
                        f"{tmpl.notes} {member_note} Compliant demo terms (all UM allowed).",
                    )
                ],
            }
        ],
        "source": {
            "origin": "generated_sample",
            "ingested_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        },
    }


def generate_contracts(
    output_dir: Path,
    formulary_dir: Path,
    *,
    overwrite: bool = True,
) -> List[Path]:
    index = _load_formulary_index(formulary_dir)
    written: List[Path] = []

    for tmpl in MASTER_TEMPLATES:
        ids, missing = _formulary_ids_for_stems(tmpl.stems, index)
        payload = build_contract_dict(tmpl, ids, missing)
        dest_dir = output_dir / tmpl.folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{_slug(tmpl.key)}.json"
        if dest.exists() and not overwrite:
            continue
        dest.write_text(json.dumps(payload, indent=2) + "\n")
        written.append(dest)

    return written


def coverage_report(formulary_dir: Path) -> dict:
    index = _load_formulary_index(formulary_dir)
    all_stems = set(index.keys())
    mapped = all_mapped_stems()
    unmapped = sorted(all_stems - mapped)
    return {
        "formulary_count": len(all_stems),
        "mapped_count": len(mapped & all_stems),
        "unmapped_stems": unmapped,
    }
