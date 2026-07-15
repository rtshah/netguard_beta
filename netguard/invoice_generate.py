"""Generate scaled demo rosters + NCPDP submittals from Module 01 output/.

Buckets match sample_contracts/ PBM / PBM-led GPO folders:
  ascent/ | cvs_zinc/ | optum_emisar/ | medimpact/

Every formulary in output/ maps to one of those (unclear → Ascent).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from openpyxl import Workbook

from .config import OUTPUT_DIR, PROJECT_ROOT
from .contract_catalog import MASTER_TEMPLATES
from .contract_ingest import _normalize_formulary_id

SAMPLE_INVOICES_DIR = PROJECT_ROOT / "sample_invoices"
SAMPLE_CONTRACTS_DIR = PROJECT_ROOT / "sample_contracts"
NDC_SYNTHROID = "00074-3727-90"
ROSTER_PERIOD = "2026-03"
PERIOD_START = "2026-01-01"
PERIOD_END = "2026-03-31"
# Real submitters send fat monthly rosters; only a fraction submit utilization.
# MedImpact is an independent PBM (no PBM-led GPO) — smaller roster.
ROSTER_TARGET_SIZE: Dict[str, int] = {
    "ascent": 1000,
    "cvs_zinc": 1000,
    "optum_emisar": 1000,
    "medimpact": 220,
}

_DUMMY_EMPLOYERS = [
    "Acme Manufacturing",
    "Northstar Logistics",
    "Summit Regional Medical",
    "Lakeside School District",
    "Prairie Employers Trust",
    "Cascade Municipal",
    "Ironwood Industries",
    "Harborview Clinic Group",
    "Metro Transit Authority",
    "Sunrise Retail Partners",
    "Valley Credit Union",
    "Pioneer Energy Co",
    "Cedar Ridge Hospital",
    "Atlantic Packaging",
    "Heartland Foods",
    "Pacific Coast Shipping",
    "Redwood Community College",
    "Great Lakes Auto Parts",
    "Southern Tier Benefits",
    "Midwest Steelworkers Fund",
]
_DUMMY_PRODUCTS = [
    "PPO",
    "HMO",
    "HDHP",
    "POS",
    "EPO",
    "Select",
    "Plus",
    "Choice",
    "Open Access",
    "National",
]

# Four buckets aligned to sample_contracts/ and PBM-led GPOs
# (EVERSANA: Ascent / Zinc / Emisar; MedImpact declined GPO membership).
# submitter_key → (display name on roster/NCPDP HDR, filename slug)
SUBMITTER_META: Dict[str, Tuple[str, str]] = {
    "ascent": ("Ascent", "ascent"),
    "cvs_zinc": ("CVS_Zinc", "cvs_zinc"),
    "optum_emisar": ("Optum_Emisar", "optum_emisar"),
    "medimpact": ("MedImpact", "medimpact"),
}


@dataclass
class FormularyPlan:
    stem: str
    submitter_key: str
    payer_display: str
    plan_id: str
    plan_name: str
    address: str
    formulary_id: str
    lives: int
    contract_rate_pct: float
    contract_id: str
    template_key: str
    printed_formulary_id: Optional[str]
    is_dummy: bool = False


@dataclass
class DemoWorld:
    plans: List[FormularyPlan] = field(default_factory=list)
    # plan_id → list of FormularyPlan (dual-formulary plans share an id)
    by_plan_id: Dict[str, List[FormularyPlan]] = field(default_factory=dict)


def _stem_to_template() -> dict:
    out = {}
    for t in MASTER_TEMPLATES:
        for s in t.stems:
            out[s] = t
    return out


def _submitter_key(tmpl) -> str:
    """Map a catalog template to a PBM / PBM-led GPO bucket.

    Per EVERSANA (PBM-led GPOs):
      ascent/        — Ascent (ESI): Prime, Navitus, Humana, Kroger, misc PBMs/plans
      cvs_zinc/      — Zinc (CVS): Caremark + CarelonRx (sole external) + SilverScript/Aetna
      optum_emisar/  — Emisar (Optum): Optum/UHC only — no non-United external members
      medimpact/     — independent PBM; declined PBM-led GPO membership (no GPO)
    """
    key = tmpl.key
    folder = tmpl.folder

    # --- Zinc (CVS Caremark GPO) ---
    if folder in ("caremark", "cvs", "cvs_zinc") or key in (
        "silverscript-medicare",
        "aetna-standard",
        "carelonrx",
    ):
        return "cvs_zinc"

    # --- Emisar (OptumRx GPO): Optum + United only ---
    if folder in ("optum", "optum_emisar") or key == "unitedhealthcare":
        # Wellcare / Kaiser are external → Ascent misc, not Emisar.
        if key in ("wellcare-medicare", "kaiser-permanente"):
            return "ascent"
        return "optum_emisar"

    # --- MedImpact (no PBM-led GPO) ---
    if folder == "medimpact" or key in ("medimpact", "alternative-pbm") or "medimpact" in key:
        return "medimpact"

    # --- Ascent (ESI GPO): Prime, Humana, Navitus, Kroger, Envolve, Blues, Cigna, … ---
    return "ascent"


def _pretty_plan_name(stem: str, formulary_name: Optional[str], payer: Optional[str]) -> str:
    if formulary_name and formulary_name.strip():
        # Keep it short for roster readability
        name = formulary_name.strip()
        if len(name) > 72:
            name = name[:69] + "..."
        return name
    # Derive from stem: 003_TRS_ActiveCare_ExpressScripts → TRS ActiveCare
    body = re.sub(r"^\d+_", "", stem)
    body = body.replace("_", " ")
    for noise in (
        " ExpressScripts",
        " CVSCaremark",
        " Optum",
        " MedImpact",
        " Formulary",
        " DrugList",
        " PDP",
        " MAPD",
    ):
        body = body.replace(noise, "")
    return body.strip() or stem


def _address_for(stem: str, idx: int) -> str:
    """Deterministic fake addresses; some use St/Ave abbreviations for fuzzy demos."""
    cities = [
        ("100 Main Street", "Austin", "TX", "78701"),
        ("200 Market Avenue", "Washington", "DC", "20001"),
        ("500 Commerce Boulevard", "Saint Louis", "MO", "63101"),
        ("12 Oak Road", "Chicago", "IL", "60601"),
        ("88 Pine Drive", "Boston", "MA", "02108"),
        ("440 Harbor Way", "Seattle", "WA", "98101"),
        ("15 Peachtree Street", "Atlanta", "GA", "30303"),
        ("900 Mission Street", "San Francisco", "CA", "94103"),
        ("300 Broad Street", "Philadelphia", "PA", "19102"),
        ("77 Lakeshore Drive", "Detroit", "MI", "48226"),
    ]
    street, city, st, zipc = cities[idx % len(cities)]
    # Alternate abbreviations on every 3rd row so fuzzy address matching gets exercise.
    if idx % 3 == 0:
        street = (
            street.replace("Street", "St")
            .replace("Avenue", "Ave")
            .replace("Boulevard", "Blvd")
            .replace("Road", "Rd")
            .replace("Drive", "Dr")
        )
        if city == "Saint Louis":
            city = "St Louis"
    return f"{street}, {city}, {st} {zipc}"


def _join_formulary_id(stem: str, printed: Optional[str]) -> str:
    """Stable join key: prefer printed ID, else synthetic DEMO id from stem."""
    norm = _normalize_formulary_id(printed)
    if norm:
        return norm
    return f"DEMO-{stem}"


def _plan_id_for(submitter_key: str, stem: str, seq: int) -> str:
    prefix = {
        "ascent": "ESI",
        "cvs_zinc": "CVS",
        "optum_emisar": "OPT",
        "medimpact": "MED",
    }.get(submitter_key, "PLN")
    return f"{prefix}-{seq:04d}"


def build_demo_world(formulary_dir: Path | None = None) -> DemoWorld:
    formulary_dir = Path(formulary_dir) if formulary_dir else OUTPUT_DIR
    stem_map = _stem_to_template()
    # Fallback template for unmapped stems → Ascent NPF rates
    ascent_fallback = next(t for t in MASTER_TEMPLATES if t.key == "ascent-national-preferred")

    plans: List[FormularyPlan] = []
    seq_by_submitter: Dict[str, int] = {k: 1 for k in SUBMITTER_META}

    files = sorted(formulary_dir.glob("*.json"))
    for jf in files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        doc = data.get("document") or {}
        stem = jf.stem
        tmpl = stem_map.get(stem, ascent_fallback)
        sk = _submitter_key(tmpl) if stem in stem_map else "ascent"
        payer_name, _ = SUBMITTER_META[sk]
        seq = seq_by_submitter[sk]
        seq_by_submitter[sk] = seq + 1
        printed = doc.get("formulary_id")
        fid = _join_formulary_id(stem, printed if isinstance(printed, str) else None)
        plans.append(
            FormularyPlan(
                stem=stem,
                submitter_key=sk,
                payer_display=payer_name,
                plan_id=_plan_id_for(sk, stem, seq),
                plan_name=_pretty_plan_name(stem, doc.get("formulary_name"), doc.get("payer_or_pbm")),
                address=_address_for(stem, seq),
                formulary_id=fid,
                lives=5000 + (seq * 1370) % 90000,
                contract_rate_pct=float(tmpl.rebate_rate_pct),
                contract_id=tmpl.contract_id,
                template_key=tmpl.key,
                printed_formulary_id=_normalize_formulary_id(printed)
                if isinstance(printed, str)
                else None,
            )
        )

    world = DemoWorld(plans=plans)
    for p in plans:
        world.by_plan_id.setdefault(p.plan_id, []).append(p)
    return world


def _pick_dual_pairs(world: DemoWorld) -> List[Tuple[FormularyPlan, FormularyPlan]]:
    """Create dual-formulary pairs within each of the four PBM buckets.

    Prefer different contract rates so the lower-rate routing demo is visible.
    Ascent (largest) gets two pairs; others get one each.
    """
    by_sub: Dict[str, List[FormularyPlan]] = {}
    for p in world.plans:
        by_sub.setdefault(p.submitter_key, []).append(p)

    pairs: List[Tuple[FormularyPlan, FormularyPlan]] = []
    for sk in ("ascent", "cvs_zinc", "optum_emisar", "medimpact"):
        plist = by_sub.get(sk, [])
        if len(plist) < 2:
            continue
        plist_sorted = sorted(plist, key=lambda x: (x.contract_rate_pct, x.stem))
        n_pairs = 2 if sk == "ascent" and len(plist_sorted) >= 4 else 1
        used: set[str] = set()
        for _ in range(n_pairs):
            remaining = [p for p in plist_sorted if p.stem not in used]
            if len(remaining) < 2:
                break
            low, high = remaining[0], remaining[-1]
            if low.formulary_id == high.formulary_id:
                break
            pairs.append((low, high))
            used.add(low.stem)
            used.add(high.stem)
    return pairs


def _apply_dual_plan_ids(world: DemoWorld, pairs: List[Tuple[FormularyPlan, FormularyPlan]]) -> None:
    """Give each dual pair a shared plan_id (roster lists the plan twice)."""
    for i, (a, b) in enumerate(pairs, start=1):
        dual_id = f"{a.plan_id[:3]}-DUAL-{i:02d}"
        a.plan_id = dual_id
        b.plan_id = dual_id
        # Ensure lives differ so audit is interesting; lower-rate row gets fewer lives
        # so we prove we pick by rate, not lives.
        if a.contract_rate_pct <= b.contract_rate_pct:
            a.lives = 25000
            b.lives = 80000
        else:
            a.lives = 80000
            b.lives = 25000
    world.by_plan_id = {}
    for p in world.plans:
        world.by_plan_id.setdefault(p.plan_id, []).append(p)


def _pad_dummy_plans(
    world: DemoWorld,
    target_sizes: Dict[str, int] | None = None,
) -> None:
    """Pad each PBM roster to its target size with non-submitting dummy plans.

    Dummies appear on the monthly Excel roster only — they do not submit utilization,
    matching the discovery point that most roster plans never show up on the invoice.
    """
    targets = target_sizes or ROSTER_TARGET_SIZE
    by_sub: Dict[str, List[FormularyPlan]] = {}
    for p in world.plans:
        by_sub.setdefault(p.submitter_key, []).append(p)

    for sk, existing in by_sub.items():
        payer_name, _ = SUBMITTER_META[sk]
        target = targets.get(sk, 1000)
        need = max(0, target - len(existing))
        start_seq = 10_000
        for i in range(need):
            seq = start_seq + i
            emp = _DUMMY_EMPLOYERS[i % len(_DUMMY_EMPLOYERS)]
            prod = _DUMMY_PRODUCTS[(i * 3) % len(_DUMMY_PRODUCTS)]
            region = ["East", "West", "Central", "South", "Midwest"][i % 5]
            plan_name = f"{emp} {region} {prod}"
            anchor = existing[i % len(existing)]
            world.plans.append(
                FormularyPlan(
                    stem=f"DUMMY-{sk}-{i:04d}",
                    submitter_key=sk,
                    payer_display=payer_name,
                    plan_id=_plan_id_for(sk, f"dummy-{i}", seq),
                    plan_name=plan_name,
                    address=_address_for(f"dummy-{i}", seq),
                    formulary_id=anchor.formulary_id,
                    lives=200 + (i * 97) % 15000,
                    contract_rate_pct=anchor.contract_rate_pct,
                    contract_id=anchor.contract_id,
                    template_key=anchor.template_key,
                    printed_formulary_id=None,
                    is_dummy=True,
                )
            )

    world.by_plan_id = {}
    for p in world.plans:
        world.by_plan_id.setdefault(p.plan_id, []).append(p)


def _write_roster(path: Path, submitter_key: str, plans: List[FormularyPlan]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payer_name, _ = SUBMITTER_META[submitter_key]
    wb = Workbook()
    ws = wb.active
    ws.title = f"{payer_name}|{ROSTER_PERIOD}"[:31]
    ws.append(["plan_id", "plan_name", "address", "formulary_id", "lives", "alt_id", "stem"])
    # Deduplicate rows but keep dual plan_id rows (same id, different formulary).
    seen = set()
    for p in sorted(plans, key=lambda x: (x.plan_id, x.formulary_id)):
        key = (p.plan_id, p.formulary_id)
        if key in seen:
            continue
        seen.add(key)
        ws.append(
            [
                p.plan_id,
                p.plan_name,
                p.address,
                p.formulary_id,
                p.lives,
                p.stem.split("_")[0] if "_" in p.stem else p.stem[:6],
                p.stem,
            ]
        )
    wb.save(path)
    return path


def _messy_plan_id(plan_id: str, kind: str) -> str:
    if kind == "fuzzy_suffix":
        return plan_id + "X"
    if kind == "fuzzy_underscore":
        return plan_id.replace("-", "_", 1)
    return plan_id


def _messy_name(name: str, kind: str) -> str:
    if kind == "abbrev":
        return (
            name.replace("Health", "Hlth")
            .replace("National", "Natl")
            .replace("Formulary", "Form.")
            .replace("Preferred", "Pref")
        )
    if kind == "space":
        return re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return name


def _messy_address(address: str) -> str:
    return (
        address.replace("Street", "St")
        .replace("Avenue", "Ave")
        .replace("Boulevard", "Blvd")
        .replace("Road", "Rd")
        .replace("Drive", "Dr")
        .replace("Saint ", "St ")
    )


def _write_ncpdp(
    path: Path,
    submitter_key: str,
    plans: List[FormularyPlan],
    dual_ids: set[str],
) -> Path:
    """One utilization line per unique real plan_id (dummies never submit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payer_name, _ = SUBMITTER_META[submitter_key]
    header = (
        f"HDR|PAYER={payer_name}|PERIOD_START={PERIOD_START}|PERIOD_END={PERIOD_END}|CYCLE=quarterly\n"
        "NDC|PRODUCT|DOSAGE|PLAN_ID|PLAN_NAME|PLAN_ADDRESS|FORMULARY_ID|UTIL_UNITS|REBATE_AMT|REBATE_RATE_PCT\n"
    )

    # Unique plan_ids among real (non-dummy) plans only — utilization filter.
    ordered: List[FormularyPlan] = []
    seen_ids = set()
    for p in plans:
        if p.is_dummy:
            continue
        if p.plan_id in seen_ids:
            continue
        seen_ids.add(p.plan_id)
        ordered.append(p)

    lines: List[str] = []
    for i, p in enumerate(ordered):
        util = 800 + (i * 173) % 20000
        # Default: claim the contract rate.
        claimed = p.contract_rate_pct
        formulary_field = p.formulary_id
        plan_id_out = p.plan_id
        name_out = p.plan_name
        addr_out = p.address
        dosage = ["50 mcg", "75 mcg", "100 mcg", "112 mcg", "125 mcg"][i % 5]

        # --- join mess only (no rate games, no unmatched junk — add those later) ---
        if p.plan_id in dual_ids:
            # Dual formulary: omit id or list both; resolve recovers + flags leakage.
            siblings = [x for x in plans if x.plan_id == p.plan_id and not x.is_dummy]
            fids = [x.formulary_id for x in siblings]
            formulary_field = "" if i % 2 == 0 else ";".join(fids)
            claimed = p.contract_rate_pct
        elif i % 5 == 0:
            # Missing formulary ID — recover from roster via fuzzy plan/name/address.
            formulary_field = ""
            plan_id_out = _messy_plan_id(p.plan_id, "fuzzy_suffix")
            name_out = _messy_name(p.plan_name, "abbrev")
            addr_out = _messy_address(p.address)
        elif i % 7 == 0:
            formulary_field = ""
            plan_id_out = _messy_plan_id(p.plan_id, "fuzzy_underscore")
            name_out = _messy_name(p.plan_name, "space")
        # else: clean line with formulary present

        amt = round(util * claimed * 0.1, 2)
        lines.append(
            f"{NDC_SYNTHROID}|SYNTHROID|{dosage}|{plan_id_out}|{name_out}|"
            f"{addr_out}|{formulary_field}|{util}|{amt:.2f}|{claimed}"
        )

    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def _sync_formulary_ids_onto_contracts(
    world: DemoWorld,
    contracts_dir: Path | None = None,
) -> int:
    """Ensure every real plan's formulary_id is listed on its PBM/GPO contract."""
    contracts_dir = Path(contracts_dir) if contracts_dir else SAMPLE_CONTRACTS_DIR
    by_contract: Dict[str, set[str]] = {}
    for p in world.plans:
        if p.is_dummy:
            continue
        by_contract.setdefault(p.contract_id, set()).add(p.formulary_id)

    updated = 0
    for path in sorted(contracts_dir.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        cid = data.get("contract_id")
        if not cid or cid not in by_contract:
            continue
        covered = [x for x in (data.get("covered_formularies") or []) if x and x != "*"]
        merged = sorted(set(covered) | by_contract[cid])
        if merged != data.get("covered_formularies"):
            data["covered_formularies"] = merged
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            updated += 1
    return updated


def _clear_generated(out_dir: Path) -> None:
    """Remove prior roster/submittal/meta artifacts so old PBM buckets disappear."""
    for sub in ("roster", "submittals", "meta"):
        d = out_dir / sub
        d.mkdir(parents=True, exist_ok=True)
        for f in d.iterdir():
            if f.is_file():
                f.unlink()


def generate_demo_invoices(
    out_dir: Path | None = None,
    formulary_dir: Path | None = None,
) -> List[Path]:
    out_dir = Path(out_dir) if out_dir else SAMPLE_INVOICES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    _clear_generated(out_dir)

    world = build_demo_world(formulary_dir)
    pairs = _pick_dual_pairs(world)
    _apply_dual_plan_ids(world, pairs)
    dual_ids = {a.plan_id for a, _ in pairs}
    real_count = len(world.plans)
    n_synced = _sync_formulary_ids_onto_contracts(world, SAMPLE_CONTRACTS_DIR)
    _pad_dummy_plans(world, ROSTER_TARGET_SIZE)

    written: List[Path] = []
    by_sub: Dict[str, List[FormularyPlan]] = {}
    for p in world.plans:
        by_sub.setdefault(p.submitter_key, []).append(p)

    unexpected = set(by_sub) - set(SUBMITTER_META)
    if unexpected:
        raise RuntimeError(f"unexpected submitter buckets: {unexpected}")

    rates: Dict[str, float] = {}
    for p in world.plans:
        if not p.is_dummy:
            rates[p.formulary_id] = p.contract_rate_pct

    for sk in ("ascent", "cvs_zinc", "optum_emisar", "medimpact"):
        plans = by_sub.get(sk, [])
        if not plans:
            continue
        _, slug = SUBMITTER_META[sk]
        roster_path = _write_roster(out_dir / "roster" / f"{slug}_{ROSTER_PERIOD}.xlsx", sk, plans)
        ncpdp_path = _write_ncpdp(
            out_dir / "submittals" / f"{slug}_ncpdp_q1_2026.txt", sk, plans, dual_ids
        )
        written.extend([roster_path, ncpdp_path])

    rates_path = out_dir / "meta" / "contract_rates_overlay.json"
    rates_path.write_text(json.dumps(rates, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(rates_path)

    submitter_counts = {}
    for sk in SUBMITTER_META:
        plans = by_sub.get(sk, [])
        submitter_counts[sk] = {
            "roster_rows": len(plans),
            "real": sum(1 for p in plans if not p.is_dummy),
            "dummy": sum(1 for p in plans if p.is_dummy),
            "submitting_plan_ids": len({p.plan_id for p in plans if not p.is_dummy}),
        }

    index = {
        "roster_period": ROSTER_PERIOD,
        "roster_target_size": ROSTER_TARGET_SIZE,
        "real_formulary_plans": real_count,
        "total_roster_rows": len(world.plans),
        "submitter_counts": submitter_counts,
        "sample_contracts_folders": sorted(SUBMITTER_META.keys()),
        "dual_formulary_plan_ids": sorted(dual_ids),
        "dual_pairs": [
            {
                "plan_id": a.plan_id,
                "formularies": [
                    {
                        "formulary_id": a.formulary_id,
                        "rate": a.contract_rate_pct,
                        "lives": a.lives,
                        "stem": a.stem,
                    },
                    {
                        "formulary_id": b.formulary_id,
                        "rate": b.contract_rate_pct,
                        "lives": b.lives,
                        "stem": b.stem,
                    },
                ],
            }
            for a, b in pairs
        ],
        "contracts_updated": n_synced,
        "note": (
            "PBM-led GPOs (EVERSANA): Ascent (ESI+Prime/Humana/Navitus/misc), "
            "CVS_Zinc (Caremark+CarelonRx), Optum_Emisar (Optum/UHC only), "
            "MedImpact (independent — no PBM-led GPO). "
            "Every real formulary_id is listed on its contract covered_formularies. "
            "Rosters padded with dummy non-submitters; NCPDP = utilization filter only "
            "(no other_bucket junk / no rate-mismatch lines in this pass)."
        ),
    }
    index_path = out_dir / "meta" / "demo_index.json"
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    written.append(index_path)

    readme = out_dir / "README.md"
    counts = ", ".join(
        f"{sk}={submitter_counts[sk]['roster_rows']} "
        f"({submitter_counts[sk]['real']} real / {submitter_counts[sk]['dummy']} dummy)"
        for sk in SUBMITTER_META
    )
    readme.write_text(
        "# Module 03 demo invoices\n\n"
        "PBM-led GPOs ([EVERSANA](https://www.eversana.com/insights/peeking-behind-the-pbm-led-gpo-curtain/)):\n\n"
        f"- Rosters: {counts}\n"
        f"- Only **{real_count} real** formulary-linked plans submit on NCPDP "
        "(dummies pad the roster)\n"
        "- **Ascent** — ESI GPO; Prime, Humana, Navitus, Kroger, Blues, Cigna, misc\n"
        "- **CVS_Zinc** — Zinc GPO; Caremark + CarelonRx (+ SilverScript/Aetna)\n"
        "- **Optum_Emisar** — Emisar GPO; Optum/UHC only (no non-United externals)\n"
        "- **MedImpact** — independent PBM, no PBM-led GPO (~220-plan roster)\n\n"
        "```bash\npython -m netguard.invoice_cli generate sample_invoices/\n"
        "python -m netguard.invoice_cli run sample_invoices/ --deterministic\n```\n",
        encoding="utf-8",
    )
    written.append(readme)
    return written
