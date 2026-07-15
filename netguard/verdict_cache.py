"""Cache-backed reproducibility for LLM placement interpretation (Module 04)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from .config import OUTPUT_DIR

DEFAULT_CACHE_PATH = OUTPUT_DIR / "compliance" / "verdict_cache.json"


def cache_key(
    *,
    formulary_line_hash: str,
    contract_term_hash: str,
    prompt_version: str,
    model: str,
) -> str:
    raw = "|".join([formulary_line_hash, contract_term_hash, prompt_version, model])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_payload(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class VerdictCache:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DEFAULT_CACHE_PATH
        self._data: dict[str, Any] = {}
        if self.path.is_file():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def get(self, key: str) -> Optional[dict]:
        hit = self._data.get(key)
        return dict(hit) if isinstance(hit, dict) else None

    def set(self, key: str, value: dict) -> None:
        self._data[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2) + "\n", encoding="utf-8")
