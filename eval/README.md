# Evaluation

## Ground truth

Manual verification labels live in `eval/ground_truth/`. Each file lists, per formulary:

- `brand_present` — is the string SYNTHROID printed?
- `expected_coverage` — `covered`, `excluded`, or `not_on_formulary`
- `expected_tier` — when known (null for list-style formularies with no tier column)
- `verification` — `text`, `text+visual`
- `notes` — including known edge cases we are not fixing yet

Current set: `synthroid.json` (99 formularies, drug = SYNTHROID).

## Compare a run

After `python -m netguard.cli sample_data --drugs SYNTHROID`:

```bash
python eval/compare_run.py
```

Writes a report to `eval/reports/latest.json` and prints mismatches.

Tool `unknown` + empty `raw_row_text` is treated as matching `not_on_formulary`.

## Updating ground truth

Edit `eval/ground_truth/synthroid.json` when you verify new cases visually or find a label was wrong.
