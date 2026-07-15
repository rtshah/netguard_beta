"""Deterministic name/address standardization from a growing rules table."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

RULES_PATH = Path(__file__).resolve().parent / "data" / "standardization_rules.json"

_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")


@lru_cache(maxsize=1)
def load_rules(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else RULES_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _tokenize(text: str) -> list[str]:
    cleaned = _PUNCT_RE.sub(" ", text.lower())
    return [t for t in _WS_RE.split(cleaned) if t]


def standardize_address(address: str | None, rules: dict[str, Any] | None = None) -> str | None:
    if address is None or not str(address).strip():
        return None
    rules = rules or load_rules()
    tokens = _tokenize(address)
    mapped = [rules.get("address_tokens", {}).get(t, t) for t in tokens]
    return _WS_RE.sub(" ", " ".join(mapped)).strip() or None


def standardize_name(name: str | None, rules: dict[str, Any] | None = None) -> str:
    if name is None or not str(name).strip():
        return ""
    rules = rules or load_rules()
    text = name.lower().strip()
    for phrase, replacement in rules.get("phrase_replacements", {}).items():
        text = text.replace(phrase, replacement)
    tokens = _tokenize(text)
    name_map = rules.get("name_tokens", {})
    mapped: list[str] = []
    for t in tokens:
        repl = name_map.get(t, t)
        if repl:
            mapped.append(repl)
    return _WS_RE.sub(" ", " ".join(mapped)).strip()
