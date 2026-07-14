"""Render matched formulary pages to PNG screenshots for the vision model.

We render the FULL page (so column headers/legend context stay visible) and draw
a highlight box around the matched row. The saved PNG doubles as an audit
provenance artifact.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF


def _safe(name: str) -> str:
    keep = "".join(c if c.isalnum() else "_" for c in name)
    return keep.strip("_")[:40] or "drug"


def render_page(
    pdf_path: str,
    page_index: int,
    out_dir: Path,
    dpi: int = 170,
    highlight_bbox: Optional[tuple[float, float, float, float]] = None,
    token_bbox: Optional[tuple[float, float, float, float]] = None,
    tag: str = "page",
) -> str:
    """Render one page to PNG with highlighting. Returns the file path.

    Two-level highlight:
      - a FAINT full-width band over the matched row (context: which row), and
      - a BOLD tight box on the exact matched drug token (which column it sits in),
        so the model can distinguish e.g. left 'DRUG NAME' vs right 'PREFERRED
        OPTION' placement.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        if highlight_bbox is not None:
            _, top, _, bottom = highlight_bbox
            pad = 2.5
            band = fitz.Rect(0, max(0, top - pad), page.rect.width, bottom + pad)
            page.draw_rect(
                band,
                color=(1, 0.75, 0.4),
                fill=(1, 0.85, 0.4),
                fill_opacity=0.12,
                width=0.8,
            )
        if token_bbox is not None:
            x0, top, x1, bottom = token_bbox
            box = fitz.Rect(max(0, x0 - 2), max(0, top - 2), x1 + 2, bottom + 2)
            page.draw_rect(box, color=(1, 0.15, 0), width=2.2)
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        stem = f"{_safe(Path(pdf_path).stem)}__{_safe(tag)}__p{page_index + 1}"
        # Keep filenames unique but stable per (pdf, tag, page).
        digest = hashlib.md5(stem.encode()).hexdigest()[:6]
        out_path = out_dir / f"{stem}_{digest}.png"
        pix.save(out_path.as_posix())
        return out_path.as_posix()
    finally:
        doc.close()


def file_sha256(pdf_path: str) -> str:
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def page_count(pdf_path: str) -> int:
    doc = fitz.open(pdf_path)
    try:
        return doc.page_count
    finally:
        doc.close()
