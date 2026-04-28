"""Single-company research pipeline orchestration."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from biotech_alpha.agents import AgentContext, ClinicalTrialAgent
from biotech_alpha.clinicaltrials import (
    ClinicalTrialsClient,
    extract_trial_summaries,
    summaries_as_dicts,
)
from biotech_alpha.conference import (
    conference_validation_report_as_dict,
    load_conference_catalysts,
    validate_conference_catalyst_file,
)
from biotech_alpha.competition import (
    competition_validation_report_as_dict,
    competitive_landscape_finding,
    load_competitor_assets,
    match_competitors_to_pipeline,
    validate_competitor_file,
)
from biotech_alpha.financials import (
    CashRunwayEstimate,
    FinancialSnapshot,
    cash_runway_finding,
    cash_runway_payload,
    estimate_cash_runway,
    financial_validation_report_as_dict,
    load_financial_snapshot,
    validate_financial_snapshot_file,
)
from biotech_alpha.models import (
    AgentFinding,
    Catalyst,
    Evidence,
    InvestmentMemo,
    CompetitiveMatch,
    CompetitorAsset,
    PipelineAsset,
    TrialAssetMatch,
    TrialSummary,
)
from biotech_alpha.pipeline import (
    load_pipeline_assets,
    match_pipeline_assets_to_trials,
    validate_pipeline_asset_file,
    validation_report_as_dict,
)
from biotech_alpha.position_action import (
    ResearchActionPlan,
    build_research_action_plan,
    research_action_plan_finding,
)
from biotech_alpha.scorecard import (
    WatchlistScorecard,
    build_watchlist_scorecard,
    scorecard_finding,
    scorecard_payload,
)
from biotech_alpha.skeptic import scientific_skeptic_finding
from biotech_alpha.target_price import (
    TargetPriceAnalysis,
    TargetPriceAssumptions,
    build_target_price_analysis,
    event_impact_payload,
    load_target_price_assumptions,
    target_price_finding,
    target_price_payload,
    target_price_summary,
    target_price_validation_report_as_dict,
    validate_target_price_assumptions_file,
    write_target_price_summary_csv,
)
from biotech_alpha.valuation import (
    ValuationMetrics,
    ValuationSnapshot,
    calculate_valuation_metrics,
    load_valuation_snapshot,
    validate_valuation_snapshot_file,
    valuation_finding,
    valuation_payload,
    valuation_validation_report_as_dict,
)


class ClinicalTrialsSource(Protocol):
    """Subset of the ClinicalTrials.gov client used by the research pipeline."""

    def version(self) -> dict[str, Any]:
        """Return source version metadata."""

    def search_studies(
        self,
        term: str,
        *,
        page_size: int = 10,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """Return a ClinicalTrials.gov v2 studies response."""


@dataclass(frozen=True)
class ResearchArtifacts:
    """Files produced by a single-company research run."""

    manifest_json: Path | None = None
    raw_clinical_trials: Path | None = None
    normalized_trials: Path | None = None
    trial_summary_csv: Path | None = None
    catalyst_calendar_csv: Path | None = None
    pipeline_assets: Path | None = None
    asset_trial_matches: Path | None = None
    competitor_assets: Path | None = None
    competitive_matches: Path | None = None
    cash_runway: Path | None = None
    valuation: Path | None = None
    scorecard: Path | None = None
    event_impact: Path | None = None
    target_price_scenarios: Path | None = None
    target_price_summary_csv: Path | None = None
    extraction_audit: Path | None = None
    memo_json: Path | None = None
    memo_markdown: Path | None = None


@dataclass(frozen=True)
class SingleCompanyResearchResult:
    """Structured result returned by the single-company research pipeline."""

    run_id: str
    context: AgentContext
    search_term: str
    search_terms: tuple[str, ...]
    trials: tuple[TrialSummary, ...]
    pipeline_assets: tuple[PipelineAsset, ...]
    asset_trial_matches: tuple[TrialAssetMatch, ...]
    competitor_assets: tuple[CompetitorAsset, ...]
    competitive_matches: tuple[CompetitiveMatch, ...]
    financial_snapshot: FinancialSnapshot | None
    cash_runway_estimate: CashRunwayEstimate | None
    valuation_snapshot: ValuationSnapshot | None
    valuation_metrics: ValuationMetrics | None
    target_price_assumptions: TargetPriceAssumptions | None
    target_price_analysis: TargetPriceAnalysis | None
    scorecard: WatchlistScorecard
    input_validation: dict[str, Any]
    clinical_trial_finding: AgentFinding
    action_plan: ResearchActionPlan | None
    memo: InvestmentMemo
    api_version: dict[str, Any]
    artifacts: ResearchArtifacts


def run_single_company_research(
    *,
    company: str,
    ticker: str | None = None,
    market: str = "HK",
    search_term: str | None = None,
    pipeline_assets: tuple[PipelineAsset, ...] | None = None,
    pipeline_assets_path: str | Path | None = None,
    competitors_path: str | Path | None = None,
    financials_path: str | Path | None = None,
    valuation_path: str | Path | None = None,
    conference_catalysts_path: str | Path | None = None,
    target_price_assumptions_path: str | Path | None = None,
    include_asset_queries: bool = True,
    max_asset_query_terms: int = 20,
    limit: int = 20,
    output_dir: str | Path = "data",
    save: bool = True,
    client: ClinicalTrialsSource | None = None,
    now: datetime | None = None,
) -> SingleCompanyResearchResult:
    """Run the first-pass single-company research workflow.

    The MVP workflow searches ClinicalTrials.gov, normalizes trial records,
    optionally loads disclosed pipeline assets, matches assets to trials,
    derives near-term clinical catalysts, creates a conservative memo, and
    optionally preserves raw/processed outputs locally.
    """

    company = company.strip()
    if not company:
        raise ValueError("company must not be empty")
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if max_asset_query_terms < 0:
        raise ValueError("max_asset_query_terms must be non-negative")
    if pipeline_assets is not None and pipeline_assets_path is not None:
        raise ValueError(
            "pass either pipeline_assets or pipeline_assets_path, not both"
        )

    timestamp = now or datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    timestamp = timestamp.astimezone(UTC)
    run_id = timestamp.strftime("%Y%m%dT%H%M%SZ")
    query = (search_term or company).strip()
    assets = (
        load_pipeline_assets(pipeline_assets_path)
        if pipeline_assets_path
        else tuple(pipeline_assets or ())
    )
    financial_snapshot = (
        load_financial_snapshot(financials_path)
        if financials_path
        else None
    )
    valuation_snapshot = (
        load_valuation_snapshot(valuation_path)
        if valuation_path
        else None
    )
    valuation_snapshot = _merge_financial_cash_into_valuation_snapshot(
        valuation_snapshot=valuation_snapshot,
        financial_snapshot=financial_snapshot,
    )
    target_price_assumptions = (
        load_target_price_assumptions(target_price_assumptions_path)
        if target_price_assumptions_path
        else None
    )
    target_price_analysis = (
        build_target_price_analysis(target_price_assumptions)
        if target_price_assumptions
        else None
    )
    competitors = (
        load_competitor_assets(competitors_path)
        if competitors_path
        else ()
    )
    conference_catalysts = (
        load_conference_catalysts(conference_catalysts_path)
        if conference_catalysts_path
        else ()
    )
    competitive_matches = match_competitors_to_pipeline(assets, competitors)
    cash_runway_estimate = (
        estimate_cash_runway(financial_snapshot)
        if financial_snapshot
        else None
    )
    valuation_metrics = (
        calculate_valuation_metrics(valuation_snapshot)
        if valuation_snapshot
        else None
    )
    input_validation = _input_validation_reports(
        pipeline_assets_path=pipeline_assets_path,
        competitors_path=competitors_path,
        financials_path=financials_path,
        valuation_path=valuation_path,
        conference_catalysts_path=conference_catalysts_path,
        target_price_assumptions_path=target_price_assumptions_path,
    )
    search_terms = _clinical_trial_search_terms(
        primary_term=query,
        assets=assets,
        include_asset_queries=include_asset_queries,
        max_asset_query_terms=max_asset_query_terms,
    )

    trials_client = client or ClinicalTrialsClient()
    clinical_warnings: list[str] = []
    try:
        api_version = trials_client.version()
    except Exception as exc:  # noqa: BLE001 - keep report resilient.
        api_version = {"error": str(exc)}
        clinical_warnings.append(f"ClinicalTrials.gov version failed: {exc}")
    raw_responses, trials, search_warnings = _search_and_dedupe_clinical_trials(
        client=trials_client,
        search_terms=search_terms,
        limit=limit,
    )
    clinical_warnings.extend(search_warnings)
    if clinical_warnings:
        input_validation["clinical_trials"] = {
            "errors": [],
            "warnings": tuple(clinical_warnings),
            "search_term_count": len(search_terms),
            "failed_search_count": len(search_warnings),
        }
    asset_trial_matches = match_pipeline_assets_to_trials(assets, trials)

    context = AgentContext(
        company=company,
        ticker=ticker,
        market=market,
        as_of_date=timestamp.date().isoformat(),
    )
    clinical_finding = ClinicalTrialAgent().summarize_trials(context, list(trials))
    catalysts = (
        *_derive_clinical_catalysts(trials, today=timestamp.date()),
        *_derive_asset_milestone_catalysts(assets),
        *conference_catalysts,
    )
    skeptic_preview = scientific_skeptic_finding(
        company=company,
        trials=trials,
        pipeline_assets=assets,
        asset_trial_matches=asset_trial_matches,
        competitor_assets=competitors,
        competitive_matches=competitive_matches,
        cash_runway_estimate=cash_runway_estimate,
        valuation_metrics=valuation_metrics,
        input_warning_count=_input_warning_count(input_validation),
    )
    scorecard = build_watchlist_scorecard(
        trials=trials,
        pipeline_assets=assets,
        asset_trial_matches=asset_trial_matches,
        competitor_assets=competitors,
        competitive_matches=competitive_matches,
        catalysts=catalysts,
        cash_runway_estimate=cash_runway_estimate,
        valuation_metrics=valuation_metrics,
        input_warning_count=_input_warning_count(input_validation),
        skeptic_risk_count=len(skeptic_preview.risks),
    )
    run_decision = "watchlist" if trials or assets else "insufficient_data"
    action_plan: ResearchActionPlan | None = None
    if target_price_analysis:
        action_plan = build_research_action_plan(
            decision=run_decision,
            target_price_analysis=target_price_analysis,
            runway_months=(
                cash_runway_estimate.runway_months
                if cash_runway_estimate is not None
                else None
            ),
        )
    memo = _build_clinical_first_memo(
        context=context,
        trials=trials,
        pipeline_assets=assets,
        asset_trial_matches=asset_trial_matches,
        competitor_assets=competitors,
        competitive_matches=competitive_matches,
        financial_snapshot=financial_snapshot,
        cash_runway_estimate=cash_runway_estimate,
        valuation_snapshot=valuation_snapshot,
        valuation_metrics=valuation_metrics,
        target_price_analysis=target_price_analysis,
        scorecard=scorecard,
        skeptic_finding=skeptic_preview,
        input_validation=input_validation,
        finding=clinical_finding,
        catalysts=catalysts,
        retrieved_at=timestamp.isoformat(),
    )

    artifacts = ResearchArtifacts()
    if save:
        artifacts = _write_research_artifacts(
            output_dir=Path(output_dir),
            company=company,
            ticker=ticker,
            market=market,
            run_id=run_id,
            search_terms=search_terms,
            retrieved_at=timestamp.isoformat(),
            api_version=api_version,
            raw_responses=raw_responses,
            trials=trials,
            pipeline_assets=assets,
            asset_trial_matches=asset_trial_matches,
            competitor_assets=competitors,
            competitive_matches=competitive_matches,
            financial_snapshot=financial_snapshot,
            cash_runway_estimate=cash_runway_estimate,
            valuation_snapshot=valuation_snapshot,
            valuation_metrics=valuation_metrics,
            target_price_assumptions=target_price_assumptions,
            target_price_analysis=target_price_analysis,
            scorecard=scorecard,
            action_plan=action_plan,
            input_validation=input_validation,
            memo=memo,
        )

    return SingleCompanyResearchResult(
        run_id=run_id,
        context=context,
        search_term=query,
        search_terms=search_terms,
        trials=trials,
        pipeline_assets=assets,
        asset_trial_matches=asset_trial_matches,
        competitor_assets=competitors,
        competitive_matches=competitive_matches,
        financial_snapshot=financial_snapshot,
        cash_runway_estimate=cash_runway_estimate,
        valuation_snapshot=valuation_snapshot,
        valuation_metrics=valuation_metrics,
        target_price_assumptions=target_price_assumptions,
        target_price_analysis=target_price_analysis,
        scorecard=scorecard,
        input_validation=input_validation,
        clinical_trial_finding=clinical_finding,
        action_plan=action_plan,
        memo=memo,
        api_version=api_version,
        artifacts=artifacts,
    )


def result_summary(result: SingleCompanyResearchResult) -> dict[str, Any]:
    """Return a compact JSON-serializable summary for CLI output."""

    return {
        "run_id": result.run_id,
        "company": result.context.company,
        "ticker": result.context.ticker,
        "market": result.context.market,
        "search_term": result.search_term,
        "search_terms": result.search_terms,
        "decision": result.memo.decision,
        "trial_count": len(result.trials),
        "pipeline_asset_count": len(result.pipeline_assets),
        "asset_trial_match_count": len(result.asset_trial_matches),
        "competitor_asset_count": len(result.competitor_assets),
        "competitive_match_count": len(result.competitive_matches),
        "cash_runway_months": (
            result.cash_runway_estimate.runway_months
            if result.cash_runway_estimate
            else None
        ),
        "enterprise_value": (
            result.valuation_metrics.enterprise_value
            if result.valuation_metrics
            else None
        ),
        "revenue_multiple": (
            result.valuation_metrics.revenue_multiple
            if result.valuation_metrics
            else None
        ),
        "probability_weighted_target_price": (
            result.target_price_analysis.probability_weighted_target_price
            if result.target_price_analysis
            else None
        ),
        "implied_upside_downside_pct": (
            result.target_price_analysis.implied_upside_downside_pct
            if result.target_price_analysis
            else None
        ),
        "target_price_summary": (
            target_price_summary(result.target_price_analysis)
            if result.target_price_analysis
            else None
        ),
        "watchlist_score": result.scorecard.total_score,
        "watchlist_bucket": result.scorecard.bucket,
        "scorecard_dimensions": _scorecard_dimensions_payload(result.scorecard),
        "research_action_plan": _action_plan_payload(result.action_plan),
        "input_warning_count": _input_warning_count(result.input_validation),
        "catalyst_count": len(result.memo.catalysts),
        "needs_human_review": any(
            finding.needs_human_review for finding in result.memo.findings
        ),
        "artifacts": _jsonable(asdict(result.artifacts)),
    }


def _merge_financial_cash_into_valuation_snapshot(
    *,
    valuation_snapshot: ValuationSnapshot | None,
    financial_snapshot: FinancialSnapshot | None,
) -> ValuationSnapshot | None:
    if valuation_snapshot is None or financial_snapshot is None:
        return valuation_snapshot
    if (
        valuation_snapshot.cash_and_equivalents > 0
        or valuation_snapshot.total_debt > 0
    ):
        return valuation_snapshot
    cash = _convert_currency_amount(
        amount=financial_snapshot.cash_and_equivalents,
        from_currency=financial_snapshot.currency,
        to_currency=valuation_snapshot.currency,
    )
    debt = _convert_currency_amount(
        amount=financial_snapshot.short_term_debt,
        from_currency=financial_snapshot.currency,
        to_currency=valuation_snapshot.currency,
    )
    return replace(
        valuation_snapshot,
        cash_and_equivalents=cash,
        total_debt=debt,
    )


def _convert_currency_amount(
    *,
    amount: float,
    from_currency: str,
    to_currency: str,
) -> float:
    src = (from_currency or "").strip().upper()
    dst = (to_currency or "").strip().upper()
    if amount == 0 or not src or not dst or src == dst:
        return amount
    rates = {
        ("RMB", "HKD"): 1.08,
        ("CNY", "HKD"): 1.08,
        ("HKD", "RMB"): 1 / 1.08,
        ("HKD", "CNY"): 1 / 1.08,
    }
    fx = rates.get((src, dst))
    if fx is None:
        return amount
    return amount * fx


def memo_to_markdown(
    memo: InvestmentMemo,
    *,
    llm_findings: tuple[AgentFinding, ...] = (),
    llm_confidence_threshold: float = 0.3,
    report_quality_payload: dict[str, Any] | None = None,
    report_synthesizer_payload: dict[str, Any] | None = None,
) -> str:
    """Render an investment-style memo with LLM findings merged in."""

    trusted_llm = tuple(
        finding
        for finding in llm_findings
        if finding.confidence >= llm_confidence_threshold
    )
    all_findings = (*memo.findings, *trusted_llm)
    lines = [
        f"# {memo.company} 研究报告",
        "",
        f"- 代码: {memo.ticker or '未识别'}",
        f"- 市场: {memo.market}",
        f"- 结论: `{memo.decision}`",
        "",
        "## 执行结论",
        "",
        memo.summary,
        "",
    ]
    if isinstance(report_synthesizer_payload, dict):
        verdict = str(
            report_synthesizer_payload.get("executive_verdict_paragraph")
            or ""
        ).strip()
        if verdict:
            lines.extend([verdict, ""])
    lines.extend(_executive_observation_lines(memo=memo, findings=tuple(all_findings)))
    valuation_findings = _findings_for(all_findings, "target_price")
    competition_findings = _findings_for(all_findings, "competition")
    if valuation_findings:
        for finding in valuation_findings:
            lines.append(f"- {finding.summary}")
    scorecard_findings = _findings_for(all_findings, "watchlist_scorecard")
    if scorecard_findings:
        lines.append(f"- {scorecard_findings[0].summary}")

    lines.extend(["", "## 投资主线", ""])
    _append_synth_transition(lines, report_synthesizer_payload, "investment_thesis")
    lines.append("### 看多驱动")
    lines.extend(_bullet_lines(memo.bull_case))
    lines.extend(["", "### 看空驱动"])
    lines.extend(_bullet_lines(memo.bear_case))
    skeptic_findings = _findings_for(all_findings, "skeptic")
    thesis_findings = _findings_for(all_findings, "investment_thesis")
    if thesis_findings:
        for finding in thesis_findings:
            lines.append(f"- {finding.summary}")
    if skeptic_findings:
        lines.extend(["", "### 反证视角"])
        for finding in skeptic_findings:
            lines.append(f"- {finding.summary}")

    lines.extend(["", "## 核心资产深挖", ""])
    _append_synth_transition(lines, report_synthesizer_payload, "core_assets")
    if memo.key_assets:
        for asset in memo.key_assets[:3]:
            details = []
            if asset.target:
                details.append(f"靶点 {asset.target}")
            if asset.indication:
                details.append(f"适应症 {asset.indication}")
            if asset.phase:
                details.append(f"阶段 {_phase_label_zh(asset.phase)}")
            if asset.regulatory_pathway:
                details.append(f"监管路径 {asset.regulatory_pathway}")
            if asset.next_binary_event:
                details.append(f"二元事件 {asset.next_binary_event}")
            if asset.next_milestone:
                details.append(f"里程碑 {asset.next_milestone}")
            suffix = f" ({'; '.join(details)})" if details else ""
            lines.append(f"- {asset.name}{suffix}")
            if asset.clinical_data:
                for datum in asset.clinical_data[:3]:
                    lines.append(f"  - 临床数据: {_clinical_data_line(datum)}")
            for line in _deep_dive_competitive_lines(
                asset_name=asset.name,
                competition_findings=tuple(competition_findings),
            ):
                lines.append(f"  - {line}")
    else:
        lines.append("- 未提供可用的结构化管线资产输入。")
    pipeline_llm = _findings_for(all_findings, "pipeline_triage")
    if pipeline_llm:
        lines.extend(["", "### 管线审阅备注"])
        for finding in pipeline_llm:
            lines.append(f"- {finding.summary}")

    lines.extend(["", "## 催化剂路线图", ""])
    _append_synth_transition(lines, report_synthesizer_payload, "catalysts")
    for line in _catalyst_lines(memo.catalysts, key_assets=memo.key_assets):
        lines.append(line)

    lines.extend(["", "## 竞争格局", ""])
    _append_synth_transition(lines, report_synthesizer_payload, "competition")
    if competition_findings:
        for finding in competition_findings:
            lines.append(f"- {finding.summary}")
            for risk in finding.risks[:3]:
                lines.append(f"  - {_format_section_risk(risk)}")
    else:
        lines.append("- 未提供可用的结构化竞品输入。")

    lines.extend(["", "## 财务与现金流", ""])
    _append_synth_transition(lines, report_synthesizer_payload, "financials")
    financial_findings = _findings_for(all_findings, "financial")
    if financial_findings:
        for finding in financial_findings:
            lines.append(f"- {finding.summary}")
            for risk in finding.risks[:3]:
                lines.append(f"  - {_format_section_risk(risk)}")
    else:
        lines.append("- 财务与现金流结论暂不可用。")

    lines.extend(["", "## 估值细化", ""])
    _append_synth_transition(lines, report_synthesizer_payload, "valuation")
    if valuation_findings:
        for finding in valuation_findings:
            lines.append(f"- {finding.summary}")
            for risk in finding.risks:
                lines.append(f"  - {risk}")
        process_findings = _findings_for(all_findings, "valuation_process")
        for finding in process_findings:
            lines.append(f"- {finding.summary}")
            for risk in finding.risks:
                lines.append(f"  - {risk}")
        valuation_llm_findings = _findings_for(all_findings, "valuation_specialist")
        for finding in valuation_llm_findings:
            lines.append(f"- {finding.summary}")
            for risk in finding.risks:
                lines.append(f"  - {risk}")
    else:
        lines.append("- 尚未形成催化剂调整后的目标价区间。")

    lines.extend(["", "## 评分卡透明度", ""])
    if scorecard_findings:
        for finding in scorecard_findings:
            lines.append(f"- {finding.summary}")
            for risk in finding.risks:
                lines.append(f"  - {risk}")
        lines.extend(
            _scorecard_lift_target_lines(tuple(scorecard_findings))
        )
    else:
        lines.append("- 尚未生成评分卡摘要。")

    lines.extend(["", "## 研究行动计划（非交易指令）", ""])
    action_plan_findings = _findings_for(all_findings, "research_action_plan")
    lines.extend(
        _research_only_action_plan_lines(
            decision=memo.decision,
            valuation_findings=tuple(valuation_findings),
            scorecard_findings=tuple(scorecard_findings),
            action_plan_findings=tuple(action_plan_findings),
        )
    )

    lines.extend(["", "## 关键风险与证伪条件", ""])
    _append_synth_transition(lines, report_synthesizer_payload, "risks")
    lines.extend(_finding_risk_lines(tuple(all_findings)))

    if isinstance(report_quality_payload, dict):
        lines.extend(["", "## 报告质量门", ""])
        publish_gate = str(
            report_quality_payload.get("publish_gate") or "review_required"
        )
        summary = str(
            report_quality_payload.get("summary")
            or "报告质量审阅完成，建议人工复核。"
        )
        lines.append(f"- publish_gate: `{publish_gate}`")
        lines.append(f"- {summary}")
        for key, label in (
            ("critical_issues", "关键问题"),
            ("consistency_findings", "一致性发现"),
            ("missing_evidence_findings", "证据缺口"),
            ("language_quality_findings", "语言质量"),
            ("valuation_coherence_findings", "估值一致性"),
            ("recommended_fixes", "建议修复"),
        ):
            values = report_quality_payload.get(key) or []
            if not values:
                continue
            lines.append(f"- {label}:")
            for item in values[:5]:
                text = str(item).strip()
                if text:
                    lines.append(f"  - {text}")

    lines.extend(["", "## 证据与来源", ""])
    evidence_items = (
        *memo.evidence,
        *(evidence for finding in all_findings for evidence in finding.evidence),
    )
    if evidence_items:
        for evidence in evidence_items:
            inferred = " inferred" if evidence.is_inferred else ""
            source_date = (
                f", source date {evidence.source_date}"
                if evidence.source_date
                else ""
            )
            lines.append(
                f"- {evidence.claim} [{evidence.source}]"
                f"{source_date}, confidence {evidence.confidence:.2f}{inferred}"
            )
    else:
        lines.append("- 暂无可追溯证据。")

    lines.extend(["", "## 后续问题", ""])
    lines.extend(_bullet_lines(memo.follow_up_questions))
    lines.append("")
    return "\n".join(lines)


def _append_synth_transition(
    lines: list[str],
    payload: dict[str, Any] | None,
    key: str,
) -> None:
    if not isinstance(payload, dict):
        return
    transitions = payload.get("section_transitions")
    if not isinstance(transitions, dict):
        return
    text = str(transitions.get(key) or "").strip()
    if text:
        lines.extend([text, ""])


def write_trial_summary_csv(
    *,
    path: str | Path,
    trials: tuple[TrialSummary, ...],
) -> Path:
    """Write normalized trial summaries as a review-friendly CSV table."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "registry",
                "registry_id",
                "title",
                "sponsor",
                "status",
                "phase",
                "conditions",
                "interventions",
                "enrollment",
                "start_date",
                "primary_completion_date",
                "completion_date",
                "last_update_posted",
            ],
        )
        writer.writeheader()
        for trial in trials:
            writer.writerow(
                {
                    "registry": trial.registry,
                    "registry_id": trial.registry_id,
                    "title": trial.title,
                    "sponsor": trial.sponsor,
                    "status": trial.status,
                    "phase": trial.phase,
                    "conditions": "; ".join(trial.conditions),
                    "interventions": "; ".join(trial.interventions),
                    "enrollment": trial.enrollment,
                    "start_date": trial.start_date,
                    "primary_completion_date": trial.primary_completion_date,
                    "completion_date": trial.completion_date,
                    "last_update_posted": trial.last_update_posted,
                }
            )
    return output_path


def write_catalyst_calendar_csv(
    *,
    path: str | Path,
    catalysts: tuple[Catalyst, ...],
) -> Path:
    """Write derived catalysts as a calendar-ready CSV table."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "title",
                "category",
                "expected_date",
                "expected_window",
                "related_asset",
                "confidence",
                "evidence_count",
            ],
        )
        writer.writeheader()
        for catalyst in catalysts:
            writer.writerow(
                {
                    "title": catalyst.title,
                    "category": catalyst.category,
                    "expected_date": (
                        catalyst.expected_date.isoformat()
                        if catalyst.expected_date
                        else ""
                    ),
                    "expected_window": catalyst.expected_window,
                    "related_asset": catalyst.related_asset,
                    "confidence": catalyst.confidence,
                    "evidence_count": len(catalyst.evidence),
                }
            )
    return output_path


def _clinical_trial_search_terms(
    *,
    primary_term: str,
    assets: tuple[PipelineAsset, ...],
    include_asset_queries: bool,
    max_asset_query_terms: int,
) -> tuple[str, ...]:
    terms = [primary_term]
    if include_asset_queries:
        for asset in assets:
            terms.extend((asset.name, *asset.aliases))

    deduped: list[str] = []
    seen: set[str] = set()
    asset_terms_used = 0
    for index, term in enumerate(terms):
        term = term.strip()
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        if index > 0:
            if asset_terms_used >= max_asset_query_terms:
                continue
            asset_terms_used += 1
        seen.add(key)
        deduped.append(term)
    return tuple(deduped)


def _search_and_dedupe_clinical_trials(
    *,
    client: ClinicalTrialsSource,
    search_terms: tuple[str, ...],
    limit: int,
) -> tuple[dict[str, dict[str, Any]], tuple[TrialSummary, ...], tuple[str, ...]]:
    raw_responses: dict[str, dict[str, Any]] = {}
    trials_by_key: dict[str, TrialSummary] = {}
    warnings: list[str] = []
    for term in search_terms:
        try:
            response = client.search_studies(term, page_size=limit)
        except Exception as exc:  # noqa: BLE001 - one failed term should degrade.
            warnings.append(f"{term}: ClinicalTrials.gov search failed: {exc}")
            raw_responses[term] = {"studies": [], "error": str(exc)}
            continue
        raw_responses[term] = response
        for trial in extract_trial_summaries(response):
            key = _trial_dedupe_key(trial)
            if key and key not in trials_by_key:
                trials_by_key[key] = trial
    return raw_responses, tuple(trials_by_key.values()), tuple(warnings)


def _trial_dedupe_key(trial: TrialSummary) -> str:
    if trial.registry_id:
        return f"{trial.registry}:{trial.registry_id}".casefold()
    title_key = re.sub(r"\s+", " ", trial.title).strip().casefold()
    if title_key:
        return f"{trial.registry}:title:{title_key}"
    return ""


def _input_validation_reports(
    *,
    pipeline_assets_path: str | Path | None,
    competitors_path: str | Path | None,
    financials_path: str | Path | None,
    valuation_path: str | Path | None,
    conference_catalysts_path: str | Path | None,
    target_price_assumptions_path: str | Path | None,
) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    if pipeline_assets_path:
        reports["pipeline_assets"] = validation_report_as_dict(
            validate_pipeline_asset_file(pipeline_assets_path)
        )
    if competitors_path:
        reports["competitors"] = competition_validation_report_as_dict(
            validate_competitor_file(competitors_path)
        )
    if financials_path:
        reports["financials"] = financial_validation_report_as_dict(
            validate_financial_snapshot_file(financials_path)
        )
    if valuation_path:
        reports["valuation"] = valuation_validation_report_as_dict(
            validate_valuation_snapshot_file(valuation_path)
        )
    if conference_catalysts_path:
        reports["conference_catalysts"] = conference_validation_report_as_dict(
            validate_conference_catalyst_file(conference_catalysts_path)
        )
    if target_price_assumptions_path:
        reports["target_price"] = target_price_validation_report_as_dict(
            validate_target_price_assumptions_file(target_price_assumptions_path)
        )
    return reports


def _input_warning_count(input_validation: dict[str, Any]) -> int:
    count = 0
    for report in input_validation.values():
        warnings = report.get("warnings", []) if isinstance(report, dict) else []
        count += len(warnings)
    return count


def _build_clinical_first_memo(
    *,
    context: AgentContext,
    trials: tuple[TrialSummary, ...],
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    competitive_matches: tuple[CompetitiveMatch, ...],
    financial_snapshot: FinancialSnapshot | None,
    cash_runway_estimate: CashRunwayEstimate | None,
    valuation_snapshot: ValuationSnapshot | None,
    valuation_metrics: ValuationMetrics | None,
    target_price_analysis: TargetPriceAnalysis | None,
    scorecard: WatchlistScorecard,
    skeptic_finding: AgentFinding,
    input_validation: dict[str, Any],
    finding: AgentFinding,
    catalysts: tuple[Catalyst, ...],
    retrieved_at: str,
) -> InvestmentMemo:
    trial_evidence = tuple(
        _trial_evidence(trial, retrieved_at)
        for trial in trials
        if trial.registry_id
    )
    asset_evidence = tuple(
        evidence
        for asset in pipeline_assets
        for evidence in asset.evidence
    )
    match_finding = _build_pipeline_match_finding(
        context=context,
        assets=pipeline_assets,
        matches=asset_trial_matches,
    )
    findings = [
        finding,
        _build_data_quality_finding(
            context=context,
            pipeline_assets=pipeline_assets,
            competitor_assets=competitor_assets,
            financial_snapshot=financial_snapshot,
            valuation_snapshot=valuation_snapshot,
            input_validation=input_validation,
        ),
    ]
    if pipeline_assets:
        findings.append(match_finding)
    if competitor_assets:
        findings.append(
            competitive_landscape_finding(
                company=context.company,
                assets=pipeline_assets,
                competitors=competitor_assets,
                matches=competitive_matches,
            )
        )
    if financial_snapshot and cash_runway_estimate:
        findings.append(
            cash_runway_finding(
                company=context.company,
                snapshot=financial_snapshot,
                estimate=cash_runway_estimate,
            )
        )
    if valuation_snapshot and valuation_metrics:
        findings.append(
            valuation_finding(
                company=context.company,
                snapshot=valuation_snapshot,
                metrics=valuation_metrics,
            )
        )
    if target_price_analysis:
        findings.append(
            target_price_finding(
                company=context.company,
                analysis=target_price_analysis,
            )
        )
        findings.append(
            _valuation_process_finding(
                company=context.company,
                valuation_snapshot=valuation_snapshot,
                valuation_metrics=valuation_metrics,
                target_price_analysis=target_price_analysis,
            )
        )
    findings.append(skeptic_finding)
    findings.append(scorecard_finding(company=context.company, scorecard=scorecard))
    evidence = (*trial_evidence, *asset_evidence)
    if financial_snapshot and financial_snapshot.source:
        evidence = (
            *evidence,
            Evidence(
                claim=(
                    f"{context.company} financial snapshot as of "
                    f"{financial_snapshot.as_of_date} was included for cash "
                    "runway estimation."
                ),
                source=financial_snapshot.source,
                source_date=financial_snapshot.source_date,
                confidence=0.7,
            ),
        )

    decision = "watchlist" if trials or pipeline_assets else "insufficient_data"
    action_plan: ResearchActionPlan | None = None
    if target_price_analysis:
        action_plan = build_research_action_plan(
            decision=decision,
            target_price_analysis=target_price_analysis,
            runway_months=(
                cash_runway_estimate.runway_months
                if cash_runway_estimate is not None
                else None
            ),
        )
        findings.append(
            research_action_plan_finding(
                company=context.company,
                plan=action_plan,
                currency=target_price_analysis.currency,
            )
        )
    summary = (
        f"首轮研究在 ClinicalTrials.gov 发现 {len(trials)} 条与 {context.company} 相关记录，"
        f"已接收 {len(pipeline_assets)} 条披露管线资产输入，并形成 {len(asset_trial_matches)} 条"
        "资产-试验匹配。当前仍是部分视图，投资判断前需继续交叉核验公司披露、HKEX 公告、"
            "中国注册库、现金流与竞争数据。"
    )
    if not trials and not pipeline_assets:
        summary = (
            f"首轮检索未在 ClinicalTrials.gov 找到 {context.company} 的有效记录。"
            "公司仍可能存在中国本土注册、合作方登记或别名资产，需补充来源后复核。"
        )
    elif pipeline_assets and not asset_trial_matches:
        summary += (
            " 当前提供的资产未与试验干预或标题形成匹配，资产命名、别名与中国本土注册需人工复核。"
        )
    if competitor_assets:
        summary += (
            f" 竞争输入包含 {len(competitor_assets)} 条竞品资产，并形成 {len(competitive_matches)} 条确定性匹配。"
        )
    if cash_runway_estimate and cash_runway_estimate.runway_months is not None:
        summary += (
            f" 现金流可持续期估算约为 {cash_runway_estimate.runway_months:.1f} 个月。"
        )
    if valuation_metrics:
        summary += (
            f" 企业价值估算约为 {valuation_metrics.enterprise_value:g} {valuation_metrics.currency}。"
        )
    if target_price_analysis:
        summary += (
            f" 催化剂调整后概率加权目标价约为 "
            f"{target_price_analysis.probability_weighted_target_price:.2f} "
            f"{target_price_analysis.currency}，对应隐含涨跌幅 "
            f"{target_price_analysis.implied_upside_downside_pct:.1f}%。"
        )

    return InvestmentMemo(
        company=context.company,
        ticker=context.ticker,
        market=context.market,
        decision=decision,
        summary=summary,
        bull_case=_default_bull_case(
            company=context.company,
            trials=trials,
            pipeline_assets=pipeline_assets,
            asset_trial_matches=asset_trial_matches,
            competitor_assets=competitor_assets,
            competitive_matches=competitive_matches,
            cash_runway_estimate=cash_runway_estimate,
            target_price_analysis=target_price_analysis,
        ),
        bear_case=(
            "仅依赖 ClinicalTrials.gov 对港股/中国生物科技覆盖并不完整。",
            "存在注册记录不等于疗效、安全性、获批概率或商业价值已被验证。",
        ),
        key_assets=_rank_core_assets(
            pipeline_assets=pipeline_assets,
            asset_trial_matches=asset_trial_matches,
        ),
        catalysts=catalysts,
        findings=tuple(findings),
        follow_up_questions=(
            "收集最新年报/中报、招股书、路演材料与 HKEX 公告。",
            "按公司中文名、资产代号与核心适应症检索中国药物试验注册记录。",
            "将披露管线资产映射到试验记录，识别缺失核心产品。",
            "基于最新财报估算现金流与融资风险。",
            "在使用任何价格区间前，先复核催化剂调整后的目标价假设。",
        ),
        evidence=evidence,
    )


def _rank_core_assets(
    *,
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
) -> tuple[PipelineAsset, ...]:
    if not pipeline_assets:
        return ()
    match_count_by_asset: dict[str, int] = {}
    for match in asset_trial_matches:
        key = match.asset_name.casefold()
        match_count_by_asset[key] = match_count_by_asset.get(key, 0) + 1
    phase2_plus = tuple(asset for asset in pipeline_assets if _is_phase2_plus(asset.phase))
    population = phase2_plus or pipeline_assets
    ranked = sorted(
        population,
        key=lambda asset: (
            -_phase_rank_for_deep_dive(asset.phase),
            -match_count_by_asset.get(asset.name.casefold(), 0),
            asset.name.casefold(),
        ),
    )
    return tuple(ranked[:3])


def _valuation_process_finding(
    *,
    company: str,
    valuation_snapshot: ValuationSnapshot | None,
    valuation_metrics: ValuationMetrics | None,
    target_price_analysis: TargetPriceAnalysis,
) -> AgentFinding:
    details: list[str] = [
        "计算框架：企业价值(EV)=市值+总债务-现金及等价物。",
    ]
    if valuation_snapshot is not None:
        details.append(
            f"输入快照：市值={getattr(valuation_snapshot, 'market_cap', None)}，"
            f"债务={valuation_snapshot.total_debt:g}，现金={valuation_snapshot.cash_and_equivalents:g} "
            f"{valuation_snapshot.currency}。"
        )
    if valuation_metrics is not None:
        details.append(
            f"结果：EV={valuation_metrics.enterprise_value:g} {valuation_metrics.currency}。"
        )

    details.append(
        "目标价框架：概率加权目标价="
        "(悲观目标价×25%)+(基准目标价×50%)+(乐观目标价×25%)。"
    )
    details.append(
        f"rNPV口径净现金（并入股权价值）={target_price_analysis.base.net_cash:.0f} "
        f"{target_price_analysis.currency}。"
    )
    details.append(
        f"本次计算：悲观/基准/乐观={target_price_analysis.bear.target_price:.2f}/"
        f"{target_price_analysis.base.target_price:.2f}/"
        f"{target_price_analysis.bull.target_price:.2f} "
        f"{target_price_analysis.currency}，概率加权="
        f"{target_price_analysis.probability_weighted_target_price:.2f} "
        f"{target_price_analysis.currency}。"
    )
    base_assets = sorted(
        target_price_analysis.base.asset_rnpv,
        key=lambda item: item.rnpv,
        reverse=True,
    )[:3]
    for asset in base_assets:
        details.append(
            f"rNPV分解（基准）：{asset.asset_name}={asset.rnpv:.0f} "
            f"{target_price_analysis.currency} "
            f"(PoS={asset.probability_of_success:.2f}, 峰值销售={asset.peak_sales:.0f}, "
            f"利润率={asset.operating_margin:.2f}, 折现率={asset.discount_rate:.2f}, "
            f"距上市年数={asset.years_to_launch})。"
        )

    return AgentFinding(
        agent_name="valuation_process_agent",
        summary=f"{company} 估值过程已拆解为 EV 计算 + rNPV 场景加权目标价。",
        risks=tuple(details),
        confidence=0.65,
        needs_human_review=True,
    )


def _default_bull_case(
    *,
    company: str,
    trials: tuple[TrialSummary, ...],
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    competitive_matches: tuple[CompetitiveMatch, ...],
    cash_runway_estimate: CashRunwayEstimate | None,
    target_price_analysis: TargetPriceAnalysis | None,
) -> tuple[str, ...]:
    points: list[str] = []
    if trials:
        phase2_plus = sum(
            1
            for trial in trials
            if (trial.phase and ("PHASE2" in trial.phase or "PHASE3" in trial.phase))
        )
        points.append(
            f"注册库已覆盖 {len(trials)} 项相关试验，其中二/三期 {phase2_plus} 项，具备持续跟踪锚点。"
        )
    if pipeline_assets:
        matched_assets = {match.asset_name for match in asset_trial_matches}
        points.append(
            f"已披露管线 {len(pipeline_assets)} 项，已有 {len(matched_assets)} 项与注册试验形成映射。"
        )
    if competitor_assets:
        points.append(
            f"竞品输入覆盖 {len(competitor_assets)} 项，并形成 {len(competitive_matches)} 条可比匹配，可用于验证差异化。"
        )
    if (
        cash_runway_estimate is not None
        and cash_runway_estimate.runway_months is not None
    ):
        points.append(
            f"{company} 现金流可持续期约 {cash_runway_estimate.runway_months:.1f} 个月，具备推进关键里程碑的资金缓冲。"
        )
    if target_price_analysis is not None:
        points.append(
            f"已形成催化剂调整后的目标价框架（基准 {target_price_analysis.base.target_price:.2f} "
            f"{target_price_analysis.currency}），便于后续随数据读出动态修正。"
        )
    if not points:
        return ("当前数据源尚不足以形成注册库支撑的看多论据。",)
    return tuple(points[:4])


def _is_phase2_plus(phase: str | None) -> bool:
    lowered = (phase or "").casefold()
    return any(
        token in lowered
        for token in ("phase 2", "phase ii", "phase 3", "phase iii", "bla")
    )


def _phase_rank_for_deep_dive(phase: str | None) -> int:
    lowered = (phase or "").casefold()
    if "bla under review" in lowered or "bla accepted" in lowered:
        return 6
    if "bla" in lowered:
        return 5
    if "phase 3" in lowered or "phase iii" in lowered:
        return 4
    if "phase 2" in lowered or "phase ii" in lowered:
        return 3
    if "phase 1" in lowered or "phase i" in lowered:
        return 2
    if lowered:
        return 1
    return 0


def _derive_clinical_catalysts(
    trials: tuple[TrialSummary, ...],
    *,
    today: date,
) -> tuple[Catalyst, ...]:
    catalysts: list[Catalyst] = []
    for trial in trials:
        expected_date = _parse_date(trial.primary_completion_date)
        if not expected_date or expected_date < today:
            continue

        title = "注册临床试验主要完成日期"
        related_asset = trial.interventions[0] if trial.interventions else None
        catalysts.append(
            Catalyst(
                title=title,
                category="clinical",
                expected_date=expected_date,
                related_asset=related_asset,
                confidence=0.65,
                evidence=(
                    Evidence(
                        claim=(
                            f"{trial.registry_id} lists primary completion date "
                            f"{trial.primary_completion_date}."
                        ),
                        source=_clinicaltrials_url(trial.registry_id),
                        source_date=trial.last_update_posted,
                        confidence=0.75,
                    ),
                ),
            )
        )

    return tuple(sorted(catalysts, key=lambda item: item.expected_date or date.max))


def _derive_asset_milestone_catalysts(
    assets: tuple[PipelineAsset, ...],
) -> tuple[Catalyst, ...]:
    catalysts: list[Catalyst] = []
    for asset in assets:
        if not asset.next_milestone:
            continue
        catalysts.append(
            Catalyst(
                title=f"公司披露的下一里程碑：{asset.next_milestone}",
                category="clinical",
                expected_window=asset.next_milestone,
                related_asset=asset.name,
                confidence=0.45,
                evidence=asset.evidence,
            )
        )
    return tuple(catalysts)


def _build_pipeline_match_finding(
    *,
    context: AgentContext,
    assets: tuple[PipelineAsset, ...],
    matches: tuple[TrialAssetMatch, ...],
) -> AgentFinding:
    matched_assets = {match.asset_name for match in matches}
    unmatched_assets = tuple(
        asset.name for asset in assets if asset.name not in matched_assets
    )
    risks = ()
    if unmatched_assets:
        risks = ("以下披露资产未通过名称或别名匹配到 ClinicalTrials.gov：" + ", ".join(unmatched_assets),)

    return AgentFinding(
        agent_name="pipeline_matcher",
        summary=(
            f"{context.company} 当前输入含 {len(assets)} 条披露管线资产；"
            f"{len(matched_assets)} 条资产与 {len(matches)} 条 ClinicalTrials.gov 记录"
            "在干预项或标题维度形成匹配。"
        ),
        risks=risks,
        evidence=tuple(
            Evidence(
                claim=(
                    f"{match.asset_name} matched {match.registry_id} via "
                    f"{match.match_reason}: {match.matched_text}"
                ),
                source=_clinicaltrials_url(match.registry_id),
                confidence=match.confidence,
                is_inferred=True,
            )
            for match in matches
        ),
        confidence=0.65 if matches else 0.3,
        needs_human_review=bool(unmatched_assets),
    )


def _build_data_quality_finding(
    *,
    context: AgentContext,
    pipeline_assets: tuple[PipelineAsset, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    financial_snapshot: FinancialSnapshot | None,
    valuation_snapshot: ValuationSnapshot | None,
    input_validation: dict[str, Any],
) -> AgentFinding:
    risks: list[str] = []
    if not pipeline_assets:
        risks.append("未提供结构化管线资产输入")
    if not financial_snapshot:
        risks.append("未提供财务快照输入")
    if not valuation_snapshot:
        risks.append("未提供估值快照输入")
    if not competitor_assets:
        risks.append("未提供结构化竞争格局输入")

    warning_count = _input_warning_count(input_validation)
    if warning_count:
        risks.append(f"输入校验产生 {warning_count} 条告警")

    return AgentFinding(
        agent_name="data_quality_agent",
        summary=(
            f"{context.company} input quality check found {len(risks)} "
            "open data-quality issue(s)."
        ),
        risks=tuple(risks),
        confidence=0.8,
        needs_human_review=bool(risks),
    )


def _write_research_artifacts(
    *,
    output_dir: Path,
    company: str,
    ticker: str | None,
    market: str,
    run_id: str,
    search_terms: tuple[str, ...],
    retrieved_at: str,
    api_version: dict[str, Any],
    raw_responses: dict[str, dict[str, Any]],
    trials: tuple[TrialSummary, ...],
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    competitive_matches: tuple[CompetitiveMatch, ...],
    financial_snapshot: FinancialSnapshot | None,
    cash_runway_estimate: CashRunwayEstimate | None,
    valuation_snapshot: ValuationSnapshot | None,
    valuation_metrics: ValuationMetrics | None,
    target_price_assumptions: TargetPriceAssumptions | None,
    target_price_analysis: TargetPriceAnalysis | None,
    scorecard: WatchlistScorecard,
    action_plan: ResearchActionPlan | None,
    input_validation: dict[str, Any],
    memo: InvestmentMemo,
) -> ResearchArtifacts:
    slug = _slugify(ticker or company)
    raw_dir = output_dir / "raw" / "clinicaltrials" / slug
    processed_dir = output_dir / "processed" / "single_company" / slug
    memo_dir = output_dir / "memos" / slug
    for directory in (raw_dir, processed_dir, memo_dir):
        directory.mkdir(parents=True, exist_ok=True)

    raw_path = raw_dir / f"{run_id}_search.json"
    manifest_json_path = processed_dir / f"{run_id}_manifest.json"
    trials_path = processed_dir / f"{run_id}_trials.json"
    trial_summary_csv_path = processed_dir / f"{run_id}_trial_summary.csv"
    catalyst_calendar_csv_path = processed_dir / f"{run_id}_catalyst_calendar.csv"
    pipeline_assets_path = processed_dir / f"{run_id}_pipeline_assets.json"
    asset_trial_matches_path = processed_dir / f"{run_id}_asset_trial_matches.json"
    competitor_assets_path = processed_dir / f"{run_id}_competitor_assets.json"
    competitive_matches_path = processed_dir / f"{run_id}_competitive_matches.json"
    cash_runway_path = processed_dir / f"{run_id}_cash_runway.json"
    valuation_path = processed_dir / f"{run_id}_valuation.json"
    scorecard_path = processed_dir / f"{run_id}_scorecard.json"
    event_impact_path = processed_dir / f"{run_id}_event_impact.json"
    target_price_scenarios_path = (
        processed_dir / f"{run_id}_target_price_scenarios.json"
    )
    target_price_summary_csv_path = (
        processed_dir / f"{run_id}_target_price_summary.csv"
    )
    memo_json_path = processed_dir / f"{run_id}_memo.json"
    memo_markdown_path = memo_dir / f"{run_id}_memo.md"

    _write_json(
        raw_path,
        {
            "company": company,
            "ticker": ticker,
            "market": market,
            "search_terms": search_terms,
            "retrieved_at": retrieved_at,
            "api_version": api_version,
            "responses": raw_responses,
        },
    )
    _write_json(
        trials_path,
        {
            "company": company,
            "ticker": ticker,
            "market": market,
            "search_terms": search_terms,
            "retrieved_at": retrieved_at,
            "trials": summaries_as_dicts(list(trials)),
        },
    )
    write_trial_summary_csv(path=trial_summary_csv_path, trials=trials)
    write_catalyst_calendar_csv(
        path=catalyst_calendar_csv_path,
        catalysts=memo.catalysts,
    )
    _write_json(
        pipeline_assets_path,
        {
            "company": company,
            "ticker": ticker,
            "market": market,
            "retrieved_at": retrieved_at,
            "assets": [asdict(asset) for asset in pipeline_assets],
        },
    )
    _write_json(
        asset_trial_matches_path,
        {
            "company": company,
            "ticker": ticker,
            "market": market,
            "retrieved_at": retrieved_at,
            "matches": [asdict(match) for match in asset_trial_matches],
        },
    )
    _write_json(
        competitor_assets_path,
        {
            "company": company,
            "ticker": ticker,
            "market": market,
            "retrieved_at": retrieved_at,
            "competitors": [asdict(item) for item in competitor_assets],
        },
    )
    _write_json(
        competitive_matches_path,
        {
            "company": company,
            "ticker": ticker,
            "market": market,
            "retrieved_at": retrieved_at,
            "matches": [asdict(match) for match in competitive_matches],
        },
    )
    if financial_snapshot and cash_runway_estimate:
        _write_json(
            cash_runway_path,
            cash_runway_payload(financial_snapshot, cash_runway_estimate),
        )
    if valuation_snapshot and valuation_metrics:
        _write_json(
            valuation_path,
            valuation_payload(valuation_snapshot, valuation_metrics),
        )
    if target_price_assumptions and target_price_analysis:
        _write_json(
            event_impact_path,
            event_impact_payload(target_price_assumptions, target_price_analysis),
        )
        _write_json(
            target_price_scenarios_path,
            target_price_payload(target_price_assumptions, target_price_analysis),
        )
        write_target_price_summary_csv(
            target_price_summary_csv_path,
            target_price_analysis,
        )
    _write_json(scorecard_path, scorecard_payload(scorecard))
    _write_json(memo_json_path, asdict(memo))
    memo_markdown_path.write_text(memo_to_markdown(memo), encoding="utf-8")

    artifacts = ResearchArtifacts(
        manifest_json=manifest_json_path,
        raw_clinical_trials=raw_path,
        normalized_trials=trials_path,
        trial_summary_csv=trial_summary_csv_path,
        catalyst_calendar_csv=catalyst_calendar_csv_path,
        pipeline_assets=pipeline_assets_path,
        asset_trial_matches=asset_trial_matches_path,
        competitor_assets=competitor_assets_path,
        competitive_matches=competitive_matches_path,
        cash_runway=(
            cash_runway_path
            if financial_snapshot and cash_runway_estimate
            else None
        ),
        valuation=(
            valuation_path
            if valuation_snapshot and valuation_metrics
            else None
        ),
        scorecard=scorecard_path,
        event_impact=(
            event_impact_path
            if target_price_assumptions and target_price_analysis
            else None
        ),
        target_price_scenarios=(
            target_price_scenarios_path
            if target_price_assumptions and target_price_analysis
            else None
        ),
        target_price_summary_csv=(
            target_price_summary_csv_path
            if target_price_assumptions and target_price_analysis
            else None
        ),
        memo_json=memo_json_path,
        memo_markdown=memo_markdown_path,
    )
    _write_json(
        manifest_json_path,
        {
            "run_id": run_id,
            "company": company,
            "ticker": ticker,
            "market": market,
            "retrieved_at": retrieved_at,
            "search_terms": search_terms,
            "api_version": api_version,
            "input_validation": input_validation,
            "quality_gate": _quality_gate_from_run(
                pipeline_assets=pipeline_assets,
                competitor_assets=competitor_assets,
                financial_snapshot=financial_snapshot,
                valuation_snapshot=valuation_snapshot,
                input_validation=input_validation,
                memo=memo,
            ),
            "counts": {
                "trials": len(trials),
                "pipeline_assets": len(pipeline_assets),
                "asset_trial_matches": len(asset_trial_matches),
                "competitor_assets": len(competitor_assets),
                "competitive_matches": len(competitive_matches),
                "cash_runway": 1 if cash_runway_estimate else 0,
                "valuation": 1 if valuation_metrics else 0,
                "target_price": 1 if target_price_analysis else 0,
                "scorecard": 1,
                "catalysts": len(memo.catalysts),
                "evidence": len(memo.evidence),
            },
            "scorecard_dimensions": _scorecard_dimensions_payload(scorecard),
            "research_action_plan": _action_plan_payload(action_plan),
            "artifacts": _jsonable(asdict(artifacts)),
        },
    )
    return artifacts


def _quality_gate_from_run(
    *,
    pipeline_assets: tuple[PipelineAsset, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    financial_snapshot: FinancialSnapshot | None,
    valuation_snapshot: ValuationSnapshot | None,
    input_validation: dict[str, Any],
    memo: InvestmentMemo,
) -> dict[str, Any]:
    missing_high = 0
    missing_medium = 0
    if not pipeline_assets:
        missing_high += 1
    if financial_snapshot is None:
        missing_high += 1
    if not competitor_assets:
        missing_medium += 1
    if valuation_snapshot is None:
        missing_medium += 1
    warning_count = _input_warning_count(input_validation)
    needs_human_review = any(
        finding.needs_human_review for finding in memo.findings
    )
    if missing_high > 0:
        level = "incomplete"
        rationale = "high-severity curated inputs are missing"
    elif needs_human_review or warning_count > 0 or missing_medium > 0:
        level = "research_ready_with_review"
        rationale = "report generated but requires manual review"
    else:
        level = "decision_ready"
        rationale = "required inputs and checks are in acceptable shape"
    return {
        "level": level,
        "rationale": rationale,
        "missing_high_severity_inputs": missing_high,
        "missing_medium_severity_inputs": missing_medium,
        "input_warning_count": warning_count,
        "needs_human_review": needs_human_review,
    }


def _scorecard_dimensions_payload(scorecard: WatchlistScorecard) -> list[dict[str, Any]]:
    total_weight = (
        sum(max(dimension.weight, 0.0) for dimension in scorecard.dimensions) or 1.0
    )
    rows: list[dict[str, Any]] = []
    for dimension in scorecard.dimensions:
        normalized_weight = max(dimension.weight, 0.0) / total_weight
        rows.append(
            {
                "name": dimension.name,
                "score": round(dimension.score, 2),
                "weight": round(dimension.weight, 4),
                "contribution": round(dimension.score * normalized_weight, 2),
                "rationale": dimension.rationale,
            }
        )
    return rows


def _action_plan_payload(action_plan: ResearchActionPlan | None) -> dict[str, Any] | None:
    if action_plan is None:
        return None
    return {
        "guidance_type": action_plan.guidance_type,
        "suggested_position_pct": round(action_plan.suggested_position_pct, 2),
        "entry_zone_low": action_plan.entry_zone_low,
        "entry_zone_high": action_plan.entry_zone_high,
        "exit_trigger_conditions": list(action_plan.exit_trigger_conditions),
        "notes": list(action_plan.notes),
        "needs_human_review": action_plan.needs_human_review,
    }


def _deep_dive_competitive_lines(
    *,
    asset_name: str,
    competition_findings: tuple[AgentFinding, ...],
) -> list[str]:
    lines: list[str] = []
    asset_key = asset_name.casefold()
    for finding in competition_findings:
        for evidence in finding.evidence:
            claim = evidence.claim.strip()
            if not claim:
                continue
            if not claim.casefold().startswith(asset_key + " matched competitor"):
                continue
            sentence = claim
            if sentence.endswith("."):
                sentence = sentence[:-1]
            lines.append(f"差异化要点：{sentence}。")
            if len(lines) >= 1:
                return lines
    return lines


def _scorecard_lift_target_lines(
    scorecard_findings: tuple[AgentFinding, ...],
) -> list[str]:
    rows: list[tuple[float, str, str]] = []
    for finding in scorecard_findings:
        for risk in finding.risks:
            parsed = _parse_scorecard_dimension_risk(risk)
            if parsed:
                rows.append(parsed)
    if not rows:
        return []
    ordered = sorted(rows, key=lambda item: item[0])[:3]
    lines = ["", "### 路径：提升至核心候选"]
    for contribution, name, rationale in ordered:
        lines.append(
            f"- {_dimension_name_zh(name)}：贡献度 {contribution:.1f}；优先补强证据：{rationale}"
        )
    return lines


def _parse_scorecard_dimension_risk(text: str) -> tuple[float, str, str] | None:
    match = re.match(
        r"^(.+?)\s+\(score=.*?contribution=([0-9]+(?:\.[0-9]+)?)\):\s+(.+)$",
        text.strip(),
    )
    if not match:
        return None
    name = match.group(1).strip()
    contribution = float(match.group(2))
    rationale = match.group(3).strip()
    return (contribution, name, rationale)


def _dimension_name_zh(name: str) -> str:
    mapping = {
        "clinical_progress": "临床进展",
        "pipeline_registry_match": "管线-注册匹配",
        "cash_runway": "现金流可持续期",
        "competition": "竞争格局",
        "valuation": "估值",
        "data_quality": "数据质量",
        "skeptical_review": "反证审阅",
    }
    return mapping.get(name.strip(), name)


def _format_section_risk(text: str) -> str:
    risk = str(text or "").strip()
    if not risk:
        return "该风险条目为空，需人工复核。"
    if "让我重新计算" in risk or "等等" in risk or len(risk) > 220:
        return "该风险原文过长或质量不稳定，请回看原始来源并人工复核。"
    replacements = {
        "revenue_ttm unavailable; revenue multiple not calculated": "营收TTM不可用，无法计算营收倍数",
        "[runway_sanity] inconsistent": "[runway_sanity] 不一致",
        "Operating Cash Flow": "经营现金流",
        "Revenue TTM": "营收TTM",
        "monthly_cash_burn": "月度现金消耗",
    }
    for src, dst in replacements.items():
        risk = risk.replace(src, dst)
    return risk


def _phase_label_zh(phase: str | None) -> str:
    text = str(phase or "").strip()
    lowered = text.casefold()
    if "phase 3" in lowered or "phase iii" in lowered:
        return "三期"
    if "phase 2" in lowered or "phase ii" in lowered:
        return "二期"
    if "phase 1" in lowered or "phase i" in lowered:
        return "一期"
    if "bla" in lowered:
        return "BLA阶段"
    return text or "未披露"


def _bucket_zh(bucket: str) -> str:
    mapping = {
        "near_term_0_6m": "近端(0-6个月)",
        "mid_term_6_18m": "中期(6-18个月)",
        "long_term_18m_plus": "远期(18个月以上)",
        "timing_tbd": "时间待定",
    }
    return mapping.get(bucket, bucket)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _trial_evidence(trial: TrialSummary, retrieved_at: str) -> Evidence:
    details = []
    if trial.status:
        details.append(f"status {trial.status}")
    if trial.phase:
        details.append(f"phase {trial.phase}")
    if trial.primary_completion_date:
        details.append(f"primary completion {trial.primary_completion_date}")
    suffix = "; ".join(details) if details else "registry record captured"
    return Evidence(
        claim=f"{trial.registry_id}: {trial.title} ({suffix}).",
        source=_clinicaltrials_url(trial.registry_id),
        source_date=trial.last_update_posted,
        retrieved_at=retrieved_at,
        confidence=0.8,
    )


def _clinicaltrials_url(registry_id: str) -> str:
    return f"https://clinicaltrials.gov/study/{registry_id}"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "company"


def _bullet_lines(values: tuple[str, ...]) -> list[str]:
    if not values:
        return ["- 暂无可用内容。"]
    return [f"- {value}" for value in values]


def _findings_for(
    findings: tuple[AgentFinding, ...],
    kind: str,
) -> tuple[AgentFinding, ...]:
    kind_key = kind.casefold()
    selected: list[AgentFinding] = []
    for finding in findings:
        name = finding.agent_name.casefold()
        if kind_key == "skeptic" and "skeptic" in name:
            selected.append(finding)
        elif kind_key == "pipeline_triage" and "pipeline_triage" in name:
            selected.append(finding)
        elif kind_key == "competition" and (
            "competition" in name or "competitive_landscape" in name
        ):
            selected.append(finding)
        elif kind_key == "financial" and (
            "financial" in name or "cash_runway" in name or "valuation_agent" in name
        ):
            selected.append(finding)
        elif kind_key == "target_price" and "target_price" in name:
            selected.append(finding)
        elif kind_key == "valuation_process" and "valuation_process" in name:
            selected.append(finding)
        elif kind_key == "valuation_specialist" and "valuation_specialist" in name:
            selected.append(finding)
        elif kind_key == "watchlist_scorecard" and "watchlist_scorecard" in name:
            selected.append(finding)
        elif kind_key == "investment_thesis" and "investment_thesis" in name:
            selected.append(finding)
        elif kind_key == "research_action_plan" and "research_action_plan" in name:
            selected.append(finding)
    return tuple(selected)


def _catalyst_lines(
    catalysts: tuple[Catalyst, ...],
    *,
    key_assets: tuple[PipelineAsset, ...] = (),
) -> list[str]:
    if not catalysts:
        return ["- 暂未捕捉到催化剂。"]
    phase_by_asset = {
        asset.name.casefold(): asset.phase for asset in key_assets if asset.name
    }
    ordered = sorted(
        _catalyst_rank_rows(catalysts, phase_by_asset=phase_by_asset),
        key=lambda row: (
            _catalyst_bucket_rank(row["bucket"]),
            -row["impact_score"],
            row["date_sort"],
            row["window_sort"],
            row["title_sort"],
        ),
    )
    lines: list[str] = []
    for row in ordered:
        catalyst = row["catalyst"]
        expected_pos = row["expected_pos"]
        expected_delta = row["expected_delta"]
        bucket = row["bucket"]
        impact_score = row["impact_score"]
        when = row["when"]
        asset = row["asset_suffix"]
        lines.append(
            f"- [{_bucket_zh(bucket)}；影响分={impact_score:.1f}] {when}："
            f"{catalyst.title}{asset} "
            f"(预期成功概率 {expected_pos:.2f}，"
            f"预期价值变化 {expected_delta:+.1f}%)"
        )
    return lines


def _catalyst_rank_rows(
    catalysts: tuple[Catalyst, ...],
    *,
    phase_by_asset: dict[str, str | None],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for catalyst in catalysts:
        phase = phase_by_asset.get((catalyst.related_asset or "").casefold())
        expected_pos = _catalyst_expected_pos(catalyst, phase=phase)
        expected_delta = _catalyst_expected_value_delta_pct(catalyst, phase=phase)
        bucket = _catalyst_time_bucket(catalyst)
        when = catalyst.expected_date.isoformat() if catalyst.expected_date else "TBD"
        if catalyst.expected_window:
            when = catalyst.expected_window
        rows.append(
            {
                "catalyst": catalyst,
                "expected_pos": expected_pos,
                "expected_delta": expected_delta,
                "bucket": bucket,
                "impact_score": abs(expected_delta) * expected_pos,
                "date_sort": (
                    catalyst.expected_date.isoformat()
                    if catalyst.expected_date
                    else "9999-12-31"
                ),
                "window_sort": catalyst.expected_window or "ZZZ",
                "title_sort": catalyst.title,
                "when": when,
                "asset_suffix": (
                    f" ({catalyst.related_asset})"
                    if catalyst.related_asset
                    else ""
                ),
            }
        )
    return rows


def _phase_success_default(phase: str | None) -> float:
    lowered = (phase or "").casefold()
    if "bla under review" in lowered or "bla accepted" in lowered:
        return 0.85
    if "bla" in lowered:
        return 0.7
    if "phase 3" in lowered or "phase iii" in lowered:
        return 0.55
    if "phase 2" in lowered or "phase ii" in lowered:
        return 0.3
    if "phase 1" in lowered or "phase i" in lowered:
        return 0.12
    if "ind" in lowered:
        return 0.08
    if "pcc" in lowered:
        return 0.03
    if "preclinical" in lowered:
        return 0.01
    return 0.2


def _catalyst_expected_pos(catalyst: Catalyst, *, phase: str | None) -> float:
    base = _phase_success_default(phase)
    category = catalyst.category
    if category == "conference":
        base *= 0.8
    elif category == "regulatory":
        base = min(base + 0.1, 0.9)
    elif category == "financial":
        base *= 0.7
    elif category == "clinical":
        base *= 1.0
    return max(0.05, min(base, 0.9))


def _catalyst_expected_value_delta_pct(
    catalyst: Catalyst, *, phase: str | None
) -> float:
    category_base = {
        "regulatory": 25.0,
        "clinical": 18.0,
        "conference": 8.0,
        "financial": 10.0,
        "commercial": 12.0,
        "corporate": 10.0,
        "unknown": 6.0,
    }.get(catalyst.category, 6.0)
    phase_weight = {
        "late": 1.0,
        "mid": 0.7,
        "early": 0.45,
        "pre": 0.25,
        "unknown": 0.5,
    }[_phase_weight_bucket(phase)]
    return category_base * phase_weight


def _phase_weight_bucket(phase: str | None) -> str:
    lowered = (phase or "").casefold()
    if any(term in lowered for term in ("bla", "phase 3", "phase iii")):
        return "late"
    if "phase 2" in lowered or "phase ii" in lowered:
        return "mid"
    if "phase 1" in lowered or "phase i" in lowered:
        return "early"
    if any(term in lowered for term in ("ind", "pcc", "preclinical")):
        return "pre"
    return "unknown"


def _catalyst_time_bucket(catalyst: Catalyst) -> str:
    if catalyst.expected_date is None:
        return "timing_tbd"
    delta_days = (catalyst.expected_date - date.today()).days
    if delta_days <= 180:
        return "near_term_0_6m"
    if delta_days <= 540:
        return "mid_term_6_18m"
    return "long_term_18m_plus"


def _catalyst_bucket_rank(bucket: str) -> int:
    if bucket == "near_term_0_6m":
        return 0
    if bucket == "mid_term_6_18m":
        return 1
    if bucket == "long_term_18m_plus":
        return 2
    return 3


def _finding_risk_lines(findings: tuple[AgentFinding, ...]) -> list[str]:
    risk_rows: list[str] = []
    for finding in findings:
        for risk in finding.risks:
            normalized = risk.strip()
            if not normalized:
                continue
            if _should_tag_llm_triage_risk(finding=finding, risk=normalized):
                normalized = f"{normalized} (source: llm[{finding.agent_name}])"
            risk_rows.append(normalized)
    if not risk_rows:
        return ["- 暂无智能体级别风险。"]
    deduped = _semantic_dedupe_risks(risk_rows)
    ordered = sorted(deduped, key=_risk_sort_key)
    return [f"- {risk}" for risk in ordered]


def _semantic_dedupe_risks(risk_rows: list[str]) -> list[str]:
    deduped: list[str] = []
    seen_raw: set[str] = set()
    seen_semantic: set[str] = set()
    for risk in risk_rows:
        raw_key = risk.casefold().strip()
        if raw_key in seen_raw:
            continue
        seen_raw.add(raw_key)
        semantic_key = _risk_semantic_key(risk)
        if semantic_key in seen_semantic:
            continue
        seen_semantic.add(semantic_key)
        deduped.append(risk)
    return deduped


def _risk_semantic_key(risk: str) -> str:
    lowered = risk.casefold()
    canonical = (
        lowered.replace("insufficient_data", "missing data")
        .replace("insufficient data", "missing data")
        .replace("missing input", "missing data")
        .replace("input missing", "missing data")
        .replace("no curated", "missing curated")
        .replace("not available", "missing data")
        .replace("unavailable", "missing data")
        .replace("not provided", "missing data")
    )
    canonical = re.sub(r"\(source:\s*llm\[[^)]+\]\)", "", canonical)
    canonical = re.sub(r"\[[^\]]+\]", " ", canonical)
    canonical = re.sub(r"[^a-z0-9\s]+", " ", canonical)
    canonical = re.sub(r"\s+", " ", canonical).strip()
    return canonical


def _executive_observation_lines(
    *, memo: InvestmentMemo, findings: tuple[AgentFinding, ...]
) -> list[str]:
    observations: list[str] = []
    for catalyst in memo.catalysts[:2]:
        label = catalyst.expected_date.isoformat() if catalyst.expected_date else (
            catalyst.expected_window or "timing TBD"
        )
        observations.append(f"关注催化剂时点：{catalyst.title}（{label}）。")
    for finding in findings:
        summary = finding.summary.strip()
        if summary:
            observations.append(summary)
        if len(observations) >= 6:
            break
    compact = []
    for line in observations:
        text = line.strip()
        if text and text not in compact:
            compact.append(text)
    while len(compact) < 3:
        compact.append(
            "在调整观点前，先验证不确定性最高的核心假设。"
        )
    lines = ["### 可执行观察"]
    lines.extend(f"- {item}" for item in compact[:3])
    lines.extend(["", "### 关键不确定性"])
    risk_bullets = _finding_risk_lines(findings)
    if risk_bullets and not risk_bullets[0].startswith("- 暂无智能体级别风险"):
        lines.extend(risk_bullets[:3])
    else:
        lines.extend(
            [
                "- 临床数据覆盖可能仍不完整（跨注册库差异）。",
                "- 缺少财务披露时，现金流可持续期判断置信度偏低。",
                "- 随着同类读出更新，竞争位次可能快速变化。",
            ]
        )
    lines.append("")
    return lines


def _risk_sort_key(risk: str) -> tuple[int, str]:
    lowered = risk.casefold()
    if "[high]" in lowered:
        rank = 0
    elif "[medium]" in lowered:
        rank = 1
    elif "[low]" in lowered:
        rank = 2
    else:
        rank = 3
    return (rank, lowered)


def _should_tag_llm_triage_risk(*, finding: AgentFinding, risk: str) -> bool:
    name = finding.agent_name.casefold()
    if "triage" not in name:
        return False
    if finding.confidence < 0.4:
        return False
    lowered = risk.casefold()
    return "[high]" in lowered or "[medium]" in lowered


def _clinical_data_line(datum: Any) -> str:
    metric = getattr(datum, "metric", None)
    value = getattr(datum, "value", None)
    unit = getattr(datum, "unit", None)
    sample_size = getattr(datum, "sample_size", None)
    context = getattr(datum, "context", None)
    if metric:
        value_part = f" {value}" if value else ""
        unit_part = unit or ""
        n_part = f" (n={sample_size})" if sample_size else ""
        context_part = f"; {context}" if context else ""
        return f"{metric}{value_part}{unit_part}{n_part}{context_part}".strip()
    text = str(datum).strip()
    return text or "clinical datapoint"


def _research_only_action_plan_lines(
    *,
    decision: str,
    valuation_findings: tuple[AgentFinding, ...],
    scorecard_findings: tuple[AgentFinding, ...],
    action_plan_findings: tuple[AgentFinding, ...],
) -> list[str]:
    if action_plan_findings:
        lines: list[str] = []
        for finding in action_plan_findings:
            lines.append(f"- {finding.summary}")
            selected_risks = list(finding.risks[:4])
            if not any("仅供研究支持" in risk for risk in selected_risks):
                for risk in finding.risks:
                    if "仅供研究支持" in risk:
                        selected_risks.append(risk)
                        break
            lines.extend(f"  - {risk}" for risk in selected_risks)
        return lines
    plan: list[str] = []
    sizing_map = {
        "core_candidate": "2.0% to 4.0%",
        "watchlist": "0.5% to 1.5%",
        "avoid": "0.0%",
        "insufficient_data": "0.0%",
    }
    plan.append(
        f"- 建议研究仓位区间：{sizing_map.get(decision, '0.0%')}。"
    )
    if valuation_findings:
        plan.append(
            "- 建仓关注点：先审阅悲观/基准/乐观估值区间与缺失假设，再决定是否提高风险暴露。"
        )
    else:
        plan.append(
            "- 建仓关注点：在形成目标价区间前，不做估值驱动的仓位判断。"
        )
    if scorecard_findings:
        plan.append(
            "- 提升置信路径：先补齐评分卡最弱维度，再考虑提高仓位。"
        )
    plan.extend(
        [
            "- 减仓/去风险触发：高影响催化剂失效、现金流可持续期显著恶化，"
            "或出现新的高严重度证据冲突。",
            "- 本节仅供研究支持，不构成交易指令。",
        ]
    )
    return plan
