"""Orchestration: parse legend/metadata once, then extract each target drug via
search -> screenshot -> vision, attaching screenshot-backed provenance.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

from . import prompts
from .config import Config, SCREENSHOT_DIR
from .drug_search import DrugQuery, rank_hits, search_drug
from .llm import VisionLLM
from .render import file_sha256, page_count, render_page
from .schema import (
    DocumentBlock,
    DocumentMetaLLM,
    DrugExtractionLLM,
    Exclusion,
    Line,
    Result,
)
from .validate import validate_document, validate_line


def _parse_legend(pdf_path: str, cfg: Config, llm: VisionLLM) -> tuple[DocumentMetaLLM, List[str]]:
    """Render the front AND back pages and extract metadata + legend.

    Legends/keys appear in front matter on some templates and in a back appendix on
    others, so we scan both ends of the document.
    """
    n = page_count(pdf_path)
    scan = min(cfg.legend_scan_pages, n)
    # First `scan` pages plus last `scan` pages, de-duplicated for short docs.
    indices = sorted(set(range(scan)) | set(range(max(0, n - scan), n)))
    warnings: List[str] = []
    images: List[str] = []
    for i in indices:
        images.append(
            render_page(pdf_path, i, SCREENSHOT_DIR, dpi=cfg.render_dpi, tag="legend")
        )
    meta = llm.parse(
        system=prompts.LEGEND_SYSTEM,
        user_text=prompts.LEGEND_USER,
        image_paths=images,
        schema=DocumentMetaLLM,
    )
    if not meta.legend:
        warnings.append("Legend not found in front-matter scan; UM codes may be unresolved.")
    return meta, warnings


def _legend_dict(meta: DocumentMetaLLM) -> dict[str, str]:
    return {e.code: e.meaning for e in meta.legend}


def _extract_drug(
    pdf_path: str,
    query: DrugQuery,
    cfg: Config,
    llm: VisionLLM,
    legend: dict[str, str],
) -> tuple[List[Line], List[Exclusion], List[str]]:
    """Search, screenshot, and vision-extract a single drug."""
    warnings: List[str] = []
    search = search_drug(pdf_path, query)
    hits = rank_hits(search, cfg.max_pages_per_drug)

    if not hits:
        # Fail loud: not-found becomes a review line, never a silent "not covered."
        line = Line(
            line_id=f"{query.name}-notfound",
            drug_name_raw=query.name,
            drug_name_normalized=query.name.lower(),
            coverage_status="unknown",
            page_ref=0,
            raw_row_text="",
            query_drug=query.name,
            needs_human_review=True,
            review_reasons=[
                "Drug not located by text search (incl. fuzzy). May be image-only, "
                "differently named, or absent. Manual review required."
            ],
            extraction_confidence=0.0,
        )
        warnings.append(f"'{query.name}': not found by search; flagged for human review.")
        return [line], [], warnings

    if search.used_fuzzy:
        warnings.append(f"'{query.name}': matched via fuzzy search; verify identity.")

    images: List[str] = []
    page_refs: List[int] = []
    for h in hits:
        img = render_page(
            pdf_path,
            h.page_index,
            SCREENSHOT_DIR,
            dpi=cfg.render_dpi,
            highlight_bbox=h.bbox,
            token_bbox=h.token_bbox,
            tag=query.name,
        )
        images.append(img)
        page_refs.append(h.page_index + 1)  # 1-based page_ref

    extraction: DrugExtractionLLM = llm.parse(
        system=prompts.DRUG_SYSTEM,
        user_text=prompts.drug_user_prompt(query.name, query.aliases, legend),
        image_paths=images,
        schema=DrugExtractionLLM,
    )

    primary_page = page_refs[0]
    primary_shot = images[0]

    if not extraction.found:
        line = Line(
            line_id=f"{query.name}-unconfirmed",
            drug_name_raw=query.name,
            drug_name_normalized=query.name.lower(),
            coverage_status="unknown",
            page_ref=primary_page,
            raw_row_text=extraction.raw_row_text or "",
            screenshot_path=primary_shot,
            query_drug=query.name,
            needs_human_review=True,
            review_reasons=[
                "Search located candidate page(s) but the vision model could not "
                "confirm the drug on the page. Manual review required."
            ],
            extraction_confidence=extraction.confidence,
        )
        return [line], [], warnings

    lines: List[Line] = []
    exclusions: List[Exclusion] = []

    line = Line(
        line_id=f"{query.name}-p{primary_page}",
        drug_name_raw=extraction.drug_name_raw or query.name,
        drug_name_normalized=extraction.drug_name_normalized,
        brand_or_generic=extraction.brand_or_generic.value,
        strength=extraction.strength,
        dosage_form=extraction.dosage_form,
        therapeutic_class=extraction.therapeutic_class,
        therapeutic_subclass=extraction.therapeutic_subclass,
        coverage_status=extraction.coverage_status.value,
        tier=extraction.tier,
        um_flags=extraction.um_flags,
        um_detail=extraction.um_detail,
        footnotes=extraction.footnotes,
        page_ref=primary_page,
        raw_row_text=extraction.raw_row_text or "",
        screenshot_path=primary_shot,
        query_drug=query.name,
        extraction_confidence=extraction.confidence,
    )
    validate_line(line, legend)
    lines.append(line)

    if extraction.is_exclusion:
        exclusions.append(
            Exclusion(
                drug_name_raw=extraction.drug_name_raw or query.name,
                preferred_alternatives=extraction.preferred_alternatives,
                effective_note=extraction.effective_note,
                page_ref=primary_page,
                screenshot_path=primary_shot,
                query_drug=query.name,
                raw_row_text=extraction.raw_row_text,
            )
        )

    if extraction.notes:
        warnings.append(f"'{query.name}': {extraction.notes}")

    return lines, exclusions, warnings


def extract(pdf_path: str, drugs: List[DrugQuery], cfg: Config) -> Result:
    llm = VisionLLM(cfg.openai_api_key, cfg.model)

    meta, warnings = _parse_legend(pdf_path, cfg, llm)
    legend = _legend_dict(meta)

    doc = DocumentBlock(
        source_file=os.path.basename(pdf_path),
        source_file_hash=file_sha256(pdf_path),
        payer_or_pbm=meta.payer_or_pbm,
        formulary_name=meta.formulary_name,
        formulary_id=meta.formulary_id,
        document_type=meta.document_type.value,
        template_label=meta.template_label,
        effective_start=meta.effective_start,
        effective_end=meta.effective_end,
        plan_year=meta.plan_year,
        updated_on=meta.updated_on,
        legend=legend,
    )
    validate_document(doc)
    if meta.notes:
        warnings.append(f"metadata: {meta.notes}")

    all_lines: List[Line] = []
    all_exclusions: List[Exclusion] = []
    for q in drugs:
        lines, exclusions, warns = _extract_drug(pdf_path, q, cfg, llm, legend)
        all_lines.extend(lines)
        all_exclusions.extend(exclusions)
        warnings.extend(warns)

    return Result(
        document=doc,
        lines=all_lines,
        exclusions=all_exclusions,
        warnings=warnings,
    )
