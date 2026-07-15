"""Orchestrate Module 04 over Module 03 resolved submittals (Module 05-lite)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .compliance_engine import evaluate_compliance
from .compliance_schema import ComplianceResult
from .config import OUTPUT_DIR, PROJECT_ROOT
from .contract_ingest import validate_contract
from .formulary_index import FormularyIndex
from .llm import TextLLM
from .mapping_report import build_mapping_rows
from .verdict_cache import VerdictCache
from .vocabulary import MatchStatus, Verdict


def _load_contracts_by_id(contracts_dir: Path) -> dict[str, Any]:
    """Load contracts for evaluation without Module 02 formulary-id existence checks.

    Demo contracts list DEMO-{stem} join keys that are not printed on PDFs, so
    `ingest_contract_file`'s known-ID gate would drop most of the catalog.
    """
    out: dict[str, Any] = {}
    root = Path(contracts_dir)
    files = [root] if root.is_file() else sorted(root.rglob("*.json"))
    for f in files:
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            contract = validate_contract(raw, known_formulary_ids=None)
        except Exception:
            continue
        out[contract.contract_id] = contract
    return out


def run_compliance_batch(
    *,
    resolved_dir: Path | None = None,
    contracts_dir: Path | None = None,
    formulary_dir: Path | None = None,
    out_dir: Path | None = None,
    use_llm_fallback: bool = False,
    llm: TextLLM | None = None,
    model_name: str = "rules",
    product_name: str = "SYNTHROID",
) -> dict[str, Any]:
    resolved_dir = Path(resolved_dir or OUTPUT_DIR / "invoices")
    contracts_dir = Path(contracts_dir or PROJECT_ROOT / "sample_contracts")
    formulary_dir = Path(formulary_dir or OUTPUT_DIR)
    out_dir = Path(out_dir or OUTPUT_DIR / "compliance")
    out_dir.mkdir(parents=True, exist_ok=True)

    mapping = build_mapping_rows(resolved_dir, contracts_dir)
    contracts = _load_contracts_by_id(contracts_dir)
    fidx = FormularyIndex(formulary_dir)
    cache = VerdictCache(out_dir / "verdict_cache.json") if use_llm_fallback else None

    # Index resolved lines by (submitter, line_id) for claimed rates
    line_index: dict[tuple[str, str], dict] = {}
    for f in sorted(resolved_dir.glob("*_ncpdp_*.resolved.json")):
        submitter = f.stem.replace("_ncpdp_q1_2026", "").replace(".resolved", "")
        # stem like ascent_ncpdp_q1_2026.resolved → messy; use mapping_report helper pattern
        name = f.name
        submitter = name.replace("_ncpdp_q1_2026.resolved.json", "")
        data = json.loads(f.read_text(encoding="utf-8"))
        for line in data.get("lines") or []:
            line_index[(submitter, line.get("line_id") or "")] = line

    results: list[dict] = []
    summary = {
        "compliant": 0,
        "non_compliant": 0,
        "indeterminate": 0,
        "unresolved_plan": 0,
        "missing_formulary_file": 0,
        "missing_contract": 0,
        "total": 0,
        "by_review_reason": {},
    }

    for row in mapping:
        summary["total"] += 1
        submitter = row.get("submitter_gpo") or ""
        line_id = row.get("line_id") or ""
        src_line = line_index.get((submitter, line_id), {})

        if row.get("match_status") != MatchStatus.matched.value:
            summary["unresolved_plan"] += 1
            results.append(
                {
                    "submitter_gpo": submitter,
                    "line_id": line_id,
                    "plan_id": row.get("resolved_plan_id") or row.get("plan_id_raw"),
                    "formulary_id": row.get("resolved_formulary_id"),
                    "contract_id": row.get("contract_id"),
                    "verdict": "unresolved_plan",
                    "scope_gate_reason": "unresolved_plan",
                }
            )
            continue

        cid = row.get("contract_id")
        fid = row.get("resolved_formulary_id")
        if not cid or cid not in contracts:
            summary["missing_contract"] += 1
            summary["indeterminate"] += 1
            results.append(
                {
                    "submitter_gpo": submitter,
                    "line_id": line_id,
                    "plan_id": row.get("resolved_plan_id"),
                    "formulary_id": fid,
                    "contract_id": cid,
                    "verdict": Verdict.indeterminate.value,
                    "scope_gate_reason": "no_contract",
                }
            )
            continue

        formulary = fidx.load(fid)
        if formulary is None:
            summary["missing_formulary_file"] += 1
            summary["indeterminate"] += 1
            results.append(
                {
                    "submitter_gpo": submitter,
                    "line_id": line_id,
                    "plan_id": row.get("resolved_plan_id"),
                    "formulary_id": fid,
                    "contract_id": cid,
                    "verdict": Verdict.indeterminate.value,
                    "scope_gate_reason": "formulary_file_missing",
                }
            )
            continue

        claimed = src_line.get("rebate_rate_pct_claimed")
        contract = contracts[cid]

        # Module 05-lite: when Module 01 omitted payer_or_pbm, inherit the
        # contract counterparty name so the canonical-entity gate can run.
        # (Unknown printed payers still fail loud via unknown_counterparty.)
        doc = formulary.setdefault("document", {})
        if not (doc.get("payer_or_pbm") or "").strip():
            doc["payer_or_pbm"] = contract.counterparty.name

        eval_result: ComplianceResult = evaluate_compliance(
            contract,
            formulary,
            claimed_rate_by_product={product_name: claimed, product_name.upper(): claimed},
            formulary_id_override=fid,
            llm=llm,
            use_llm_fallback=use_llm_fallback,
            cache=cache,
            model_name=model_name,
            product_filter={product_name},
        )
        eval_result.plan_id = row.get("resolved_plan_id")
        eval_result.line_id = line_id
        eval_result.submitter_gpo = submitter

        # Persist per-line detail
        detail_name = f"{submitter}_{line_id}.json"
        detail_path = out_dir / "details" / detail_name
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        detail_path.write_text(eval_result.model_dump_json(indent=2) + "\n", encoding="utf-8")

        product = eval_result.product_results[0] if eval_result.product_results else None
        verdict = product.verdict.value if product else Verdict.indeterminate.value
        if not eval_result.scope_gate.passed:
            verdict = Verdict.indeterminate.value

        summary[verdict] = summary.get(verdict, 0) + 1
        for reason in (product.review_reasons if product else []) or []:
            summary["by_review_reason"][reason] = summary["by_review_reason"].get(reason, 0) + 1
        if eval_result.scope_gate.reason:
            r = eval_result.scope_gate.reason
            summary["by_review_reason"][r] = summary["by_review_reason"].get(r, 0) + 1

        failed_checks = []
        if product:
            for te in product.term_evaluations:
                for ch in te.checks:
                    if ch.result.value == "fail":
                        failed_checks.append(f"{te.term_id}:{ch.check.value}")

        results.append(
            {
                "submitter_gpo": submitter,
                "line_id": line_id,
                "plan_id": row.get("resolved_plan_id"),
                "plan_id_raw": row.get("plan_id_raw"),
                "formulary_id": fid,
                "contract_id": cid,
                "counterparty": row.get("counterparty"),
                "claimed_rate": claimed,
                "earned_rate": product.earned_rebate_rate_pct if product else None,
                "verdict": verdict,
                "scope_gate_passed": eval_result.scope_gate.passed,
                "scope_gate_reason": eval_result.scope_gate.reason,
                "interpreted_position": (
                    product.observed.interpreted_position.value
                    if product and product.observed.interpreted_position
                    else None
                ),
                "um_present": product.observed.um_present if product else [],
                "coverage_status": product.observed.coverage_status.value if product else None,
                "best_term": product.best_matching_term_id if product else None,
                "consensus": product.interpretation.consensus.value if product else None,
                "needs_human_review": product.needs_human_review if product else False,
                "review_reasons": product.review_reasons if product else [],
                "failed_checks": failed_checks,
                "detail_path": str(detail_path.relative_to(out_dir.parent.parent))
                if out_dir.parent.parent in detail_path.parents
                else str(detail_path),
                "leakage_candidate": bool(row.get("leakage_candidate")),
            }
        )

    summary_path = out_dir / "summary.json"
    results_path = out_dir / "results.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    results_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return {"summary": summary, "results": results, "out_dir": str(out_dir)}
