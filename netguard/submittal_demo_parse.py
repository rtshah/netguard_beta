"""Deterministic parsers for Module 03 *generated* demo submittals (offline / CI).

Production/demo extraction path remains LLM-assisted (`submittal_extract.py`).
These parsers only understand the files written by `invoice_generate.py`.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path

from .submittal_schema import RebatePeriod, Submittal, SubmittalLine, SubmittalMeta
from .vocabulary import MatchStatus, RebateCycle, SourceFormat


def parse_demo_ncpdp(path: Path) -> Submittal:
    text = Path(path).read_text(encoding="utf-8")
    lines_raw = text.strip().splitlines()
    payer = "Express Scripts"
    start, end = "2026-01-01", "2026-03-31"
    cycle = RebateCycle.quarterly
    if lines_raw and lines_raw[0].startswith("HDR|"):
        for part in lines_raw[0].split("|")[1:]:
            if part.startswith("PAYER="):
                payer = part.split("=", 1)[1]
            elif part.startswith("PERIOD_START="):
                start = part.split("=", 1)[1]
            elif part.startswith("PERIOD_END="):
                end = part.split("=", 1)[1]
            elif part.startswith("CYCLE="):
                cycle = RebateCycle(part.split("=", 1)[1])

    data_lines = [ln for ln in lines_raw if ln and not ln.startswith("HDR|") and not ln.startswith("NDC|")]
    lines: list[SubmittalLine] = []
    for i, row in enumerate(data_lines, start=1):
        cols = row.split("|")
        if len(cols) < 10:
            continue
        fid = cols[6].strip() or None
        lines.append(
            SubmittalLine(
                line_id=f"N{i:04d}",
                ndc=cols[0] or None,
                product_name=cols[1],
                dosage=cols[2] or None,
                plan_id_raw=cols[3],
                plan_name_raw=cols[4] or None,
                address_raw=cols[5] or None,
                formulary_id_raw=fid,
                utilization_units=float(cols[7]) if cols[7] else None,
                rebate_amount_claimed=float(cols[8]) if cols[8] else None,
                rebate_rate_pct_claimed=float(cols[9]) if cols[9] else None,
                raw_row=row,
                match_status=MatchStatus.unmatched,
            )
        )
    return Submittal(
        submittal=SubmittalMeta(
            source_file=str(path),
            source_format=SourceFormat.ncpdp,
            payer_or_pbm=payer,
            rebate_period=RebatePeriod(start=start, end=end, cycle=cycle),
            ingested_at=datetime.now(timezone.utc),
        ),
        lines=lines,
    )


def parse_demo_payer_custom(path: Path) -> Submittal:
    text = Path(path).read_text(encoding="utf-8")
    # Find the CSV header row.
    match = re.search(r"^Client Plan Code,.*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"payer-custom header not found in {path}")
    csv_text = text[match.start() :]
    reader = csv.DictReader(io.StringIO(csv_text))
    lines: list[SubmittalLine] = []
    for i, row in enumerate(reader, start=1):
        raw = ",".join(row[k] or "" for k in reader.fieldnames or [])
        fid = (row.get("Formulary Code") or "").strip() or None
        ndc = (row.get("NDC11") or "").strip() or None
        lines.append(
            SubmittalLine(
                line_id=f"C{i:04d}",
                ndc=ndc,
                product_name=(row.get("Drug") or "").strip(),
                dosage=(row.get("Strength") or "").strip() or None,
                plan_id_raw=(row.get("Client Plan Code") or "").strip(),
                plan_name_raw=(row.get("Client Plan Label") or "").strip() or None,
                address_raw=(row.get("Street") or "").strip() or None,
                formulary_id_raw=fid,
                utilization_units=float(row["Units Dispensed"]) if row.get("Units Dispensed") else None,
                rebate_amount_claimed=float(row["Requested $"]) if row.get("Requested $") else None,
                rebate_rate_pct_claimed=float(row["Requested Rebate %"])
                if row.get("Requested Rebate %")
                else None,
                raw_row=raw,
                match_status=MatchStatus.unmatched,
            )
        )
    return Submittal(
        submittal=SubmittalMeta(
            source_file=str(path),
            source_format=SourceFormat.payer_custom,
            payer_or_pbm="Express Scripts",
            rebate_period=RebatePeriod(
                start="2026-01-01", end="2026-03-31", cycle=RebateCycle.quarterly
            ),
            ingested_at=datetime.now(timezone.utc),
        ),
        lines=lines,
    )


def parse_demo_submittal(path: Path) -> Submittal:
    path = Path(path)
    name = path.name.lower()
    if "ncpdp" in name or path.suffix == ".txt":
        return parse_demo_ncpdp(path)
    return parse_demo_payer_custom(path)
