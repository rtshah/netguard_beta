"""Module 04 compliance engine — stateless evaluator (agent_4 §3)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .compliance_schema import (
    CheckRecord,
    ComplianceResult,
    DateWindow,
    InterpretationBlock,
    InterpretationReading,
    MatchedFormularyLine,
    ObservedPlacement,
    ProductResult,
    RequiredCondition,
    ScopeGate,
    TermEvaluation,
)
from .contract_schema import Contract, Product, RebateTerm
from .entities import UnknownCounterparty, resolve_counterparty
from .llm import TextLLM
from .placement_llm import interpret_placement_llm
from .placement_prompts import PROMPT_VERSION
from .placement_rules import interpret_placement_rules, position_satisfies
from .schema import DocumentBlock, Line
from .verdict_cache import VerdictCache
from .vocabulary import (
    CheckName,
    CheckResult,
    ConsensusStatus,
    CoverageObserved,
    EXTRACTION_UM_TO_CONTRACT_KEY,
    InterpretedPosition,
    UMAllowance,
    Verdict,
)


def _parse_date(s: str | None) -> Optional[str]:
    if not s or len(s) < 10:
        return None
    return s[:10]


def _windows_overlap(c_start: str, c_end: str, f_start: str | None, f_end: str | None) -> bool:
    """True if contract window ∩ formulary window is non-empty.

    Missing formulary end → treat as open-ended. Missing formulary start → use
    contract start (cannot prove mismatch without a start).
    """
    cs, ce = _parse_date(c_start), _parse_date(c_end)
    if not cs or not ce:
        return False
    fs = _parse_date(f_start) or cs
    fe = _parse_date(f_end) or "9999-12-31"
    return cs <= fe and fs <= ce


def assert_preconditions(
    contract: Contract,
    formulary_doc: DocumentBlock,
    formulary_id_for_scope: str,
) -> ScopeGate:
    """Step 1 — refuse evaluation on failed assertions."""
    try:
        c_cid = resolve_counterparty(contract.counterparty.name)
    except UnknownCounterparty:
        return ScopeGate(passed=False, reason="unknown_counterparty", contract_canonical_id=None)

    try:
        f_cid = resolve_counterparty(formulary_doc.payer_or_pbm)
    except UnknownCounterparty:
        return ScopeGate(
            passed=False,
            reason="unknown_counterparty",
            contract_canonical_id=c_cid,
            formulary_canonical_id=None,
        )

    if c_cid != f_cid:
        return ScopeGate(
            passed=False,
            reason="counterparty_mismatch",
            contract_canonical_id=c_cid,
            formulary_canonical_id=f_cid,
        )

    covered = set(contract.covered_formularies or [])
    in_scope = formulary_id_for_scope in covered or "*" in covered
    # Also allow printed ID variants (comma suffix stripped already by caller)
    if not in_scope and formulary_doc.formulary_id:
        printed = formulary_doc.formulary_id.split(",")[0].strip()
        in_scope = printed in covered
    if not in_scope:
        return ScopeGate(
            passed=False,
            reason="formulary_out_of_scope",
            contract_canonical_id=c_cid,
            formulary_canonical_id=f_cid,
        )

    if not _windows_overlap(
        contract.effective_start,
        contract.effective_end,
        formulary_doc.effective_start,
        formulary_doc.effective_end,
    ):
        return ScopeGate(
            passed=False,
            reason="effective_window_mismatch",
            contract_canonical_id=c_cid,
            formulary_canonical_id=f_cid,
        )

    return ScopeGate(
        passed=True,
        reason=None,
        contract_canonical_id=c_cid,
        formulary_canonical_id=f_cid,
    )


def _norm_name(s: str | None) -> str:
    return " ".join((s or "").lower().replace("-", " ").split())


def join_product_to_line(
    product: Product,
    lines: list[Line] | list[dict],
) -> tuple[Optional[Any], CoverageObserved, list[Any]]:
    """Step 2 — match by NDC when present, else normalized drug name."""
    candidates: list[Any] = []
    product_ndc = (product.ndc or "").replace("-", "").strip()
    product_name = _norm_name(product.product_name)

    for line in lines:
        if isinstance(line, dict):
            drug_raw = line.get("drug_name_raw") or ""
            drug_norm = line.get("drug_name_normalized") or ""
            # NDC rarely on formulary lines in Module 01 — name match primary
        else:
            drug_raw = line.drug_name_raw or ""
            drug_norm = line.drug_name_normalized or ""

        names = {_norm_name(drug_raw), _norm_name(drug_norm)}
        if product_name and product_name in names:
            candidates.append(line)
            continue
        # brand/generic containment (SYNTHROID in "SYNTHROID TABLET")
        if product_name and any(product_name in n for n in names if n):
            candidates.append(line)

    if not candidates:
        return None, CoverageObserved.not_found, []
    if len(candidates) > 1:
        # Prefer exact normalized equality
        exact = []
        for c in candidates:
            n = _norm_name(
                (c.get("drug_name_normalized") if isinstance(c, dict) else c.drug_name_normalized)
                or (c.get("drug_name_raw") if isinstance(c, dict) else c.drug_name_raw)
            )
            if n == product_name:
                exact.append(c)
        if len(exact) == 1:
            return exact[0], CoverageObserved.covered, candidates
        return None, CoverageObserved.not_found, candidates  # ambiguous multi → caller handles

    line = candidates[0]
    cov_raw = (
        line.get("coverage_status") if isinstance(line, dict) else line.coverage_status
    ) or "unknown"
    if str(cov_raw).lower() in ("excluded", "non_formulary"):
        return line, CoverageObserved.excluded, candidates
    if str(cov_raw).lower() == "covered":
        return line, CoverageObserved.covered, candidates
    return line, CoverageObserved.covered, candidates


def _line_field(line: Any, key: str, default=None):
    if line is None:
        return default
    if isinstance(line, dict):
        return line.get(key, default)
    return getattr(line, key, default)


def _check(
    name: CheckName,
    expected: str,
    observed: str,
    result: CheckResult,
    rationale: str,
) -> CheckRecord:
    return CheckRecord(
        check=name,
        expected=expected,
        observed=observed,
        result=result,
        rationale=rationale,
    )


def _um_present_set(um_present: list[str]) -> set[str]:
    return {u for u in um_present if u in EXTRACTION_UM_TO_CONTRACT_KEY}


def evaluate_term(
    term: RebateTerm,
    *,
    coverage: CoverageObserved,
    interpreted_position: str,
    um_present: list[str],
    claimed_rate: float | None,
    position_ambiguous: bool,
) -> TermEvaluation:
    checks: list[CheckRecord] = []
    cond = term.condition

    # coverage
    if coverage == CoverageObserved.not_found:
        checks.append(
            _check(
                CheckName.coverage,
                "covered",
                "not_found",
                CheckResult.fail,
                "Contracted product absent from formulary (finding, not skip).",
            )
        )
    elif coverage == CoverageObserved.excluded:
        checks.append(
            _check(
                CheckName.coverage,
                "covered",
                "excluded",
                CheckResult.fail,
                "Product listed as excluded / non-formulary.",
            )
        )
    else:
        checks.append(
            _check(
                CheckName.coverage,
                "covered",
                "covered",
                CheckResult.pass_,
                "Product is covered on the formulary.",
            )
        )

    # position
    if coverage in (CoverageObserved.not_found, CoverageObserved.excluded):
        checks.append(
            _check(
                CheckName.position,
                cond.formulary_position.value,
                interpreted_position,
                CheckResult.not_evaluated,
                "Position not evaluated when coverage failed.",
            )
        )
    elif position_ambiguous or interpreted_position == InterpretedPosition.ambiguous.value:
        checks.append(
            _check(
                CheckName.position,
                cond.formulary_position.value,
                interpreted_position,
                CheckResult.indeterminate,
                "Interpreted position ambiguous; needs human review.",
            )
        )
    else:
        ok = position_satisfies(cond.formulary_position.value, interpreted_position)
        if ok is True:
            checks.append(
                _check(
                    CheckName.position,
                    cond.formulary_position.value,
                    interpreted_position,
                    CheckResult.pass_,
                    "Observed position meets or beats required position.",
                )
            )
        elif ok is False:
            checks.append(
                _check(
                    CheckName.position,
                    cond.formulary_position.value,
                    interpreted_position,
                    CheckResult.fail,
                    "Observed position worse than contracted requirement (access leakage).",
                )
            )
        else:
            checks.append(
                _check(
                    CheckName.position,
                    cond.formulary_position.value,
                    interpreted_position,
                    CheckResult.indeterminate,
                    "Could not compare positions.",
                )
            )

    # UM checks
    um_set = _um_present_set(um_present)
    for check_name, allowance, code in (
        (CheckName.prior_auth, cond.prior_auth, "PA"),
        (CheckName.step_therapy, cond.step_therapy, "ST"),
        (CheckName.quantity_limit, cond.quantity_limit, "QL"),
    ):
        present = code in um_set
        if coverage in (CoverageObserved.not_found, CoverageObserved.excluded):
            checks.append(
                _check(
                    check_name,
                    allowance.value,
                    code if present else "absent",
                    CheckResult.not_evaluated,
                    f"{code} not evaluated when coverage failed.",
                )
            )
            continue
        if allowance == UMAllowance.not_allowed and present:
            checks.append(
                _check(
                    check_name,
                    allowance.value,
                    code,
                    CheckResult.fail,
                    f"Contract forbids {code} but formulary row carries {code}.",
                )
            )
        else:
            checks.append(
                _check(
                    check_name,
                    allowance.value,
                    code if present else "absent",
                    CheckResult.pass_,
                    f"{code} allowance={allowance.value}; observed={'present' if present else 'absent'}.",
                )
            )

    # rate — compare claimed to THIS term's rate when evaluating the term;
    # aggregation picks best-matching term for the product-level rate check.
    if claimed_rate is None:
        checks.append(
            _check(
                CheckName.rate,
                str(term.rebate_rate_pct),
                "absent",
                CheckResult.indeterminate,
                "Claimed rebate rate absent → indeterminate (never pass).",
            )
        )
    else:
        # Per-term rate equality is informational; product rollup uses earned rate.
        match = abs(float(claimed_rate) - float(term.rebate_rate_pct)) < 1e-6
        checks.append(
            _check(
                CheckName.rate,
                str(term.rebate_rate_pct),
                str(claimed_rate),
                CheckResult.pass_ if match else CheckResult.fail,
                "Claimed rate vs this term's rate."
                if match
                else "Claimed rate does not equal this term's rebate_rate_pct.",
            )
        )

    results = [c.result for c in checks if c.result != CheckResult.not_evaluated]
    if any(r == CheckResult.fail for r in results):
        term_result = Verdict.non_compliant
    elif any(r == CheckResult.indeterminate for r in results):
        term_result = Verdict.indeterminate
    elif results and all(r == CheckResult.pass_ for r in results):
        term_result = Verdict.compliant
    else:
        term_result = Verdict.indeterminate

    return TermEvaluation(
        term_id=term.term_id,
        required=RequiredCondition(
            formulary_position=cond.formulary_position.value,
            prior_auth=cond.prior_auth.value,
            step_therapy=cond.step_therapy.value,
            quantity_limit=cond.quantity_limit.value,
            rebate_rate_pct=term.rebate_rate_pct,
        ),
        checks=checks,
        term_result=term_result,
    )


def _term_satisfies_placement(term_eval: TermEvaluation) -> bool:
    """True if coverage/position/UM checks all pass (ignore rate for 'earned' term pick)."""
    for c in term_eval.checks:
        if c.check == CheckName.rate:
            continue
        if c.result in (CheckResult.fail, CheckResult.indeterminate):
            return False
        if c.result == CheckResult.not_evaluated and c.check == CheckName.coverage:
            return False
    cov = next((c for c in term_eval.checks if c.check == CheckName.coverage), None)
    return cov is not None and cov.result == CheckResult.pass_


def evaluate_product(
    product: Product,
    *,
    formulary_lines: list,
    legend: dict[str, str],
    claimed_rate: float | None,
    llm: TextLLM | None = None,
    use_llm_fallback: bool = False,
    cache: VerdictCache | None = None,
    model_name: str = "rules",
) -> ProductResult:
    line, cov_join, multi = join_product_to_line(product, formulary_lines)
    review_reasons: list[str] = []
    needs_review = False

    if len(multi) > 1 and line is None:
        return ProductResult(
            product_name=product.product_name,
            ndc=product.ndc,
            matched_formulary_line=MatchedFormularyLine(),
            observed=ObservedPlacement(
                coverage_status=CoverageObserved.not_found,
                interpreted_position=InterpretedPosition.ambiguous,
                um_present=[],
            ),
            interpretation=InterpretationBlock(
                confidence=0.0,
                consensus=ConsensusStatus.rules_only,
                readings=[
                    InterpretationReading(
                        call=1,
                        interpreted_position=InterpretedPosition.ambiguous.value,
                        reasoning="Multiple formulary line candidates; not guessing.",
                    )
                ],
                source="rules",
            ),
            term_evaluations=[],
            verdict=Verdict.indeterminate,
            needs_human_review=True,
            review_reasons=["multiple_line_matches"],
            claimed_rebate_rate_pct=claimed_rate,
        )

    if line is None:
        observed = ObservedPlacement(
            coverage_status=CoverageObserved.not_found,
            interpreted_position=None,
            um_present=[],
        )
        interp = InterpretationBlock(
            confidence=1.0,
            consensus=ConsensusStatus.rules_only,
            readings=[],
            model="rules",
            prompt_version="rules-v1",
            source="rules",
        )
        # Build synthetic interpretation for checks
        position = InterpretedPosition.ambiguous.value
        um: list[str] = []
        position_ambiguous = False
        coverage = CoverageObserved.not_found
        matched = MatchedFormularyLine()
    else:
        tier = _line_field(line, "tier")
        um_flags = list(_line_field(line, "um_flags") or [])
        cov_status = str(_line_field(line, "coverage_status") or "unknown")
        raw_row = _line_field(line, "raw_row_text")
        page_ref = _line_field(line, "page_ref")
        matched = MatchedFormularyLine(
            line_id=_line_field(line, "line_id"),
            page_ref=page_ref,
            raw_row_text=raw_row,
        )
        rules = interpret_placement_rules(
            coverage_status=cov_status,
            tier=tier if isinstance(tier, int) else None,
            um_flags=um_flags,
        )
        coverage = CoverageObserved(rules["coverage_status"])
        if cov_join == CoverageObserved.excluded:
            coverage = CoverageObserved.excluded

        used_llm = False
        llm_out = None
        if rules.get("ambiguous") and use_llm_fallback and llm is not None:
            # Use first term's position language as context
            first_pos = product.rebate_terms[0].condition.formulary_position.value
            clause = product.rebate_terms[0].notes
            llm_out = interpret_placement_llm(
                llm,
                drug_name=product.product_name,
                tier=tier if isinstance(tier, int) else None,
                coverage_status=cov_status,
                um_flags=um_flags,
                raw_row_text=raw_row,
                legend=legend or {},
                contract_position=first_pos,
                contract_clause=clause,
                page_ref=page_ref,
                cache=cache,
                model_name=model_name,
            )
            used_llm = True

        if used_llm and llm_out is not None:
            position = llm_out["interpreted_position"]
            um = list(llm_out["um_present"])
            position_ambiguous = bool(llm_out.get("ambiguous"))
            readings = [
                InterpretationReading(
                    call=r["call"],
                    interpreted_position=r["interpreted_position"],
                    um_present=r.get("um_present") or [],
                    reasoning=r.get("reasoning") or "",
                )
                for r in llm_out.get("readings") or []
            ]
            if llm_out.get("needs_human_review"):
                needs_review = True
                review_reasons.extend(llm_out.get("review_reasons") or [])
            consensus = ConsensusStatus(llm_out.get("consensus") or ConsensusStatus.agreed.value)
            interp = InterpretationBlock(
                confidence=float(llm_out.get("confidence") or 0),
                consensus=consensus,
                readings=readings,
                model=llm_out.get("model") or model_name,
                prompt_version=llm_out.get("prompt_version") or PROMPT_VERSION,
                source=llm_out.get("source") or "llm",
            )
        else:
            position = rules["interpreted_position"]
            um = list(rules["um_present"])
            position_ambiguous = bool(rules.get("ambiguous"))
            if position_ambiguous:
                needs_review = True
                review_reasons.append("placement_ambiguous_rules")
            interp = InterpretationBlock(
                confidence=float(rules.get("confidence") or 0),
                consensus=ConsensusStatus.rules_only,
                readings=[
                    InterpretationReading(
                        call=1,
                        interpreted_position=position,
                        um_present=um,
                        reasoning=rules.get("reasoning") or "",
                    )
                ],
                model="rules",
                prompt_version="rules-v1",
                source="rules",
            )

        observed = ObservedPlacement(
            coverage_status=coverage,
            tier=tier if isinstance(tier, int) else None,
            interpreted_position=InterpretedPosition(position)
            if position in {p.value for p in InterpretedPosition}
            else InterpretedPosition.ambiguous,
            um_present=um,
        )

    term_evals = [
        evaluate_term(
            term,
            coverage=coverage if line is not None else CoverageObserved.not_found,
            interpreted_position=position,
            um_present=um,
            claimed_rate=claimed_rate,
            position_ambiguous=position_ambiguous if line is not None else False,
        )
        for term in product.rebate_terms
    ]

    # Best-matching term = highest rate among terms whose placement+UM satisfy
    earners = [t for t in term_evals if _term_satisfies_placement(t)]
    best = None
    if earners:
        best = max(earners, key=lambda t: t.required.rebate_rate_pct)
    earned = best.required.rebate_rate_pct if best else None

    # Rewrite rate check on each term_eval relative to earned rate at product level
    # Product verdict: prefer best term's non-rate checks + rate vs earned
    if best is not None and claimed_rate is not None:
        rate_ok = abs(float(claimed_rate) - float(earned)) < 1e-6
        # Replace rate check on best term with earned-rate comparison
        new_checks = []
        for c in best.checks:
            if c.check == CheckName.rate:
                new_checks.append(
                    _check(
                        CheckName.rate,
                        str(earned),
                        str(claimed_rate),
                        CheckResult.pass_ if rate_ok else CheckResult.fail,
                        "Claimed rate equals rate earned by actual placement."
                        if rate_ok
                        else "Claimed rate differs from rate earned by actual placement (overpayment risk).",
                    )
                )
            else:
                new_checks.append(c)
        best = TermEvaluation(
            term_id=best.term_id,
            required=best.required,
            checks=new_checks,
            term_result=Verdict.compliant
            if rate_ok and best.term_result == Verdict.compliant
            else (
                Verdict.non_compliant
                if (not rate_ok) or best.term_result == Verdict.non_compliant
                else best.term_result
            ),
        )
        # put updated best back into term_evals
        term_evals = [best if t.term_id == best.term_id else t for t in term_evals]

    # Aggregate product verdict
    if not term_evals:
        verdict = Verdict.indeterminate
    elif any(t.term_result == Verdict.compliant for t in term_evals):
        # At least one fully compliant term (including rate) → compliant
        verdict = Verdict.compliant
    elif all(t.term_result == Verdict.non_compliant for t in term_evals):
        verdict = Verdict.non_compliant
    elif any(t.term_result == Verdict.non_compliant for t in term_evals) and best is None:
        verdict = Verdict.non_compliant
    elif best is not None:
        verdict = best.term_result
    else:
        verdict = Verdict.indeterminate

    # If coverage not found → non_compliant finding
    if (line is None or coverage == CoverageObserved.not_found) and "multiple_line_matches" not in review_reasons:
        # re-evaluate with not_found path already in term_evals
        if term_evals and all(t.term_result == Verdict.non_compliant for t in term_evals):
            verdict = Verdict.non_compliant

    return ProductResult(
        product_name=product.product_name,
        ndc=product.ndc,
        matched_formulary_line=matched if line is not None else MatchedFormularyLine(),
        observed=observed
        if line is not None
        else ObservedPlacement(
            coverage_status=CoverageObserved.not_found,
            um_present=[],
        ),
        interpretation=interp,
        term_evaluations=term_evals,
        best_matching_term_id=best.term_id if best else None,
        earned_rebate_rate_pct=earned,
        claimed_rebate_rate_pct=claimed_rate,
        verdict=verdict,
        needs_human_review=needs_review,
        review_reasons=review_reasons,
    )


def evaluate_compliance(
    contract: Contract,
    formulary: dict,
    *,
    claimed_rate_by_product: dict[str, float | None] | None = None,
    formulary_id_override: str | None = None,
    llm: TextLLM | None = None,
    use_llm_fallback: bool = False,
    cache: VerdictCache | None = None,
    model_name: str = "rules",
    product_filter: set[str] | None = None,
) -> ComplianceResult:
    """Evaluate contract products against one formulary extraction JSON."""
    doc_raw = formulary.get("document") or {}
    doc = DocumentBlock.model_validate(doc_raw) if not isinstance(doc_raw, DocumentBlock) else doc_raw
    lines_raw = formulary.get("lines") or []
    lines = []
    for lr in lines_raw:
        if isinstance(lr, Line):
            lines.append(lr)
        else:
            try:
                lines.append(Line.model_validate(lr))
            except Exception:
                lines.append(lr)

    scope_fid = formulary_id_override or (doc.formulary_id or "")
    if scope_fid:
        scope_fid = scope_fid.split(",")[0].strip()

    gate = assert_preconditions(contract, doc, scope_fid or (formulary_id_override or ""))
    evaluated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    result = ComplianceResult(
        contract_id=contract.contract_id,
        formulary_id=formulary_id_override or doc.formulary_id or scope_fid,
        formulary_effective_window=DateWindow(start=doc.effective_start, end=doc.effective_end),
        evaluated_at=evaluated_at,
        scope_gate=gate,
        product_results=[],
    )

    if not gate.passed:
        # Emit indeterminate product shells so callers see the gate reason
        for product in contract.products:
            if product_filter and product.product_name.upper() not in {p.upper() for p in product_filter}:
                continue
            claimed = None
            if claimed_rate_by_product:
                claimed = claimed_rate_by_product.get(product.product_name)
                if claimed is None:
                    claimed = claimed_rate_by_product.get(product.product_name.upper())
            result.product_results.append(
                ProductResult(
                    product_name=product.product_name,
                    ndc=product.ndc,
                    matched_formulary_line=MatchedFormularyLine(),
                    observed=ObservedPlacement(coverage_status=CoverageObserved.not_found),
                    interpretation=InterpretationBlock(
                        confidence=0.0,
                        consensus=ConsensusStatus.rules_only,
                        source="rules",
                    ),
                    term_evaluations=[],
                    verdict=Verdict.indeterminate,
                    needs_human_review=gate.reason == "unknown_counterparty",
                    review_reasons=[gate.reason or "scope_gate_failed"],
                    claimed_rebate_rate_pct=claimed,
                )
            )
        return result

    legend = doc.legend if isinstance(doc.legend, dict) else {}
    for product in contract.products:
        if product_filter and product.product_name.upper() not in {p.upper() for p in product_filter}:
            continue
        claimed = None
        if claimed_rate_by_product:
            claimed = claimed_rate_by_product.get(product.product_name)
            if claimed is None:
                claimed = claimed_rate_by_product.get(product.product_name.upper())
        result.product_results.append(
            evaluate_product(
                product,
                formulary_lines=lines,
                legend=legend,
                claimed_rate=claimed,
                llm=llm,
                use_llm_fallback=use_llm_fallback,
                cache=cache,
                model_name=model_name,
            )
        )
    return result
