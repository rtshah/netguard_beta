# NetGuard Agent Spec — Module 07: UI / Control & Reporting Surface (v0.1)

> **Status:** first draft, for iteration.
> **Position in build order:** Module 07, last. A view-and-control layer over Modules 01–06 — it does no processing itself. The agents are **headless** and run in the manufacturer's environment; this UI is the human-in-the-loop control surface (review, confirm, override, dispute) and the reporting surface (analytics, audit). Also serves as the demonstration surface for how the extraction/validation logic works.

---

## 1. What this module is (and its boundary)

The UI renders the outputs of the pipeline and captures human decisions back into it:
- **Validation queue** — the main dashboard: what's compliant / non-compliant / needs-review, ranked for action.
- **Open disputes** — the Module 06 tracker.
- **Analytics dashboards** — operational and financial reporting over time.
- **Audit log / agent trace** — the immutable decision record.

**In scope:** presentation, navigation, and the human actions (confirm, dispute, override, resolve, export).

**Explicitly NOT this module:**
- Any extraction, validation, matching, drafting, or detection logic (Modules 01–06). The UI calls them; it doesn't reimplement them.
- The headless agent runtime — the UI is optional to the engine's operation, not required for it.

**Cross-cutting principles (apply to every view):**
- **Exception-first, impact-ranked.** Default to what needs a human, sorted by dollars at stake. Never dump thousands of rows.
- **Confidence everywhere.** Every verdict shows its confidence score.
- **Manual override everywhere** — and every override is a logged decision with a captured reason.
- **Everything cross-links** — a dispute ↔ its originating line + evidence ↔ its audit entries.

---

## 2. The data grain (why the hierarchy is what it is)

The rebate triangle: the manufacturer's contract is with the **PBM**; each **plan** separately contracts with the PBM; plans submit utilization (NCPDP w/ plan ID + formulary ID); the PBM aggregates and invoices the manufacturer. So **payment rolls up to the PBM**, but **compliance is decided per plan × per drug**.

The UI hierarchy follows this: **PBM → Plan → Drug line**, where the drug line (one plan × one drug) is the atomic actionable unit — identical to Module 05's discrepancy grain. Money aggregates upward; decisions happen at the leaf.

Scale drives the design: one formulary can link to thousands of plan IDs; a big-3 payer can mean ~1,500 plans across multiple products. Hence exception-first ranking, rollups, and bulk actions are requirements, not niceties.

---

## 3. View 1 — Validation Queue (main dashboard)

**Top: money-view summary bar.** Total rebates claimed this cycle, split into $ payable (compliant), $ at risk (non-compliant / disputable), $ under review, and estimated recovery. The at-a-glance exposure number.

**Body: exception-first, impact-ranked drill-down.**
- Grouped **PBM → Plan → Drug line**, defaulting to items needing a decision (non-compliant + needs-review), sorted by dollar impact. Compliant/payable items roll up into the summary and are reachable but not cluttering the queue.
- **PBM row:** total claimed, compliant/non-compliant/needs-review split, $ at risk, counts.
- **Plan row:** per-plan status rollup across its drugs, $ claimed, $ at risk.
- **Drug line (leaf):** the atomic verdict — status, dollar delta, confidence — click to open the detail panel.

**Detail panel (per drug line):**
- Verdict + **confidence score**.
- **Agent trace / reasoning** — the timestamped, expandable decision trail.
- **Citations** — the exact contract clause (Module 02), formulary placement with page + raw row (Module 01), and invoice/utilization line (Module 03). This is Module 05's lineage, rendered.
- **Actions:**
  - **Confirm** (human-in-the-loop). If compliant → clears from the queue as payable. If non-compliant → **Next → auto-draft dispute** (Module 06), citing the sources.
  - **Manual override** — change the verdict/mapping; prompts for a reason; logged.

**Bulk actions.** Confirm/clear compliant, high-confidence lines in bulk (e.g., "confirm all compliant ≥ 95% confidence") — each confirm still written to the audit log.

**Needs-review sub-states — each with a resolution surface (not a dead end):**
- **Low confidence** (below the review threshold) → analyst reviews and confirms/overrides.
- **Missing formulary** (no formulary available for the plan) → upload/attach the formulary inline, or mark unavailable.
- **Unresolved plan mapping** (Module 03 match < 0.80 / other-bucket) → show the fuzzy-match candidates and let the human pick the correct plan→formulary mapping.

---

## 4. View 2 — Open Disputes

A view over the Module 06 tracker.

- Lists everything sent to dispute: payer/PBM, plan, drug, dollar amount, status, days open, payment-term deadline.
- **Track / edit / remove / manually log** disputes.
- **Filter** by dollars, days outstanding, status, payer, product.
- **Aging & backlog** surfaced so nothing ages past tight payment terms.
- **Export PDF** — the dispute evidence packet (message + contract clause + formulary copy/page + discrepancy + dollar delta), i.e., the "formal email with a copy of the formulary" made concrete.
- Each dispute **links back** to its originating drug line + evidence (View 1) and its audit entries (View 4).

---

## 5. View 3 — Analytics Dashboards

Operational + financial reporting for business users and executives (distinct from the raw agent trace).

**Throughput & errors:** validation requests processed per day; discrepancies/errors found; compliance rate.

**Time-series (month-over-month / quarter-over-quarter):** errors, $ recovered, $ disputed, and leakage plotted over cycles — the trend view a manager uses to see whether things are improving or degrading.

**Resubmission / reversal / back-bill tracking:** because the same (plan, product, period) recurs across cycles, a **claim-history / version-chain view** — original → reversal → resubmission → back-bill — showing the amount and the verdict at each step, so a claim's evolution is visible rather than just its latest snapshot. Plus a per-cycle count of reversals/resubmissions/back-bills (a spike in back-bills for an old period is itself a flag).

**Errors by plan:** which plans generate the most discrepancies (repeat-offender detection → feeds contract intelligence).

**Basic anomaly / fraud analytics:** flag abnormal movement in a plan's or product's rebate/utilization over time — both large single-cycle jumps ($1M→$5M) and **gradual creep** ($1M→$1.5M→$2M) that line-by-line review misses. Threshold-based to start.

---

## 6. View 4 — Audit Log / Agent Trace

The global, immutable, append-only decision record (Module 06 Part C), as opposed to the per-line trace in View 1.

- Every validation and dispute action, timestamped, with expandable full reasoning.
- **Includes override events** (who, when, why) — a human decision is still a logged decision.
- Searchable/filterable by PBM, plan, drug, date, action type.
- This is the SOX artifact — turning a reconciliation blind spot into a defensible, complete trail.

---

## 7. Demo scope

Walk the full loop on the demo data: money-view bar up top → drill PBM → plan → the step-therapy drug line flagged non-compliant → open the detail panel (verdict, confidence, agent trace, citations to contract clause + formulary page + invoice line) → confirm error → auto-draft dispute → send (mock) → it appears in Open Disputes (dated, days-open, exportable to PDF) → Analytics shows a month-over-month recovery view + one anomaly flag → Audit Log shows the full timestamped trail including the confirm action. Show one needs-review item (missing formulary or unresolved mapping) resolving via its surface.

---

## 8. Decisions & deferrals

1. **UI is a thin control/reporting surface — RESOLVED:** no processing logic in the UI; it renders Modules 01–06 and captures human decisions. Engine is headless; UI is optional to runtime.
2. **Anomaly analytics depth — SIMPLIFIED (demo):** threshold-based; richer fraud/trend modeling is a roadmap item.
3. **Contract-intelligence view — DEFERRED (roadmap):** surfacing recurring error-source clauses ("contract grays") to account managers is a natural next view; not built for the demo.
4. **Read/write contract:** the UI's writes (confirm, override, resolve, dispute) must route through the modules that own that state so nothing is mutated only in the UI layer.

---

## Running agent spec — module checklist

- [x] 00 — Overview, mental model & glossary
- [x] 01 — Formulary extraction
- [x] 02 — Contract ingestion
- [x] 03 — Invoice/utilization extraction + roster ingestion + plan resolution
- [x] 04 — Validation / compliance engine (formulary ↔ contract ↔ invoice)
- [x] 05 — Discrepancy detection & leakage surfacing
- [x] 06 — Dispute drafting, tracking & audit / operational memory
- [x] **07 — UI / control & reporting surface** (this doc)

**Backbone complete.** Eight docs covering the end-to-end, in build == runtime order: extract formularies → ingest contracts → **generate/ingest invoices & rosters + resolve plan→PBM/formulary** → validate (position, UM, rate) → detect discrepancies & quantify leakage → draft/track disputes & log decisions → human control & reporting surface.