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
  drug_search.py  find name/aliases -> pages + row bboxes; TOC filter; fuzzy fallback
  render.py       PyMuPDF page -> PNG with highlighted row (provenance artifact)
  llm.py          OpenAI vision structured-output wrapper
  prompts.py      legend/metadata + per-drug extraction prompts
  pipeline.py     orchestration + provenance wiring
  validate.py     confidence + needs_human_review
  cli.py          entrypoint
```
