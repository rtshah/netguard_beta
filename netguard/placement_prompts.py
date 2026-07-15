"""Prompts for Module 04 LLM placement interpretation (dual-call consensus)."""

PROMPT_VERSION = "placement-interpret-v1"

SYSTEM_A = """You interpret a formulary drug row relative to rebate-contract position language.
Return structured JSON only. Do NOT decide compliant/non-compliant.
Map the row to one of: exclusive, one_of_1, one_of_2, one_of_3, preferred, non_preferred, ambiguous.
Demo rule of thumb: without competitive-set counts, prefer preferred vs non_preferred from tier band + legend;
if you cannot tell, return ambiguous rather than guessing one_of_N.
um_present must be only codes among PA, ST, QL that appear on the row."""

SYSTEM_B = """You are a second independent reader of formulary placement for rebate contracts.
Ignore any prior answer. From the row text, tier, UM flags, legend, and contract position definitions,
emit structured placement only (no verdict). Use exclusive|one_of_1|one_of_2|one_of_3|preferred|non_preferred|ambiguous.
If class competitive context is missing for one_of_N, return ambiguous. um_present ⊆ {PA, ST, QL}."""


def user_prompt(
    *,
    drug_name: str,
    tier: int | None,
    coverage_status: str,
    um_flags: list[str],
    raw_row_text: str | None,
    legend: dict[str, str],
    contract_position: str,
    contract_clause: str | None,
) -> str:
    legend_txt = json_dumps(legend) if legend else "{}"
    return (
        f"Drug: {drug_name}\n"
        f"Coverage status: {coverage_status}\n"
        f"Tier: {tier}\n"
        f"UM flags on row: {um_flags}\n"
        f"Raw row text: {raw_row_text or ''}\n"
        f"Formulary legend: {legend_txt}\n"
        f"Contract required position (context only): {contract_position}\n"
        f"Contract clause notes: {contract_clause or '(none)'}\n"
        "Interpret coverage_status, um_present, and interpreted_position."
    )


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)
