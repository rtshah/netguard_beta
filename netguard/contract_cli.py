"""CLI for Module 02: load and validate contract JSON.

Usage:
  python -m netguard.contract_cli generate sample_contracts/ --formulary-dir output
  python -m netguard.contract_cli ingest sample_contracts/ --formulary-dir output
  python -m netguard.contract_cli validate sample_contracts/optum_emisar/comprehensive-medicare.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import OUTPUT_DIR
from .contract_generate import coverage_report, generate_contracts
from .contract_ingest import ContractValidationError, ingest_contract_file, load_known_formulary_ids, validate_contract


def _contract_files(root: Path) -> list[Path]:
    if root.is_dir():
        return sorted(root.rglob("*.json"))
    return [root]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NetGuard Module 02: contract ingestion")
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="Generate master-template contract JSON files")
    gen.add_argument("path", help="Output directory (e.g. sample_contracts/)")
    gen.add_argument("--formulary-dir", default=str(OUTPUT_DIR))

    ing = sub.add_parser("ingest", help="Validate contract JSON (directory tree)")
    ing.add_argument("path")
    ing.add_argument("--formulary-dir", default=str(OUTPUT_DIR))

    val = sub.add_parser("validate", help="Validate one contract file")
    val.add_argument("path")
    val.add_argument("--formulary-dir", default=str(OUTPUT_DIR))

    args = parser.parse_args(argv)
    fdir = Path(args.formulary_dir)

    if args.cmd == "generate":
        out_dir = Path(args.path)
        written = generate_contracts(out_dir, fdir)
        report = coverage_report(fdir)
        print(f"Generated {len(written)} contracts in {out_dir}")
        print(
            f"Formulary coverage: {report['mapped_count']}/{report['formulary_count']} mapped"
        )
        if report["unmapped_stems"]:
            print("Unmapped formularies:")
            for stem in report["unmapped_stems"]:
                print(f"  - {stem}")
        return 0

    if args.cmd == "validate":
        raw = json.loads(Path(args.path).read_text())
        known = load_known_formulary_ids(fdir)
        try:
            c = validate_contract(raw, known_formulary_ids=known if known else None)
        except ContractValidationError as e:
            for err in e.errors:
                print(f"  - {err}")
            return 1
        print(f"VALID: {c.contract_id}")
        return 0

    files = _contract_files(Path(args.path))
    ok, fail = 0, 0
    for f in files:
        try:
            result = ingest_contract_file(f, formulary_dir=fdir)
            ok += 1
            c = result.contract
            print(f"OK  {c.contract_id}  formularies={c.covered_formularies}")
        except ContractValidationError as e:
            fail += 1
            print(f"FAIL {f.relative_to(args.path) if Path(args.path).is_dir() else f.name}")
            for err in e.errors:
                print(f"  - {err}")
    print(f"Ingested {ok}, failed {fail}")
    return 1 if fail and not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
