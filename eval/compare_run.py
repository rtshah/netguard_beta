#!/usr/bin/env python3
"""Compare a NetGuard run against saved ground truth.

Usage:
  python eval/compare_run.py
  python eval/compare_run.py --output-dir output --truth eval/ground_truth/synthroid.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _tool_coverage(line: dict | None) -> str:
    if line is None:
        return "missing"
    status = line.get("coverage_status", "unknown")
    if status == "unknown" and line.get("needs_human_review"):
        raw = (line.get("raw_row_text") or "").strip()
        if not raw:
            return "not_on_formulary"
    return status


def _match_coverage(expected: str, actual: str) -> bool:
    if expected == "not_on_formulary":
        return actual in ("not_on_formulary", "unknown", "missing")
    return expected == actual


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare tool output vs ground truth")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--truth", default="eval/ground_truth/synthroid.json")
    parser.add_argument("--save-report", default="eval/reports/latest.json")
    args = parser.parse_args()

    truth_path = PROJECT_ROOT / args.truth
    output_dir = PROJECT_ROOT / args.output_dir
    report_path = PROJECT_ROOT / args.save_report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    truth = json.loads(truth_path.read_text())
    entries = truth["entries"]

    results = []
    ok = fail = skip = crash = 0

    for entry in entries:
        fname = entry["file"]
        stem = Path(fname).stem
        jf = output_dir / f"{stem}.json"

        row = {
            "file": fname,
            "expected_coverage": entry["expected_coverage"],
            "expected_tier": entry.get("expected_tier"),
            "brand_present": entry["brand_present"],
            "notes": entry.get("notes", ""),
            "actual_coverage": "crash",
            "actual_tier": None,
            "confidence": None,
            "match": False,
        }

        if not jf.exists():
            crash += 1
            row["actual_coverage"] = "crash"
            results.append(row)
            continue

        data = json.loads(jf.read_text())
        lines = data.get("lines", [])
        line = lines[0] if lines else None
        actual = _tool_coverage(line)
        row["actual_coverage"] = actual
        row["actual_tier"] = line.get("tier") if line else None
        row["confidence"] = line.get("extraction_confidence") if line else None

        cov_ok = _match_coverage(entry["expected_coverage"], actual)
        tier_ok = True
        if entry.get("expected_tier") is not None and actual == "covered":
            tier_ok = row["actual_tier"] == entry["expected_tier"]

        row["match"] = cov_ok and tier_ok
        if row["match"]:
            ok += 1
        else:
            fail += 1
        results.append(row)

    report = {
        "drug": truth.get("drug"),
        "total": len(entries),
        "matched": ok,
        "mismatched": fail,
        "crashed": crash,
        "coverage_accuracy": round(ok / len(entries), 3) if entries else 0,
        "results": results,
    }
    report_path.write_text(json.dumps(report, indent=2))

    print(f"Ground truth: {truth_path}")
    print(f"Output dir:   {output_dir}")
    print(f"Report:       {report_path}")
    print("-" * 72)
    print(f"Matched:    {ok}/{len(entries)}")
    print(f"Mismatched: {fail}")
    print(f"Crashed:    {crash} (no JSON output)")
    print("-" * 72)
    print("Mismatches:")
    for r in results:
        if r["match"]:
            continue
        exp_t = f" t{r['expected_tier']}" if r["expected_tier"] is not None else ""
        act_t = f" t{r['actual_tier']}" if r["actual_tier"] is not None else ""
        print(
            f"  {r['file']:<44} expected={r['expected_coverage']}{exp_t} "
            f"got={r['actual_coverage']}{act_t} conf={r['confidence']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
