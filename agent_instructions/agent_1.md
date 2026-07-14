NetGuard Agent Spec — Module 01: Formulary Extraction (v0.1)
This product is for a demo of NetGuard. NetGuard is a revenue management software pharmaceutical manufacturers can use to automate the process of formulary validation, or validating rebate invoices, contracts, and formularies. Pharmaceutical manufacturers contract with commercial PBMs in exchange for preferred access (formulary tier, placement, restrictions, etc), this software validates whether the access has been honored.
1. What this module does (and its boundary)
Turn a formulary document (Preferred Drug List / PDL/ formulary) into normalized, structured, auditable data.
A formulary is the PBM- or health-plan-published list of covered drugs and their coverage terms, issued as a versioned document (almost always PDF; sometimes DOCX/HTML/Excel), effective for a date range, and identified by a formulary ID/number that links back to invoice lines via plan_id and/or formulary_id.
In scope: parsing the formulary/PDL document itself.
Explicitly NOT this module:
Rebate invoice / NCPDP utilization extraction
Contract term extraction
Any judgment about whether a rebate is owed
Do not let the extractor reach into contract or invoice logic. It has one job: faithfully represent what the document says, with provenance.
2. Why this is hard (design drivers — do not skip)
~8+ document formats. The same national formulary is re-skinned per employer/plan; each PBM publishes multiple templates (e.g., CVS Value / Performance Basic / Standard / Advanced Control / Specialty). Parser must be format-agnostic, not template-matched to one layout.
Per-document legends. Each document defines its own symbol key (PA, ST, QL, SP, AGE, etc. There may also be composite codes. An example is PA* = PA if QL exceeded, PA** = PA if ST not met, plus plan-specific ones like DC/LD/MC/OC/SC). The same code can mean different things across documents. Parse the legend first; resolve codes against that document's key only.
Typography is semantic. Convention (varies, but here’s an example): BRAND in caps, branded generics in upper/lowercase italics, generics in lowercase italics. Make sure to preserve typography.
Effective dates vary and can be mid-year. Calendar-year (1/1–12/31) is common but not universal (4/1, 6/1, 7/1 all seen). A single document may encode split-year rules (e.g., "continuation through 6/30, excluded 7/1"). Capture the window and any embedded date-scoped rules.
Copay tier ≠ contractual position. The document shows a copay tier (1–5+). Contracts care about position (exclusive / preferred / one-of-two / one-of-three / non-preferred / excluded). Capture raw signals here; defer tier→position inference to the validation engine.

3. Target output schema (normalize every document to this)
{
  "document": {
    "source_file": "string",
    "source_file_hash": "string",
    "payer_or_pbm": "string",              // e.g. "Express Scripts", "CVS Caremark"
    "formulary_name": "string",            // e.g. "National Preferred Formulary"
    "formulary_id": "string | null",       // e.g. "1702", "8677" — links to invoice line
    "document_type": "commercial | medicare_part_d | medicaid | exchange | unknown",
    "template_label": "string | null",     // e.g. "Value", "Advanced Control"
    "effective_start": "YYYY-MM-DD | null",
    "effective_end": "YYYY-MM-DD | null",
    "plan_year": "int | null",
    "updated_on": "YYYY-MM-DD | null",
    "legend": { "CODE": "resolved meaning" }, // parsed from THIS document
    "extraction_confidence": "float 0-1",
    "needs_human_review": "bool",
    "review_reasons": ["string"]
  },
  "lines": [
    {
      "line_id": "string",
      "drug_name_raw": "string",           // exactly as printed
      "drug_name_normalized": "string",
      "brand_or_generic": "brand | branded_generic | generic | unknown", // from typography
      "strength": "string | null",
      "dosage_form": "string | null",
      "therapeutic_class": "string | null",
      "therapeutic_subclass": "string | null",
      "coverage_status": "covered | excluded | non_formulary | unknown",
      "tier": "int | null",
      "um_flags": ["PA", "ST", "QL", "SP", "AGE"],   // resolved from legend
      "um_detail": "string | null",        // e.g. "QL 60 caps / 30 days"
      "footnotes": ["string"],             // mid-year change markers, care-value flags, etc.
      "page_ref": "int",
      "raw_row_text": "string"             // REQUIRED — provenance for audit trail
    }
  ],
  "exclusions": [
    {
      "drug_name_raw": "string",
      "preferred_alternatives": ["string"],
      "effective_note": "string | null",   // e.g. "excluded for all utilizers 7/1/2026"
      "page_ref": "int"
    }
  ],
  "warnings": ["string"]                    // anything the extractor is unsure about
}

Non-negotiable: every line carries page_ref + raw_row_text. The audit trail is the product. If a line can't cite where it came from, it cannot flow downstream.

4. Extraction pipeline (what to build)
Ingest & route by file type. PDF (text-based vs scanned/image), DOCX, HTML, Excel/CSV. Route each to the right parser. Scanned PDFs → OCR path.
Layout-aware parse. Preserve columns, table structure, and typography (casing/italics). Do not flatten to plain text and lose the semantic formatting.
Parse the legend block first. Build the document-specific code → meaning map. All UM resolution downstream uses only this map.
Capture document metadata. Payer, formulary name/ID, template label, effective window (including embedded split-year rules), document type, updated-on date.
Segment the drug listing. Detect therapeutic-class / subclass headers (or alphabetical structure) and the row region.
Per-row extraction. Name (raw + normalized), strength, dosage form, tier, requirements/limits column → resolve UM codes via legend, capture parenthetical UM detail, capture footnote markers.
Classify brand/generic from typography.
Extract exclusions (may be a separate exclusion document) with preferred alternatives and any date-scoped notes.
Emit normalized JSON to the Section 3 schema, with per-line provenance.

5. Domain rules the extractor MUST get right
Legend-first, always. Never hardcode a global UM code map. Resolve per document.
Preserve provenance. page_ref + raw_row_text on every line and exclusion.
Capture, don't interpret. Record tier + on/off + UM flags. Do NOT infer "preferred / one-of-two / exclusive" here — that's the validation engine's job with the contract in hand.
Effective window is load-bearing. Wrong-period formulary = wrong validation. Capture start/end and any inline date-scoped exclusions/continuations.
Drug identity. PDLs usually carry name + strength + dosage form but no NDC (NDC lives on the invoice side). Normalize names to support later matching; flag where an NDC/RxNorm crosswalk will be needed rather than guessing.
Fail loud, not silent. If the legend can't be found, a column is ambiguous, or the effective date is missing → set needs_human_review = true with a reason. Never fabricate a tier or a code.

6. Validation & human-in-the-loop
Emit extraction_confidence and a needs_human_review flag with reasons.
Self-checks: does extracted drug count roughly match visible rows? Are all UM codes present in the legend? Is the effective window present and sane?
Design for the reviewer workflow: AI proposes, human confirms/corrects, corrections feed back (operational memory). Katherine's own phased plan was exactly this — automated parse, human verification.

