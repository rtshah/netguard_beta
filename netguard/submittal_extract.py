"""LLM-assisted format-agnostic submittal extraction (Module 03 Part A)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .config import load_config
from .llm import TextLLM
from .submittal_prompts import SYSTEM, user_prompt
from .submittal_schema import (
    LLMExtractedSubmittal,
    RebatePeriod,
    Submittal,
    SubmittalLine,
    SubmittalMeta,
)
from .vocabulary import MatchStatus, SourceFormat


class SubmittalExtractError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _read_source(path: Path) -> str:
    path = Path(path)
    if not path.is_file():
        raise SubmittalExtractError([f"not a file: {path}"])
    # Cap payload size for LLM context.
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > 120_000:
        text = text[:120_000] + "\n...[truncated]..."
    return text


def extract_submittal(
    path: Path,
    *,
    llm: TextLLM | None = None,
    source_format_hint: SourceFormat | None = None,
) -> Submittal:
    path = Path(path)
    content = _read_source(path)
    if llm is None:
        cfg = load_config()
        llm = TextLLM(cfg.openai_api_key, cfg.model)

    parsed = llm.parse(SYSTEM, user_prompt(str(path), content), LLMExtractedSubmittal)
    errors: list[str] = []
    if not parsed.lines:
        errors.append("no lines extracted")
    lines: list[SubmittalLine] = []
    for i, raw in enumerate(parsed.lines, start=1):
        if not (raw.plan_id_raw or "").strip():
            errors.append(f"line {i}: missing plan_id_raw — refusing to invent")
            continue
        if not (raw.product_name or "").strip():
            errors.append(f"line {i}: missing product_name")
            continue
        if not (raw.raw_row or "").strip():
            errors.append(f"line {i}: missing raw_row provenance")
            continue
        lines.append(
            SubmittalLine(
                line_id=raw.line_id or f"L{i:04d}",
                ndc=raw.ndc,
                product_name=raw.product_name.strip(),
                dosage=raw.dosage,
                plan_id_raw=raw.plan_id_raw.strip(),
                plan_name_raw=raw.plan_name_raw,
                address_raw=raw.address_raw,
                formulary_id_raw=raw.formulary_id_raw,
                utilization_units=raw.utilization_units,
                rebate_amount_claimed=raw.rebate_amount_claimed,
                rebate_rate_pct_claimed=raw.rebate_rate_pct_claimed,
                raw_row=raw.raw_row,
                match_status=MatchStatus.unmatched,
            )
        )

    if errors and not lines:
        raise SubmittalExtractError(errors)

    fmt = source_format_hint or parsed.source_format
    meta = SubmittalMeta(
        source_file=str(path),
        source_format=fmt,
        payer_or_pbm=parsed.payer_or_pbm,
        rebate_period=RebatePeriod(
            start=parsed.rebate_period_start,
            end=parsed.rebate_period_end,
            cycle=parsed.rebate_cycle,
        ),
        ingested_at=datetime.now(timezone.utc),
    )
    result = Submittal(submittal=meta, lines=lines)
    if errors:
        # Fail-loud flags attached via exception only when nothing usable;
        # partial success returns lines and surfaces warnings on stderr by caller.
        result.submittal.source_file = str(path)
        # Stash warnings on a private attribute for CLI (not in schema dump).
        object.__setattr__(result, "_warnings", errors)  # type: ignore[attr-defined]
    return result


def load_submittal_json(path: Path) -> Submittal:
    import json

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return Submittal.model_validate(data)
