"""Prompts for LLM-assisted submittal / utilization extraction."""

SYSTEM = """You extract rebate submittal / utilization invoice lines into a strict schema.

Rules:
- Never invent plan IDs, formulary IDs, NDCs, rates, or dollar amounts. If a field is absent, leave it null.
- Always copy the original row text into raw_row for provenance.
- Heterogeneous payer formats are expected (NCPDP-style, RMS summary, or payer-custom).
- Infer source_format as one of: ncpdp, rms_summary, payer_custom.
- Dates must be YYYY-MM-DD. Rates are percentages (e.g. 32.5 means 32.5%).
- Prefer product_name as written; include dosage when present.
- If address / street appears for a plan, put it in address_raw.
"""


def user_prompt(source_file: str, content: str) -> str:
    return (
        f"Source file: {source_file}\n\n"
        "Extract every utilization / rebate line from the file contents below.\n"
        "Return payer_or_pbm, rebate period, source_format, and lines.\n\n"
        "----- FILE CONTENTS -----\n"
        f"{content}\n"
        "----- END -----\n"
    )
