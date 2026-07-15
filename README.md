# NetGuard — Module 01: Formulary Drug Validation (v0.1)

Targeted extraction module for [NetGuard](agent_instructions/agent_1.md). Given a
formulary PDF and a few contracted drugs, it:

1. Parses the document's **key/structure once** — legend (this document's own code
   map) plus metadata (payer/PBM, formulary ID/name, effective window, template).
2. For each target drug: **searches** the PDF for the name + your aliases,
   **screenshots** the matching page(s) with the row highlighted, and uses an
   OpenAI **vision** model to extract that drug's coverage — resolving UM codes
   against the parsed legend only.
3. Emits normalized JSON (per spec section 3) with **screenshot-backed provenance**
   (`page_ref` + `raw_row_text` + `screenshot_path`) and loud `needs_human_review`
   flags. It never silently reports "not covered."

Scope boundary (per spec): parses the formulary only. No invoice/NCPDP extraction,
no contract terms, no rebate-owed judgment. Capture, don't interpret.

## Setup

```bash
pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env   # already present in this workspace
```

## Usage

```bash
# One formulary, one drug
python -m netguard.cli sample_data/rx-esi-formulary.pdf --drugs OZEMPIC

# One formulary, multiple drugs with brand/generic aliases (NAME:alias1|alias2)
python -m netguard.cli sample_data/rx-esi-formulary.pdf \
  --drugs "OZEMPIC:semaglutide, atorvastatin:LIPITOR, JARDIANCE:empagliflozin"

# EVERY formulary in a folder (batch): pass a directory instead of a file
python -m netguard.cli sample_data --drugs "SYNTHROID:levothyroxine"
```

Output: a per-formulary summary in the terminal, full JSON at `output/<pdf-stem>.json`
(one file per formulary), and highlighted provenance screenshots in
`output/screenshots/`.

## Evaluate against ground truth

```bash
python eval/compare_run.py
```

Labels: `eval/ground_truth/synthroid.json`. Report: `eval/reports/latest.json`.

## Module 02: Contract ingestion

Master-template SYNTHROID contracts live in [`sample_contracts/`](sample_contracts/), grouped by PBM / PBM-led GPO:

| Folder | GPO / role | Templates |
| --- | --- | --- |
| `ascent/` | Ascent (ESI) | NPF, Part D, Prime, Humana, Navitus, Kroger, Blues, Cigna, Wellcare, Kaiser, … |
| `cvs_zinc/` | Zinc (CVS) | Caremark lists, SilverScript, Aetna, CarelonRx |
| `optum_emisar/` | Emisar (Optum) | Optum lists + UHC only |
| `medimpact/` | Independent (no GPO) | MedImpact, alternative PBMs |

All contracts use **permissive compliant terms** (`non_preferred` + all UM allowed) so Module 04 can pass every formulary except known Module 01 edge cases (CVS dual-listing, `[NP]` semantics, tier bleed).

```bash
# Regenerate from output/ formulary metadata + template catalog
python -m netguard.contract_cli generate sample_contracts/ --formulary-dir output

# Validate all contracts
python -m netguard.contract_cli ingest sample_contracts/ --formulary-dir output
```

Code: `vocabulary.py`, `contract_schema.py`, `contract_ingest.py`, `contract_catalog.py`, `contract_generate.py`, `contract_cli.py`.

## Module 03: Invoice / roster / plan→formulary

Ingest payer rebate submittals + monthly Excel rosters, then fuzzy-resolve each
submitting plan to its governing formulary (and recover missing formulary IDs).

```bash
# Generate per-PBM rosters + NCPDP submittals for every formulary in output/
python -m netguard.invoice_cli generate sample_invoices/

# Full pipeline (deterministic — recommended for the scaled demo)
python -m netguard.invoice_cli run sample_invoices/ --deterministic

# Plan → formulary → PBM/GPO contract mapping table
python -m netguard.invoice_cli report
python -m netguard.invoice_cli report --flags-only    # leakage / recovered formulary only
python -m netguard.invoice_cli report --limit 0       # print all rows
```

Covers all formularies in `output/`, bucketed like `sample_contracts/`:
**ascent**, **cvs_zinc**, **optum_emisar**, **medimpact**. Ascent holds most
misc PBMs; Zinc includes CarelonRx; Emisar is Optum/UHC only; MedImpact has no
PBM-led GPO (~220-plan roster). Submittals include missing formulary IDs,
dual-formulary leakage, fuzzy plan ids, and claimed-rate mismatches.

Outputs: `output/invoices/` (per-roster JSON, resolved submittals, `summary.json`,
`rate_preview.json`).

Code: `submittal_schema.py`, `roster_schema.py`, `roster_ingest.py`,
`submittal_extract.py`, `plan_resolve.py`, `rate_preview.py`, `invoice_generate.py`,
`invoice_cli.py`.

## Module 04: Formulary ↔ contract qualification

Stateless compliance engine: given Module 03’s resolved plan→formulary join,
compare the Module 01 formulary placement to the Module 02 contract terms and
emit a verdict (`compliant` / `non_compliant` / `indeterminate`) with full audit.

Engine is **deterministic-first** (scope gate, product join, UM/coverage/rate
checks, tier→position rules). Optional `--llm-fallback` runs dual-call consensus
only when position is ambiguous. Canonical GPO↔PBM entity table lives in
`netguard/data/canonical_entities.json`.

```bash
# Batch-evaluate all resolved invoice lines (after Module 03 run)
python -m netguard.compliance_cli run

# One triple (designed ST fail fixture)
python -m netguard.compliance_cli evaluate \
  --contract tests/fixtures/compliance/contract_st_fail.json \
  --formulary tests/fixtures/compliance/formulary_st.json \
  --formulary-id FIXTURE-ESI-ST \
  --claimed-rate 32.5

# Optional LLM fallback when tier→position is ambiguous
python -m netguard.compliance_cli run --llm-fallback

# Unit tests (acceptance cases from agent_4 §6)
python -m pytest tests/test_compliance_engine.py -v
```

Outputs: `output/compliance/results.json`, `summary.json`, per-line
`details/*.json`. Designed ST discrepancy contract:
`sample_contracts/ascent/st-not-allowed-demo.json` (evaluate against
`output/086_ExpressScriptsMedicare_PDP.json`).

Code: `entities.py`, `compliance_schema.py`, `compliance_engine.py`,
`placement_rules.py`, `placement_llm.py`, `verdict_cache.py`,
`formulary_index.py`, `compliance_run.py`, `compliance_cli.py`.

## Configuration (env vars)

| Var | Default | Meaning |
| --- | --- | --- |
| `OPENAI_API_KEY` | – | required |
| `NETGUARD_MODEL` | `gpt-4o` | vision-capable model |
| `NETGUARD_RENDER_DPI` | `170` | screenshot resolution |
| `NETGUARD_LEGEND_PAGES` | `6` | front pages scanned for legend/metadata |
| `NETGUARD_MAX_PAGES_PER_DRUG` | `4` | cap on candidate pages sent per drug |

## How it works

```
netguard/
  config.py       env/.env, model + render settings
  schema.py       Pydantic models (LLM structured-output + final section-3 result)
  drug_search.py  find name/aliases -> pages + row bboxes (pdfplumber, PyMuPDF fallback)
  render.py       PyMuPDF page -> PNG with highlighted row (provenance artifact)
  llm.py          OpenAI vision structured-output wrapper
  prompts.py      legend/metadata + per-drug extraction prompts
  pipeline.py     orchestration + provenance wiring
  validate.py     confidence + needs_human_review
  cli.py          entrypoint
```
