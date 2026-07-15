NetGuard Agent Spec — Module 02: Contract Ingestion (v0.1)

1. What this module does (and its boundary)
Ingest a rebate contract — supplied as a JSON file with machine-readable rules — into the system's canonical internal representation, validate it, and make it available to the validation engine.
A rebate contract, reduced to its core, says: for our product, in this therapeutic class, on this payer's formulary, if we hold [position] with [these access restrictions and no worse], then the rebate owed is [rate]. Everything in the schema serves that rule shape.
DEMO DECISION (locked): Contracts arrive as JSON. The coding agent generates sample contracts that pair with the formulary(ies) being demoed. Parsing real contract PDFs/Word docs into this JSON is a separate, deferred module.
In scope: define the canonical contract schema; validate incoming contract JSON; generate demo samples.
Explicitly NOT this module:
Reading contract PDFs/Word (deferred — JSON in only).
Interpreting the formulary (that's the validation engine).
Deciding whether a rebate is owed or computing discrepancies (validation engine).
Invoice/utilization data (separate module).

2. What a rebate contract encodes (domain)
A national account manager negotiates placement with a PBM/payer. Higher position and looser access restrictions command a higher rebate. The contract nails down:
Counterparty — the PBM or health plan (Express Scripts, CVS Caremark, OptumRx, etc.).
Product(s) — the manufacturer's drug(s), each in a therapeutic class (the competitive set the position is measured within).
Rebate terms — one or more rules, each a qualifying condition (formulary position + access/UM allowances) paired with a rebate rate.
Covered formularies / plans — which formulary IDs this contract governs (join key to Module 01 output).
Effective window — term start/end.
Lookback period — how far back overpayments can be clawed back (commonly 6 or 12 months).
Payment terms — days to pay / raise issues before interest (commonly 30 / 60 / 90).

3. Canonical contract schema (JSON)
{
  "contract_id": "string",
  "contract_name": "string",
  "manufacturer": "string",
  "counterparty": {
    "name": "string",
    "entity_type": "pbm | health_plan"
  },
  "effective_start": "YYYY-MM-DD",
  "effective_end": "YYYY-MM-DD",
  "lookback_months": "int",
  "payment_terms_days": "int",
  "covered_formularies": ["formulary_id"],
  "products": [
    {
      "product_name": "string",
      "ndc": "string | null",
      "therapeutic_class": "string",
      "rebate_terms": [
        {
          "term_id": "string",
          "condition": {
            "formulary_position": "exclusive | one_of_1 | one_of_2 | one_of_3 | preferred | non_preferred",
            "prior_auth":     "allowed | not_allowed",
            "step_therapy":   "allowed | not_allowed",
            "quantity_limit": "allowed | not_allowed"
          },
          "rebate_rate_pct": "float",
          "notes": "string | null"
        }
      ]
    }
  ],
  "source": {
    "origin": "generated_sample | ingested_json",
    "ingested_at": "ISO-8601"
  }
}

Notes:
covered_formularies is the join to Module 01. ["*"] means all formularies under the counterparty.
source exists for the audit trail — every rule the validation engine fires must be traceable to a contract.

4. The rule model (how "qualifying" works)
Each product carries one or more rebate terms. A term = a condition on formulary placement + the rebate_rate_pct owed when that condition holds.
condition.formulary_position is the required position. prior_auth / step_therapy / quantity_limit express what access restrictions are permitted while still qualifying. If the actual formulary imposes a restriction the term marks not_allowed, the condition is violated.
Downstream (Module 04), the validation engine will: take Module 01's raw formulary signals → interpret them into a position + UM set → find the matching term → confirm the invoiced rate equals that term's rebate_rate_pct. Mismatch → discrepancy.
Vocabulary must line up across modules. The formulary_position enum and the UM keys here must be exactly what the validation engine expects from an interpreted Module 01 line. Keep these three vocabularies (extraction UM flags, contract UM conditions, validation position enum) defined in one shared place so they can't drift.

5. Sample-contract generation (for the demo)
The agent generates a small set of contracts that pair with the demo formulary. The set MUST include, at minimum:
One clean-pass contract — product's contracted position + access terms match the formulary placement exactly. Validation returns compliant.
One designed-discrepancy contract — constructed to trip a clean, explainable flag. Preferred pattern (mirrors the intended demo moment): contract term sets step_therapy: "not_allowed", but the demo formulary places the drug with step therapy → validation flags a UM violation. This keeps the demo discrepancy on an access-term mismatch, which does not require competitive-set analysis to detect.
Realism requirements for generated samples:
Real-sounding drug names + plausible therapeutic classes.
Counterparties from the Big 3 (Express Scripts / CVS Caremark / OptumRx).
Rebate rates in a realistic band (~15–50%).
Lookback 6 or 12 months; payment terms 30 / 60 / 90 days.
covered_formularies referencing the actual formulary ID used in the demo.

6. Ingestion behavior
Load JSON → validate against the schema → normalize into the internal model.
Fail loud: reject on missing required fields, unknown enum values, a term whose rate is absent, or a covered_formularies reference with no matching formulary. Emit a clear per-error message, never a silent default.
Preserve source for provenance.
Expose the normalized contract to Module 04 keyed for join: (product/ndc, counterparty, covered_formularies, therapeutic_class, effective_window).

7. Acceptance criteria (first pass)
[ ] Round-trips a well-formed contract JSON into the canonical model with no loss.
[ ] Rejects malformed contracts (missing rate, bad enum, dangling formulary ref) with specific errors.
[ ] Generated demo set contains ≥1 clean-pass and ≥1 designed-discrepancy contract, both referencing the demo formulary's ID.
[ ] The designed-discrepancy contract, when later run through Module 04 against the demo formulary, produces exactly the intended UM-mismatch flag.

8. Decisions & deferrals
Format — RESOLVED (demo): Contracts are JSON with machine-readable rules; agent generates samples. Contract-PDF/Word term extraction is a separate deferred module.
Position vs competitive set — OPEN: distinguishing one_of_2 vs one_of_3 requires knowing how many preferred products share the class — data the formulary alone may not give cleanly. For the demo, we sidestep this by keeping the discrepancy UM-based. Decision deferred: encode an expected competitive count in the contract, or derive it later from a therapeutic-class reference. Not needed for demo.
Rate validation — DEFERRED: confirming the invoiced rate against rebate_rate_pct needs the invoice module (Module 03). For now the contract just holds the expected rate.
