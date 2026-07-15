"""CLI for Module 03: roster ingest, submittal extract, plan resolve, rate preview.

Usage:
  python -m netguard.invoice_cli generate sample_invoices/
  python -m netguard.invoice_cli run sample_invoices/ --deterministic
  python -m netguard.invoice_cli report
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import OUTPUT_DIR, PROJECT_ROOT, load_config
from .invoice_generate import SAMPLE_INVOICES_DIR, generate_demo_invoices
from .mapping_report import format_mapping_table, write_mapping_report
from .plan_resolve import contract_rates_from_dir, resolve_submittal
from .roster_ingest import RosterIngestError, ingest_roster_excel
from .roster_schema import Roster, RosterPlan
from .submittal_demo_parse import parse_demo_submittal
from .submittal_extract import SubmittalExtractError, extract_submittal, load_submittal_json
from .vocabulary import SourceFormat


def _dump(model, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _load_rates_overlay(path: Path | None) -> dict[str, float]:
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): float(v) for k, v in data.items()}


def _merge_rosters(rosters: list[Roster]) -> Roster:
    plans: list[RosterPlan] = []
    for r in rosters:
        plans.extend(r.plans)
    payer = "ALL" if len(rosters) != 1 else rosters[0].payer_or_pbm
    period = rosters[0].roster_period if rosters else ""
    return Roster(
        payer_or_pbm=payer,
        roster_period=period,
        source_file=";".join(r.source_file for r in rosters),
        plans=plans,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NetGuard Module 03: invoices / roster / resolve")
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="Generate demo rosters + NCPDP submittals from output/")
    gen.add_argument("path", nargs="?", default=str(SAMPLE_INVOICES_DIR))
    gen.add_argument("--formulary-dir", default=str(OUTPUT_DIR))

    ing = sub.add_parser("ingest-roster", help="Ingest Excel roster → JSON")
    ing.add_argument("path")
    ing.add_argument("--out", default=None)
    ing.add_argument("--payer", default=None)
    ing.add_argument("--period", default=None)

    ext = sub.add_parser("extract", help="Extract a submittal file → JSON")
    ext.add_argument("path")
    ext.add_argument("--out", default=None)
    ext.add_argument(
        "--format",
        choices=[e.value for e in SourceFormat],
        default=None,
    )
    ext.add_argument(
        "--deterministic",
        action="store_true",
        help="Parse generated demo NCPDP/CSV without LLM",
    )

    res = sub.add_parser("resolve", help="Fuzzy-resolve submittal lines against roster")
    res.add_argument("--submittal", required=True)
    res.add_argument("--roster", required=True, help="Roster JSON (or directory of roster JSONs)")
    res.add_argument("--out", default=None)
    res.add_argument("--rates-overlay", default=None)
    res.add_argument("--contracts", default=None)

    run = sub.add_parser("run", help="Full demo pipeline on sample_invoices/")
    run.add_argument("path", nargs="?", default=str(SAMPLE_INVOICES_DIR))
    run.add_argument(
        "--contracts",
        default=str(PROJECT_ROOT / "sample_contracts"),
    )
    run.add_argument("--out-dir", default=str(OUTPUT_DIR / "invoices"))
    run.add_argument("--skip-generate", action="store_true")
    run.add_argument(
        "--deterministic",
        action="store_true",
        help="Use demo parsers instead of LLM (recommended for scaled demo)",
    )

    rep = sub.add_parser(
        "report",
        help="Print plan → formulary → PBM/GPO contract mapping from resolved outputs",
    )
    rep.add_argument(
        "--resolved-dir",
        default=str(OUTPUT_DIR / "invoices"),
        help="Directory with *_ncpdp_*.resolved.json",
    )
    rep.add_argument(
        "--contracts",
        default=str(PROJECT_ROOT / "sample_contracts"),
    )
    rep.add_argument(
        "--rates-overlay",
        default=str(SAMPLE_INVOICES_DIR / "meta" / "contract_rates_overlay.json"),
    )
    rep.add_argument("--out", default=None, help="Write full JSON mapping (default: <resolved-dir>/mapping_report.json)")
    rep.add_argument("--limit", type=int, default=40, help="Max table rows to print (0 = all)")
    rep.add_argument(
        "--flags-only",
        action="store_true",
        help="Only print leakage / recovered-formulary rows",
    )

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        written = generate_demo_invoices(Path(args.path), formulary_dir=Path(args.formulary_dir))
        print(f"Wrote {len(written)} files under {args.path}")
        for p in written:
            print(f"  {p}")
        return 0

    if args.cmd == "ingest-roster":
        try:
            roster = ingest_roster_excel(
                Path(args.path), payer_or_pbm=args.payer, roster_period=args.period
            )
        except RosterIngestError as e:
            for err in e.errors:
                print(f"  - {err}")
            return 1
        out = Path(args.out) if args.out else Path(args.path).with_suffix(".json")
        _dump(roster, out)
        print(f"OK  roster plans={len(roster.plans)} → {out}")
        return 0

    if args.cmd == "extract":
        hint = SourceFormat(args.format) if args.format else None
        try:
            if args.deterministic:
                submittal = parse_demo_submittal(Path(args.path))
            else:
                load_config()
                submittal = extract_submittal(Path(args.path), source_format_hint=hint)
        except (SubmittalExtractError, ValueError) as e:
            errs = getattr(e, "errors", None) or [str(e)]
            for err in errs:
                print(f"  - {err}")
            return 1
        out = Path(args.out) if args.out else Path(args.path).with_suffix(".extracted.json")
        _dump(submittal, out)
        print(f"OK  lines={len(submittal.lines)} format={submittal.submittal.source_format} → {out}")
        return 0

    if args.cmd == "resolve":
        submittal = load_submittal_json(Path(args.submittal))
        roster_path = Path(args.roster)
        if roster_path.is_dir():
            rosters = [
                Roster.model_validate(json.loads(p.read_text()))
                for p in sorted(roster_path.glob("*.json"))
            ]
            roster = _merge_rosters(rosters)
        else:
            roster = Roster.model_validate(json.loads(roster_path.read_text()))
        rates = _load_rates_overlay(Path(args.rates_overlay) if args.rates_overlay else None)
        if args.contracts:
            for k, v in contract_rates_from_dir(args.contracts).items():
                rates.setdefault(k, v)
        resolved = resolve_submittal(submittal, roster, contract_rates_by_formulary=rates or None)
        out = Path(args.out) if args.out else Path(args.submittal).with_suffix(".resolved.json")
        _dump(resolved, out)
        matched = sum(1 for ln in resolved.lines if ln.match_status.value == "matched")
        other = sum(1 for ln in resolved.lines if ln.match_status.value == "other_bucket")
        leak = sum(1 for ln in resolved.lines if ln.leakage_candidate)
        print(f"OK  matched={matched} other_bucket={other} leakage={leak} → {out}")
        return 0

    if args.cmd == "report":
        resolved_dir = Path(args.resolved_dir)
        out_json = Path(args.out) if args.out else resolved_dir / "mapping_report.json"
        rows, path = write_mapping_report(
            resolved_dir,
            Path(args.contracts),
            out_json,
        )
        view = rows
        if args.flags_only:
            view = [
                r
                for r in rows
                if r.get("leakage_candidate") or r.get("recovered_formulary")
            ]
        limit = None if args.limit == 0 else args.limit
        print(format_mapping_table(view, limit=limit))
        print()
        no_contract = sum(
            1 for r in rows if r.get("match_status") == "matched" and not r.get("contract_id")
        )
        print(
            f"{len(rows)} lines | "
            f"matched={sum(1 for r in rows if r.get('match_status')=='matched')} "
            f"leak={sum(1 for r in rows if r.get('leakage_candidate'))} "
            f"recovered_fid={sum(1 for r in rows if r.get('recovered_formulary'))} "
            f"no_contract={no_contract}"
        )
        print(f"Full JSON → {path}")
        return 0

    if args.cmd != "run":
        parser.error(f"unknown command {args.cmd}")
        return 2

    # run — full pipeline across all generated rosters + NCPDP files
    root = Path(args.path)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_generate:
        generate_demo_invoices(root)

    roster_files = sorted((root / "roster").glob("*.xlsx"))
    if not roster_files:
        print("No roster Excel files found. Run generate first.")
        return 1

    rosters: list[Roster] = []
    for rf in roster_files:
        try:
            r = ingest_roster_excel(rf)
        except RosterIngestError as e:
            print(f"FAIL roster {rf.name}")
            for err in e.errors:
                print(f"  - {err}")
            return 1
        out_r = out_dir / "rosters" / f"{rf.stem}.json"
        _dump(r, out_r)
        rosters.append(r)
        print(f"Roster {rf.name}: {len(r.plans)} plans → {out_r}")

    merged = _merge_rosters(rosters)
    _dump(merged, out_dir / "roster_all.json")
    print(f"Merged roster: {len(merged.plans)} plan rows")

    rates = _load_rates_overlay(root / "meta" / "contract_rates_overlay.json")
    for k, v in contract_rates_from_dir(args.contracts).items():
        rates.setdefault(k, v)

    if not args.deterministic:
        load_config()

    submittal_files = sorted((root / "submittals").glob("*_ncpdp_*.txt"))
    if not submittal_files:
        submittal_files = sorted((root / "submittals").glob("*.txt"))

    totals = {"matched": 0, "other_bucket": 0, "leakage": 0, "lines": 0}

    for src in submittal_files:
        mode = "deterministic" if args.deterministic else "llm"
        print(f"Extracting {src.name} ({mode}) ...")
        try:
            if args.deterministic:
                submittal = parse_demo_submittal(src)
            else:
                submittal = extract_submittal(src, source_format_hint=SourceFormat.ncpdp)
        except (SubmittalExtractError, ValueError) as e:
            print(f"FAIL extract {src.name}")
            errs = getattr(e, "errors", None) or [str(e)]
            for err in errs:
                print(f"  - {err}")
            return 1

        _dump(submittal, out_dir / f"{src.stem}.extracted.json")
        resolved = resolve_submittal(submittal, merged, contract_rates_by_formulary=rates or None)
        _dump(resolved, out_dir / f"{src.stem}.resolved.json")

        matched = sum(1 for ln in resolved.lines if ln.match_status.value == "matched")
        other = sum(1 for ln in resolved.lines if ln.match_status.value == "other_bucket")
        leak = sum(1 for ln in resolved.lines if ln.leakage_candidate)
        totals["matched"] += matched
        totals["other_bucket"] += other
        totals["leakage"] += leak
        totals["lines"] += len(resolved.lines)
        print(f"  resolve matched={matched} other_bucket={other} leakage={leak}")

    summary = dict(totals)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        f"TOTAL lines={totals['lines']} matched={totals['matched']} "
        f"other_bucket={totals['other_bucket']} leakage={totals['leakage']}"
    )
    print(f"Summary → {out_dir / 'summary.json'}")

    rows, map_path = write_mapping_report(
        out_dir, Path(args.contracts), out_dir / "mapping_report.json"
    )
    print()
    print("=== Plan → Formulary → Contract ===")
    print(format_mapping_table(rows, limit=25))
    no_contract = sum(
        1 for r in rows if r.get("match_status") == "matched" and not r.get("contract_id")
    )
    print(
        f"Full mapping → {map_path}  ({len(rows)} lines, "
        f"leak={sum(1 for r in rows if r.get('leakage_candidate'))}, "
        f"no_contract={no_contract})"
    )
    print("Re-print anytime:  python -m netguard.invoice_cli report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
