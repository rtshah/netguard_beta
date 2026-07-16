"""Tiny static server for the Module 07 UI mock.

Usage:
  python -m netguard.ui_server
  # open http://127.0.0.1:8765/
"""

from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import OUTPUT_DIR, PROJECT_ROOT


def refresh_data() -> Path:
    """Rebuild ui/data.json from the latest Module 04 compliance results."""
    results_path = OUTPUT_DIR / "compliance" / "results.json"
    summary_path = OUTPUT_DIR / "compliance" / "summary.json"
    ui_dir = PROJECT_ROOT / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)

    rows = json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else []
    summary = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.is_file()
        else {"total": len(rows)}
    )

    money: dict[tuple[str, str], dict] = {}
    inv = OUTPUT_DIR / "invoices"
    if inv.is_dir():
        for f in inv.glob("*_ncpdp_*.resolved.json"):
            submitter = f.name.replace("_ncpdp_q1_2026.resolved.json", "")
            data = json.loads(f.read_text(encoding="utf-8"))
            for line in data.get("lines") or []:
                money[(submitter, line.get("line_id") or "")] = {
                    "product": line.get("product_name"),
                    "units": line.get("utilization_units"),
                    "rebate_amount_claimed": line.get("rebate_amount_claimed"),
                    "ndc": line.get("ndc"),
                }

    enriched = []
    for r in rows:
        m = money.get((r.get("submitter_gpo") or "", r.get("line_id") or ""), {})
        enriched.append({**r, **{k: v for k, v in m.items() if v is not None}})

    out = ui_dir / "data.json"
    out.write_text(
        json.dumps({"summary": summary, "rows": enriched}, indent=2) + "\n",
        encoding="utf-8",
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve NetGuard Module 07 UI mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-refresh", action="store_true", help="Skip rebuilding data.json")
    args = parser.parse_args(argv)

    ui_dir = PROJECT_ROOT / "ui"
    if not args.no_refresh:
        path = refresh_data()
        print(f"Refreshed {path}")

    handler = partial(SimpleHTTPRequestHandler, directory=str(ui_dir))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"NetGuard UI mock → http://{args.host}:{args.port}/")
    print("Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
