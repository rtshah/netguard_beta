"""Human-readable plan → formulary → PBM/GPO contract mapping report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


def _load_contract_index(contracts_dir: Path) -> list[dict]:
    rows: list[dict] = []
    root = Path(contracts_dir)
    files = [root] if root.is_file() else sorted(root.rglob("*.json"))
    for f in files:
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.append(
            {
                "path": str(f.relative_to(root) if root.is_dir() else f.name),
                "gpo_folder": f.parent.name if root.is_dir() else "",
                "contract_id": c.get("contract_id"),
                "counterparty": (c.get("counterparty") or {}).get("name"),
                "covered": list(c.get("covered_formularies") or []),
            }
        )
    return rows


def _submitter_from_filename(name: str) -> str:
    return Path(name).stem.replace("_ncpdp_q1_2026", "").replace(".resolved", "")


def build_mapping_rows(
    resolved_dir: Path,
    contracts_dir: Path,
    *,
    rates_overlay: Optional[Dict[str, float]] = None,  # kept for CLI compat; unused
) -> List[dict]:
    del rates_overlay  # rate checks are Module 04 — not shown here
    contracts = _load_contract_index(Path(contracts_dir))
    rows: list[dict] = []

    files = sorted(Path(resolved_dir).glob("*_ncpdp_*.resolved.json"))
    prefer = {
        f.name
        for f in files
        if "zinc" in f.name or "emisar" in f.name or f.name.startswith(("ascent_", "medimpact_"))
    }
    legacy_skip = set()
    if any("cvs_zinc" in n for n in prefer):
        legacy_skip |= {n for n in (f.name for f in files) if n.startswith("cvs_ncpdp")}
    if any("optum_emisar" in n for n in prefer):
        legacy_skip |= {
            n for n in (f.name for f in files) if n.startswith("optum_ncpdp") and "emisar" not in n
        }

    for f in files:
        if f.name in legacy_skip:
            continue
        submitter = _submitter_from_filename(f.name)
        data = json.loads(f.read_text(encoding="utf-8"))
        for line in data.get("lines") or []:
            fid = line.get("resolved_formulary_id")
            exact = None
            if fid:
                folder_hits = [
                    c for c in contracts if fid in c["covered"] and c["gpo_folder"] == submitter
                ]
                any_hits = [c for c in contracts if fid in c["covered"]]
                exact = (folder_hits or any_hits or [None])[0]

            rows.append(
                {
                    "submitter_gpo": submitter,
                    "line_id": line.get("line_id"),
                    "plan_id_raw": line.get("plan_id_raw"),
                    "resolved_plan_id": line.get("resolved_plan_id"),
                    "plan_name_raw": line.get("plan_name_raw"),
                    "formulary_id_raw": line.get("formulary_id_raw"),
                    "resolved_formulary_id": fid,
                    "match_status": line.get("match_status"),
                    "match_confidence": line.get("match_confidence"),
                    "leakage_candidate": bool(line.get("leakage_candidate")),
                    "contract_id": exact["contract_id"] if exact else None,
                    "counterparty": exact["counterparty"] if exact else None,
                    "contract_path": exact["path"] if exact else None,
                    "recovered_formulary": bool(
                        (line.get("match_audit") or {}).get("recovered_formulary_from_roster")
                    ),
                }
            )
    return rows


def format_mapping_table(rows: List[dict], *, limit: Optional[int] = None) -> str:
    header = (
        f"{'GPO':<14} {'plan_raw':<18} {'→ plan':<18} {'formulary':<28} "
        f"{'status':<12} {'contract_id':<40} flags"
    )
    lines = [header, "-" * len(header)]
    shown = rows if limit is None else rows[:limit]
    for r in shown:
        flags = []
        if r.get("leakage_candidate"):
            flags.append("LEAK")
        if r.get("recovered_formulary"):
            flags.append("recovered_fid")
        if r.get("match_status") == "other_bucket":
            flags.append("OTHER")
        if not r.get("contract_id") and r.get("match_status") == "matched":
            flags.append("NO_CONTRACT")
        fid = (r.get("resolved_formulary_id") or r.get("formulary_id_raw") or "-")
        if len(str(fid)) > 26:
            fid = str(fid)[:23] + "..."
        lines.append(
            f"{(r.get('submitter_gpo') or '-'):<14} "
            f"{(r.get('plan_id_raw') or '-'):<18} "
            f"{(r.get('resolved_plan_id') or '-'):<18} "
            f"{fid:<28} "
            f"{(r.get('match_status') or '-'):<12} "
            f"{(r.get('contract_id') or '-'):<40} "
            f"{','.join(flags) or '-'}"
        )
    if limit is not None and len(rows) > limit:
        lines.append(f"... ({len(rows) - limit} more rows; see mapping_report.json)")
    return "\n".join(lines)


def write_mapping_report(
    resolved_dir: Path,
    contracts_dir: Path,
    out_json: Path,
    *,
    rates_overlay: Optional[Dict[str, float]] = None,
) -> tuple[List[dict], Path]:
    rows = build_mapping_rows(resolved_dir, contracts_dir, rates_overlay=rates_overlay)
    out_json = Path(out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return rows, out_json
