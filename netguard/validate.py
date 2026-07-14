"""Self-checks: confidence scoring and loud human-review flagging."""

from __future__ import annotations

from typing import List

from .schema import DocumentBlock, Line


def validate_document(doc: DocumentBlock) -> None:
    """Mutates doc: set needs_human_review/review_reasons/confidence for metadata."""
    reasons: List[str] = []
    if not doc.legend:
        reasons.append("No legend/key was parsed for this document.")
    if not doc.effective_start and not doc.effective_end:
        reasons.append("Effective window missing (load-bearing for validation).")
    if not doc.formulary_id:
        reasons.append("Formulary ID not found (needed to link invoice lines).")
    if not doc.payer_or_pbm:
        reasons.append("Payer/PBM not identified.")

    # Confidence: start high, subtract for each missing load-bearing field.
    conf = 1.0 - 0.15 * len(reasons)
    doc.extraction_confidence = round(max(0.0, min(1.0, conf)), 2)
    doc.review_reasons = reasons
    doc.needs_human_review = bool(reasons)


def validate_line(line: Line, legend: dict[str, str]) -> None:
    """Mutates line: flag UM codes missing from the legend and other issues."""
    reasons: List[str] = list(line.review_reasons)

    unknown = [f for f in line.um_flags if f and f not in legend]
    if unknown:
        reasons.append(f"UM code(s) not in document legend: {', '.join(unknown)}.")

    if line.coverage_status == "covered" and line.tier is None:
        reasons.append("Covered but no tier captured; verify tier column.")

    if line.coverage_status == "unknown":
        reasons.append("Coverage status could not be determined.")

    if not line.raw_row_text:
        reasons.append("Missing raw_row_text provenance.")

    # Fold model confidence into the review decision.
    if line.extraction_confidence < 0.6:
        reasons.append(f"Low model confidence ({line.extraction_confidence:.2f}).")

    line.review_reasons = reasons
    line.needs_human_review = line.needs_human_review or bool(reasons)
