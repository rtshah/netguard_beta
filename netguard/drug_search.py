"""Locate target drugs inside a formulary PDF.

Returns, per drug, the pages and row bounding boxes where the name (or a
user-supplied alias) appears, so the renderer can screenshot the right region.
Text-flow scrambling on multi-column pages does not matter here: we only need to
know *which* page/row a name lives on; the vision model reads the actual content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator, List

import fitz  # PyMuPDF
import pdfplumber

# A dotted-leader table-of-contents/index line, e.g. "OZEMPIC..........23".
_TOC_RE = re.compile(r"\.{4,}\s*\d+\s*$")
_ROW_Y_TOLERANCE = 3.0  # points; words within this vertical gap are one row

Word = dict  # keys: text, x0, top, x1, bottom
BBox = tuple[float, float, float, float]  # (x0, top, x1, bottom) in PDF points


@dataclass
class RowHit:
    page_index: int  # 0-based
    text: str  # reconstructed row text
    bbox: BBox  # full row bounding box
    score: float  # match score 0-100
    is_toc: bool
    token_bbox: BBox | None = None  # tight box around the matched drug token(s)


@dataclass
class DrugQuery:
    name: str
    aliases: List[str] = field(default_factory=list)

    @property
    def terms(self) -> List[str]:
        seen, out = set(), []
        for t in [self.name, *self.aliases]:
            t = t.strip()
            key = t.lower()
            if t and key not in seen:
                seen.add(key)
                out.append(t)
        return out


@dataclass
class DrugSearchResult:
    query: DrugQuery
    hits: List[RowHit]
    search_engine: str = "pdfplumber"  # or "pymupdf" when pdfplumber could not open


def _iter_page_words_pdfplumber(pdf_path: str) -> Iterator[tuple[int, List[Word]]]:
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            if words:
                yield i, words


def _iter_page_words_pymupdf(pdf_path: str) -> Iterator[tuple[int, List[Word]]]:
    doc = fitz.open(pdf_path)
    try:
        for i in range(doc.page_count):
            raw = doc[i].get_text("words")
            if not raw:
                continue
            words: List[Word] = [
                {"text": w[4], "x0": w[0], "top": w[1], "x1": w[2], "bottom": w[3]}
                for w in raw
            ]
            if words:
                yield i, words
    finally:
        doc.close()


def _iter_page_words(pdf_path: str) -> tuple[Iterator[tuple[int, List[Word]]], str]:
    """Yield (page_index, words) per page. pdfplumber first; PyMuPDF if that fails."""
    try:
        with pdfplumber.open(pdf_path):
            pass  # probe: pdfplumber must open before we commit to it
        return _iter_page_words_pdfplumber(pdf_path), "pdfplumber"
    except Exception:
        return _iter_page_words_pymupdf(pdf_path), "pymupdf"


def _cluster_rows(words: List[Word]) -> List[dict]:
    """Group words into visual rows by their vertical position."""
    rows: List[dict] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        placed = False
        for row in rows:
            if abs(row["top"] - w["top"]) <= _ROW_Y_TOLERANCE:
                row["words"].append(w)
                row["top"] = min(row["top"], w["top"])
                placed = True
                break
        if not placed:
            rows.append({"top": w["top"], "words": [w]})
    result = []
    for row in rows:
        ws = sorted(row["words"], key=lambda w: w["x0"])
        result.append(
            {
                "text": " ".join(w["text"] for w in ws),
                "x0": min(w["x0"] for w in ws),
                "top": min(w["top"] for w in ws),
                "x1": max(w["x1"] for w in ws),
                "bottom": max(w["bottom"] for w in ws),
                "words": ws,
            }
        )
    return result


def _term_matches(term: str, row_text: str) -> bool:
    return re.search(re.escape(term), row_text, flags=re.IGNORECASE) is not None


def _token_bbox(row_words: List[Word], terms: List[str]) -> BBox | None:
    """Tight bbox around the specific word(s) in the row that match a term."""
    matched = []
    for w in row_words:
        wt = w["text"].lower().strip(".,;:")
        for t in terms:
            tl = t.lower()
            if tl == wt or tl in wt or (len(tl) >= 5 and tl.split()[0] == wt):
                matched.append(w)
                break
    if not matched:
        return None
    return (
        min(w["x0"] for w in matched),
        min(w["top"] for w in matched),
        max(w["x1"] for w in matched),
        max(w["bottom"] for w in matched),
    )


def search_drug(pdf_path: str, query: DrugQuery) -> DrugSearchResult:
    """Search a PDF for one drug (exact match on name + aliases only)."""
    pages, engine = _iter_page_words(pdf_path)
    hits: List[RowHit] = []

    for i, words in pages:
        for row in _cluster_rows(words):
            text = row["text"]
            if not any(_term_matches(t, text) for t in query.terms):
                continue
            tok = _token_bbox(row["words"], query.terms)
            hits.append(
                RowHit(
                    i,
                    text,
                    (row["x0"], row["top"], row["x1"], row["bottom"]),
                    100.0,
                    bool(_TOC_RE.search(text)),
                    token_bbox=tok,
                )
            )

    return DrugSearchResult(query=query, hits=hits, search_engine=engine)


def rank_hits(result: DrugSearchResult, max_pages: int) -> List[RowHit]:
    """Prefer real content rows over TOC/index rows; keep top pages, de-duped."""
    ordered = sorted(result.hits, key=lambda h: (h.is_toc, -h.score))
    seen_pages: set[int] = set()
    picked: List[RowHit] = []
    for h in ordered:
        if h.page_index in seen_pages:
            continue
        seen_pages.add(h.page_index)
        picked.append(h)
        if len(picked) >= max_pages:
            break
    return picked


def parse_drug_args(specs: List[str]) -> List[DrugQuery]:
    """Parse CLI drug specs like 'OZEMPIC:semaglutide|ozempic pen'."""
    queries: List[DrugQuery] = []
    for spec in specs:
        spec = spec.strip()
        if not spec:
            continue
        if ":" in spec:
            name, alias_str = spec.split(":", 1)
            aliases = [a.strip() for a in re.split(r"[|]", alias_str) if a.strip()]
        else:
            name, aliases = spec, []
        queries.append(DrugQuery(name=name.strip(), aliases=aliases))
    return queries
