"""Load Module 01 formulary JSON by resolved formulary_id (printed or DEMO-stem)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .config import OUTPUT_DIR
from .contract_ingest import _normalize_formulary_id


class FormularyIndex:
    def __init__(self, formulary_dir: Path | None = None):
        self.dir = Path(formulary_dir) if formulary_dir else OUTPUT_DIR
        self._by_id: dict[str, Path] = {}
        self._by_stem: dict[str, Path] = {}
        self._build()

    def _build(self) -> None:
        if not self.dir.is_dir():
            return
        for jf in self.dir.glob("*.json"):
            if jf.name.startswith("."):
                continue
            # skip nested dirs' accidental picks — glob is flat
            self._by_stem[jf.stem] = jf
            self._by_id[f"DEMO-{jf.stem}"] = jf
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except Exception:
                continue
            fid = _normalize_formulary_id((data.get("document") or {}).get("formulary_id"))
            if fid:
                self._by_id.setdefault(fid, jf)

    def path_for(self, formulary_id: str | None) -> Optional[Path]:
        if not formulary_id:
            return None
        if formulary_id in self._by_id:
            return self._by_id[formulary_id]
        # DEMO-{stem} already indexed; also try stripping DEMO-
        if formulary_id.startswith("DEMO-"):
            stem = formulary_id[len("DEMO-") :]
            return self._by_stem.get(stem)
        return self._by_stem.get(formulary_id)

    def load(self, formulary_id: str | None) -> Optional[dict]:
        path = self.path_for(formulary_id)
        if path is None or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
