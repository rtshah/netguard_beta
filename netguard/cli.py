"""CLI: targeted formulary drug validation.

Usage:
  # Single formulary
  python -m netguard.cli sample_data/rx-esi-formulary.pdf --drugs "OZEMPIC:semaglutide"

  # All formularies in a folder (batch)
  python -m netguard.cli sample_data --drugs "SYNTHROID:levothyroxine"

Output:
  output/<pdf-stem>.json          one result file per formulary
  output/screenshots/*.png        highlighted provenance screenshots
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import List

from .config import OUTPUT_DIR, SCREENSHOT_DIR, load_config
from .drug_search import parse_drug_args
from .pipeline import extract


def _split_specs(raw: list[str]) -> list[str]:
    specs: list[str] = []
    for item in raw:
        specs.extend(s for s in item.split(",") if s.strip())
    return specs


def _clean_output() -> None:
    """Wipe prior JSON results and screenshots before each run (no caching yet)."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for p in OUTPUT_DIR.glob("*.json"):
        p.unlink()
    for p in SCREENSHOT_DIR.glob("*"):
        if p.is_file():
            p.unlink()


def _resolve_pdfs(path: Path, pattern: str) -> List[Path]:
    """A file -> [file]; a directory -> sorted PDFs matching pattern."""
    if path.is_dir():
        return sorted(p for p in path.glob(pattern) if p.is_file())
    return [path]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="NetGuard targeted formulary drug validation")
    parser.add_argument("pdf", help="A formulary PDF, or a directory to run on every PDF inside")
    parser.add_argument(
        "--drugs",
        action="append",
        required=True,
        help="Drug spec(s). 'NAME:alias1|alias2'. Repeatable and/or comma-separated.",
    )
    parser.add_argument(
        "--glob",
        default="*.pdf",
        help="Glob for directory mode (default: *.pdf)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output JSON path (single-file mode only; default: output/<pdf>.json)",
    )
    args = parser.parse_args(argv)

    root = Path(args.pdf)
    if not root.exists():
        print(f"error: path not found: {root}", file=sys.stderr)
        return 2

    pdfs = _resolve_pdfs(root, args.glob)
    if not pdfs:
        print(f"error: no PDFs found in {root} matching {args.glob}", file=sys.stderr)
        return 2

    queries = parse_drug_args(_split_specs(args.drugs))
    if not queries:
        print("error: no drugs parsed from --drugs", file=sys.stderr)
        return 2

    if args.output and len(pdfs) > 1:
        print("error: -o/--output cannot be used when running on multiple PDFs", file=sys.stderr)
        return 2

    cfg = load_config()
    _clean_output()

    print(f"Formularies: {len(pdfs)}")
    print(f"Drugs:       {', '.join(q.name for q in queries)}")
    print(f"Model:       {cfg.model}  (dpi={cfg.render_dpi})")
    print(f"Output dir:  {OUTPUT_DIR}\n")

    failures = 0
    written: list[Path] = []
    for idx, pdf_path in enumerate(pdfs, 1):
        print(f"\n[{idx}/{len(pdfs)}] {pdf_path.name}")
        print("  extracting (legend -> per-drug search + screenshot + vision)...")
        try:
            result = extract(str(pdf_path), queries, cfg)
        except Exception as e:  # noqa: BLE001 - keep the batch going
            failures += 1
            print(f"  ERROR: {e}", file=sys.stderr)
            traceback.print_exc()
            continue

        out_path = (
            Path(args.output)
            if args.output
            else OUTPUT_DIR / f"{pdf_path.stem}.json"
        )
        out_path.write_text(json.dumps(result.model_dump(), indent=2))
        written.append(out_path)
        _print_summary(result)

    print("\n" + "#" * 72)
    print(f"Done. {len(written)} succeeded, {failures} failed.")
    print(f"JSON results: {OUTPUT_DIR}")
    print(f"Screenshots:  {OUTPUT_DIR / 'screenshots'}")
    return 1 if failures and not written else 0


def _print_summary(result) -> None:
    d = result.document
    print("  " + "=" * 70)
    print(f"  PBM/Payer:  {d.payer_or_pbm}")
    print(f"  Formulary:  {d.formulary_name}  (ID: {d.formulary_id})")
    print(f"  Type:       {d.document_type}   Template: {d.template_label}")
    print(f"  Effective:  {d.effective_start} -> {d.effective_end}  (updated {d.updated_on})")
    print(f"  Legend:     {len(d.legend)} codes   Confidence: {d.extraction_confidence}")
    if d.needs_human_review:
        print(f"  REVIEW:     {'; '.join(d.review_reasons)}")
    print("  " + "-" * 70)
    for ln in result.lines:
        flag = "  [REVIEW]" if ln.needs_human_review else ""
        um = f" UM={','.join(ln.um_flags)}" if ln.um_flags else ""
        print(
            f"  * {ln.query_drug}: {ln.coverage_status} "
            f"tier={ln.tier}{um} (p{ln.page_ref}, conf={ln.extraction_confidence}){flag}"
        )
        if ln.raw_row_text:
            print(f"      row: {ln.raw_row_text[:88]}")
        if ln.needs_human_review and ln.review_reasons:
            print(f"      -> {'; '.join(ln.review_reasons)}")
    if result.exclusions:
        for ex in result.exclusions:
            print(f"  ! EXCLUDED {ex.drug_name_raw} (p{ex.page_ref})")
            if ex.preferred_alternatives:
                print(f"      alternatives: {', '.join(ex.preferred_alternatives)}")
    print("  " + "=" * 70)


if __name__ == "__main__":
    raise SystemExit(main())
