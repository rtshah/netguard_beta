"""CLI for Module 04: formulary ↔ contract compliance.

Usage:
  python -m netguard.compliance_cli evaluate --contract ... --formulary ... --claimed-rate 32.5
  python -m netguard.compliance_cli run
  python -m netguard.compliance_cli run --llm-fallback
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .compliance_engine import evaluate_compliance
from .compliance_run import run_compliance_batch
from .config import OUTPUT_DIR, PROJECT_ROOT, load_config
from .contract_ingest import validate_contract
from .llm import TextLLM
from .verdict_cache import VerdictCache


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NetGuard Module 04: compliance / qualification")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ev = sub.add_parser("evaluate", help="Evaluate one contract × formulary triple")
    ev.add_argument("--contract", required=True, help="Path to contract JSON")
    ev.add_argument("--formulary", required=True, help="Path to Module 01 formulary JSON")
    ev.add_argument("--claimed-rate", type=float, default=None)
    ev.add_argument("--product", default="SYNTHROID")
    ev.add_argument("--formulary-id", default=None, help="Override scope formulary id")
    ev.add_argument("--llm-fallback", action="store_true")
    ev.add_argument("--out", default=None)

    run = sub.add_parser("run", help="Batch-evaluate resolved invoice lines")
    run.add_argument("--resolved-dir", default=str(OUTPUT_DIR / "invoices"))
    run.add_argument("--contracts-dir", default=str(PROJECT_ROOT / "sample_contracts"))
    run.add_argument("--formulary-dir", default=str(OUTPUT_DIR))
    run.add_argument("--out", default=str(OUTPUT_DIR / "compliance"))
    run.add_argument("--llm-fallback", action="store_true")
    run.add_argument("--product", default="SYNTHROID")

    args = parser.parse_args(argv)

    if args.cmd == "evaluate":
        raw_contract = json.loads(Path(args.contract).read_text(encoding="utf-8"))
        contract = validate_contract(raw_contract, known_formulary_ids=None)
        formulary = json.loads(Path(args.formulary).read_text(encoding="utf-8"))
        llm = None
        model_name = "rules"
        cache = None
        if args.llm_fallback:
            cfg = load_config()
            llm = TextLLM(cfg.openai_api_key, cfg.model)
            model_name = cfg.model
            cache = VerdictCache(OUTPUT_DIR / "compliance" / "verdict_cache.json")
        result = evaluate_compliance(
            contract,
            formulary,
            claimed_rate_by_product={args.product: args.claimed_rate},
            formulary_id_override=args.formulary_id,
            llm=llm,
            use_llm_fallback=args.llm_fallback,
            cache=cache,
            model_name=model_name,
            product_filter={args.product},
        )
        text = result.model_dump_json(indent=2)
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
            print(f"Wrote {out}")
        else:
            print(text)
        gate = result.scope_gate
        print(
            f"scope_gate={gate.passed} reason={gate.reason} "
            f"products={len(result.product_results)} "
            f"verdicts={[p.verdict.value for p in result.product_results]}",
            flush=True,
        )
        return 0

    if args.cmd == "run":
        llm = None
        model_name = "rules"
        if args.llm_fallback:
            cfg = load_config()
            llm = TextLLM(cfg.openai_api_key, cfg.model)
            model_name = cfg.model
        payload = run_compliance_batch(
            resolved_dir=Path(args.resolved_dir),
            contracts_dir=Path(args.contracts_dir),
            formulary_dir=Path(args.formulary_dir),
            out_dir=Path(args.out),
            use_llm_fallback=args.llm_fallback,
            llm=llm,
            model_name=model_name,
            product_name=args.product,
        )
        s = payload["summary"]
        print(f"Wrote {payload['out_dir']}")
        print(
            f"total={s['total']} compliant={s['compliant']} "
            f"non_compliant={s['non_compliant']} indeterminate={s['indeterminate']} "
            f"unresolved={s['unresolved_plan']} missing_formulary={s['missing_formulary_file']}"
        )
        if s.get("by_review_reason"):
            print("review/gate reasons:", s["by_review_reason"])
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
