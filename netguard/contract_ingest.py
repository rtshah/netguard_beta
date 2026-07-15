"""Load and validate contract JSON (Module 02)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Set

from pydantic import ValidationError

from .contract_schema import Contract, IngestedContract
from .config import OUTPUT_DIR

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ContractValidationError(Exception):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def _normalize_formulary_id(fid: str | None) -> str | None:
    if not fid:
        return None
    return fid.split(",")[0].strip() or None


def load_known_formulary_ids(formulary_dir: Path | None = None) -> Set[str]:
    formulary_dir = formulary_dir or OUTPUT_DIR
    if not formulary_dir.is_dir():
        return set()
    ids: Set[str] = set()
    for jf in formulary_dir.glob("*.json"):
        try:
            data = json.loads(jf.read_text())
            fid = _normalize_formulary_id(data.get("document", {}).get("formulary_id"))
            if fid:
                ids.add(fid)
        except Exception:
            continue
    return ids


def validate_contract(data: dict, known_formulary_ids: Set[str] | None = None) -> Contract:
    errors: List[str] = []
    try:
        contract = Contract.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            errors.append(f"{loc}: {err['msg']}")
        raise ContractValidationError(errors) from e

    if contract.effective_start > contract.effective_end:
        errors.append("effective_start must be on or before effective_end")
    if contract.lookback_months not in (6, 12):
        errors.append(f"lookback_months: expected 6 or 12, got {contract.lookback_months}")
    if contract.payment_terms_days not in (30, 60, 90):
        errors.append(f"payment_terms_days: expected 30, 60, or 90, got {contract.payment_terms_days}")

    if known_formulary_ids is not None and "*" not in contract.covered_formularies:
        for fid in contract.covered_formularies:
            if fid not in known_formulary_ids:
                errors.append(
                    f"covered_formularies: no matching formulary for id {fid!r}"
                )

    if errors:
        raise ContractValidationError(errors)
    return contract


def _join_keys(contract: Contract) -> List[dict]:
    return [
        {
            "product_name": p.product_name,
            "ndc": p.ndc,
            "counterparty": contract.counterparty.name,
            "covered_formularies": contract.covered_formularies,
            "therapeutic_class": p.therapeutic_class,
            "effective_start": contract.effective_start,
            "effective_end": contract.effective_end,
        }
        for p in contract.products
    ]


def ingest_contract_file(
    path: Path,
    formulary_dir: Path | None = None,
) -> IngestedContract:
    raw = json.loads(path.read_text())
    known = load_known_formulary_ids(formulary_dir)
    contract = validate_contract(raw, known_formulary_ids=known if known else None)
    return IngestedContract(contract=contract, join_keys=_join_keys(contract))
