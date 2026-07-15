"""Canonical counterparty / PBM / GPO entity resolution (Modules 02–04)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).resolve().parent / "data" / "canonical_entities.json"

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


class UnknownCounterparty(Exception):
    """Loud failure when a counterparty string is not in the reference table."""

    def __init__(self, raw: str):
        self.raw = raw
        super().__init__(f"unknown_counterparty: {raw!r}")


def _norm(s: str) -> str:
    return _NORMALIZE_RE.sub(" ", (s or "").strip().lower()).strip()


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    index: dict[str, str] = {}
    for ent in data.get("entities") or []:
        cid = ent["canonical_id"]
        names = [ent.get("pbm_name"), ent.get("gpo_name"), *(ent.get("aliases") or [])]
        for name in names:
            if not name:
                continue
            key = _norm(name)
            if key and key not in index:
                index[key] = cid
    return index


def clear_entity_cache() -> None:
    _alias_index.cache_clear()


# Submitter GPO folder → default payer string when formulary metadata omitted it.
SUBMITTER_DEFAULT_PAYER: dict[str, str] = {
    "ascent": "Ascent",
    "cvs_zinc": "Zinc",
    "optum_emisar": "Emisar",
    "medimpact": "MedImpact",
}


def resolve_counterparty(name: str | None) -> str:
    """Map a raw GPO/PBM/alias string to a canonical_id. Raises UnknownCounterparty."""
    if name is None or not str(name).strip():
        raise UnknownCounterparty(str(name))
    cid = _alias_index().get(_norm(name))
    if cid is None:
        raise UnknownCounterparty(str(name).strip())
    return cid


def try_resolve_counterparty(name: str | None) -> Optional[str]:
    try:
        return resolve_counterparty(name)
    except UnknownCounterparty:
        return None


def entity_table_version() -> str:
    data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return str(data.get("version") or "unknown")
