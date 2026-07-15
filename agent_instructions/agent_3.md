# NetGuard Agent Spec — Module 03: Invoice / Utilization Extraction + Roster Ingestion + Plan Resolution (v0.2)

> **Status:** v0.2. **Changed:** promoted from Module 04 → **Module 03** (built *before* validation). Build order now matches runtime order: generate/ingest invoices → resolve plan→PBM/formulary → *then* run the compliance logic.
> **Position in build order:** Module 03 — **built first of the runtime chain**. Three tied-together jobs: (A) extract the payer's rebate **submittal / NCPDP utilization** data, (B) ingest the monthly payer **roster** (Excel), and (C) resolve each submitting plan to its **governing formulary** via a fuzzy-matching engine. This module supplies the two things validation needs before it can run at all: the **invoiced rate** (so the rate check is live, not stubbed) and the **plan→formulary join** (which formulary a submitting plan is checked against). **Module 04 (validation) is built against this module's output** — nothing in validation is written until this exists.

---

## 1. What this module does (and its boundary)

**Part A — Submittal / utilization extraction.** Turn a payer's rebate submittal (summarized feed from the manufacturer's revenue management system of NCPDP summarized/scrubbed data, or a payer-custom format) into normalized invoice line items: product/NDC, plan ID, formulary ID (when present), utilization, and the rebate amount/rate being claimed.

**Part B — Roster ingestion.** Load the monthly Excel roster each submitter provides — their plans and every plan ID they use — into a standardized per-payer plan reference table, enriched with name/address for matching.

**Part C — Plan→formulary resolution.** Join each submittal line's plan to the governing formulary using a fuzzy-matching engine (standardize → match → score → threshold), ranked by rebate impact.

**In scope:** the three jobs above and their normalized outputs.

**Explicitly NOT this module:**
- Interpreting the formulary or deciding compliance (Module 04).
- Reading formulary documents (Module 01) or contracts (Module 02).
- Purchasing/integrating third-party lives/claims data (MMIT / Symphony / IQVIA) — noted as a future enrichment source for matching; not built now.

---

## 2. Domain grounding (why each part exists)

- **The two keys.** On the NCPDP/submittal, the rebate is written out by NDC and product; the two elements that link everything are **plan ID** and **formulary ID**. Workflow: product → NDC → rebate (verify vs contract) → formulary ID + plan ID.
- **Formulary ID is often missing.** The field exists but isn't required, so payers frequently omit it — you then recover the formulary via the roster / enrollment form / fuzzy match. Never assume it's present.
- **No consistent key across payers.** Every payer submits differently — different IDs, different layouts — so there is no single column to join on. This is the core reason Parts B and C exist and why extraction must be format-agnostic.
- **The roster.** Submitters send a monthly Excel roster of their plans + plan IDs; it's the anchor table you match submittal plans against, using name and address as additional signals.
- **No mandated plan identifier.** Managed markets has no government-standard plan ID (unlike DEA/HIN on the hospital/chargeback side), and third-party sources each carry their own IDs with 1-to-many / many-to-1 relationships — hence fuzzy matching, not a clean join.
- **Utilization is the "who we care about" filter.** Plans that don't submit utilization don't need validating. The submittal identifies the plans actually seeking rebate dollars — the set Module 04 should evaluate.
- **Leakage lives in the plan→formulary link.** A plan ideally maps to one formulary, but some map to two (e.g., ESI 1702 preferred @ higher rate vs 1703 one-of-two @ lower rate). When both rates differ and it's ambiguous which applies, that gap is the revenue leakage the platform exists to catch.

---

## 3. Part A — Submittal / utilization extraction

**Input formats (all must be handled):**
- Raw **NCPDP** Rx-level pharmacy-claims files.
- **Summarized rebate feeds** from the manufacturer's RMS (e.g., Model N / Validata output) — summary level, configurable.
- **Payer-custom** submittal formats — heterogeneous, no standard schema.

**DEMO DECISION (locked, flippable):** Because payer formats are heterogeneous with no standard, use **LLM-assisted, format-agnostic extraction** (same rationale as Module 01's Option A). Deterministic parsers for the well-structured cases (clean NCPDP, RMS summary) are the production optimization, deferred.

**Normalized line schema:**
```json
{
  "submittal": {
    "source_file": "string",
    "source_format": "ncpdp | rms_summary | payer_custom",
    "payer_or_pbm": "string",
    "rebate_period": { "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "cycle": "monthly | quarterly" },
    "ingested_at": "ISO-8601"
  },
  "lines": [
    {
      "line_id": "string",
      "ndc": "string | null",
      "product_name": "string",
      "dosage": "string | null",
      "plan_id_raw": "string",
      "plan_name_raw": "string | null",
      "formulary_id_raw": "string | null",
      "utilization_units": "number | null",
      "rebate_amount_claimed": "number | null",
      "rebate_rate_pct_claimed": "number | null",
      "raw_row": "string",
      "resolved_plan_id": "string | null",
      "resolved_formulary_id": "string | null",
      "match_confidence": "number | null",
      "match_status": "matched | other_bucket | unmatched"
    }
  ]
}
```
The `resolved_*` / `match_*` fields are populated by Part C. `raw_row` is provenance — required.

---

## 4. Part B — Payer roster ingestion

**Input:** monthly Excel roster per submitter (plans + all plan IDs they use; often name/address too).

**Approach (deterministic):** parse the Excel → **pre-standardize** join fields (e.g., normalize address tokens: `st`/`str`/`street`) → load into a common per-payer plan table. Maintain the standardization rules in a **reference table that grows over time**, so improving matching doesn't mean rewriting code.

**Normalized roster schema:**
```json
{
  "payer_or_pbm": "string",
  "roster_period": "YYYY-MM",
  "source_file": "string",
  "plans": [
    {
      "plan_id": "string",
      "plan_name": "string",
      "plan_name_standardized": "string",
      "address": "string | null",
      "address_standardized": "string | null",
      "formulary_id": "string | null",
      "lives": "number | null",
      "alt_ids": { "source": "id" }
    }
  ]
}
```

---

## 5. Part C — Plan→formulary resolution (fuzzy-matching engine)

For each submittal line, resolve `plan_id_raw` (+ name/address) to a roster plan, and through it to a `formulary_id`.

**Algorithm:**
1. **Rank by impact first.** Order plans by rebate dollars (high→low) and spend matching effort where it matters; low-dollar tail can wait or land in `other_bucket`.
2. **Standardize** submittal and roster join fields identically (names, addresses).
3. **Fuzzy match** on plan number + name + address using one or more string-similarity algorithms; produce a `match_confidence` 0–1.
4. **Threshold at 0.80.** ≥ 0.80 → `matched`; below → `other_bucket` (not treated as a real join), surfaced for review.
5. **1-to-many roll-up.** When a plan resolves to multiple candidates, pick the **highest-impact** one (most lives). This is the accepted industry practice — record the choice for audit.
6. **Recover missing formulary IDs.** When `formulary_id_raw` is absent, derive it from the matched roster plan (or flag for enrollment-form fallback).
7. **Flag multi-formulary plans.** If a resolved plan legitimately maps to more than one formulary with different rates → emit a `leakage_candidate` flag for Module 04/05 rather than silently picking one.

**Output:** the submittal lines enriched with `resolved_plan_id`, `resolved_formulary_id`, `match_confidence`, `match_status`, plus any `leakage_candidate` flags.

**DEMO DECISION (locked, flippable):** deterministic fuzzy engine (standardization + string similarity + threshold + impact ranking). LLM may assist only on genuinely ambiguous name matches later; the core join is deterministic and reproducible.

---

## 6. How this feeds Module 04 (runtime flow)

Build order **now equals** runtime order — this module is built and validated first, then validation is built on top of its real output (no fixtures, no stub resolver):

1. **Module 03** ingests the submittal + roster, resolves each submitting plan → formulary, and yields the invoiced rate per line.
2. Filter to plans **actually seeking rebate dollars** (have utilization) — the "only ones we care about" set.
3. For each such plan, **Module 04** validates its resolved formulary against the contract (position + UM), now also running the **rate check**: `rebate_rate_pct_claimed` vs the matched contract term's `rebate_rate_pct`.
4. `other_bucket` / `unmatched` / `leakage_candidate` lines route to human review rather than a forced verdict. **Validation is never invoked on an unresolved plan** — an unresolved line is a finding here, not a verdict there.

Because this module lands first, validation has both inputs from day one: the **plan→formulary join** (Part C) and the **claimed rate** (Part A). Neither is stubbed.

---

## 7. Demo scope & sample data

> **This is the first build step of the runtime chain — start here.** Generate the sample invoices/rebates and roster *before* any validation logic exists, so resolution can be built and eyeballed against real-shaped data. Everything downstream consumes what this produces.

The agent generates data that pairs with the existing demo formulary (Module 01) + contract (Module 02) so the full chain runs end to end:
- A **payer roster** (Excel) for the demo PBM, including the plan(s) that map to the demo formulary — with at least one plan carrying name/address variants that exercise the fuzzy match (not an exact string equality).
- One or more **submittals** (an NCPDP-style file + at least one payer-custom layout) whose lines reference those plans, some **omitting the formulary ID** so Part C has to recover it.
- At least one line that triggers the **rate check** discrepancy (claimed rate ≠ contract term rate) and, optionally, one **leakage_candidate** (plan mapping to two formularies at different rates) to show the marquee scenario.
- **Counterparty naming:** at least one contract naming the **GPO/rebate aggregator** while the formulary names the **PBM** — exercising the canonical-entity resolution (00 §4a) rather than letting raw strings accidentally match.

---

## 8. Rules the module MUST get right

- **Provenance.** `raw_row` on every submittal line; record the matched roster plan and the roll-up choice for every resolution. The match decision is auditable, not a black box.
- **Format-agnostic, fail-loud.** Heterogeneous submittals are expected; when a line can't be parsed or a required field is missing, flag it — never invent a plan ID, rate, or formulary ID.
- **Don't force low-confidence joins.** Below 0.80 is `other_bucket`, not a guess. A wrong plan→formulary match produces a wrong validation downstream.
- **Formulary ID is optional on input.** Always have the roster/enrollment-form fallback path; never assume it's submitted.
- **Surface, don't resolve, leakage.** Multi-formulary/different-rate ambiguity is flagged for Module 04/05, not silently collapsed.
- **Impact-weighted effort.** Rank by rebate dollars; match the money first.

---

## 9. Acceptance criteria (first pass)

- [ ] Extracts a clean NCPDP-style submittal and a payer-custom submittal to the same normalized line schema.
- [ ] Ingests the sample Excel roster into the standardized per-payer plan table, with name/address standardization applied.
- [ ] Resolves a submittal plan to the correct formulary via fuzzy match when names/addresses differ (not exact-equal), at ≥ 0.80 confidence, and recovers a **missing** formulary ID from the roster.
- [ ] Routes a deliberately low-similarity plan to `other_bucket` rather than mis-joining it.
- [ ] On a plan mapping to two different-rate formularies, emits a `leakage_candidate` flag rather than picking one.
- [ ] End to end with Modules 02+03: a line whose `rebate_rate_pct_claimed` differs from the contract term rate produces a rate-check discrepancy with provenance on both sides.
- [ ] Re-running identical inputs yields identical resolutions (reproducibility).

---

## 10. Decisions & deferrals

1. **Extraction architecture — RESOLVED (demo):** LLM-assisted, format-agnostic for submittals (§3); deterministic roster parse (§4); deterministic fuzzy engine (§5).
2. **Third-party enrichment (MMIT / Symphony / IQVIA lives & claims) — DEFERRED:** valuable for matching and impact ranking, but not built for the demo. Roster + submittal only for now.
3. **Enrollment-form fallback — DEFERRED (stubbed):** when the roster can't supply a missing formulary ID, real systems fall back to enrollment forms; for the demo, flag for review instead.
4. **Shared vocabulary — CARRYOVER:** plan/formulary identifiers and the rate field must use the same shared definitions Modules 02/03 rely on, so the rate check and join line up.
