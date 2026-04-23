"""Single-company research pipeline orchestration."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
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
        "input_warning_count": _input_warning_count(result.input_validation),
        "catalyst_count": len(result.memo.catalysts),
        "needs_human_review": any(
            finding.needs_human_review for finding in result.memo.findings
        ),
        "artifacts": _jsonable(asdict(result.artifacts)),
    }


def memo_to_markdown(memo: InvestmentMemo) -> str:
    """Render a conservative, source-aware Markdown memo."""

    lines = [
        f"# {memo.company} Research Memo",
        "",
        f"- Ticker: {memo.ticker or 'N/A'}",
        f"- Market: {memo.market}",
        f"- Decision: `{memo.decision}`",
        "",
        "## Summary",
        "",
        memo.summary,
        "",
        "## Bull Case",
        "",
    ]
    lines.extend(_bullet_lines(memo.bull_case))
    lines.extend(["", "## Bear Case", ""])
    lines.extend(_bullet_lines(memo.bear_case))
    lines.extend(["", "## Key Risks", ""])
    lines.extend(_finding_risk_lines(memo.findings))
    lines.extend(["", "## Pipeline Assets", ""])
    if memo.key_assets:
        for asset in memo.key_assets:
            details = []
            if asset.target:
                details.append(f"target {asset.target}")
            if asset.indication:
                details.append(f"indication {asset.indication}")
            if asset.phase:
                details.append(f"phase {asset.phase}")
            suffix = f" ({'; '.join(details)})" if details else ""
            lines.append(f"- {asset.name}{suffix}")
    else:
        lines.append("- No disclosed pipeline asset input was provided.")
    lines.extend(["", "## Clinical Trial Finding", ""])
    for finding in memo.findings:
        lines.append(f"- {finding.summary}")
    lines.extend(["", "## Competitive Landscape", ""])
    competitive_findings = [
        finding
        for finding in memo.findings
        if finding.agent_name == "competitive_landscape_agent"
    ]
    if competitive_findings:
        for finding in competitive_findings:
            lines.append(f"- {finding.summary}")
    else:
        lines.append("- No curated competitive landscape input was provided.")
    lines.extend(["", "## Skeptical Review", ""])
    skeptic_findings = [
        finding
        for finding in memo.findings
        if finding.agent_name == "scientific_skeptic_agent"
    ]
    if skeptic_findings:
        for finding in skeptic_findings:
            lines.append(f"- {finding.summary}")
            for risk in finding.risks:
                lines.append(f"  - {risk}")
    else:
        lines.append("- No skeptical review finding was generated.")
    lines.extend(["", "## Watchlist Scorecard", ""])
    scorecard_findings = [
        finding
        for finding in memo.findings
        if finding.agent_name == "watchlist_scorecard_agent"
    ]
    if scorecard_findings:
        for finding in scorecard_findings:
            lines.append(f"- {finding.summary}")
    else:
        lines.append("- No watchlist scorecard was generated.")
    lines.extend(["", "## Catalyst-Adjusted Valuation", ""])
    target_price_findings = [
        finding
        for finding in memo.findings
        if finding.agent_name == "target_price_scenario_agent"
    ]
    if target_price_findings:
        for finding in target_price_findings:
            lines.append(f"- {finding.summary}")
            for risk in finding.risks:
                lines.append(f"  - {risk}")
    else:
        lines.append("- No catalyst-adjusted target price range was generated.")
    clinical_catalysts = tuple(
        catalyst for catalyst in memo.catalysts if catalyst.category != "conference"
    )
    conference_catalysts = tuple(
        catalyst for catalyst in memo.catalysts if catalyst.category == "conference"
    )

    lines.extend(["", "## Upcoming Clinical Catalysts", ""])
    if clinical_catalysts:
        for catalyst in clinical_catalysts:
            when = (
                catalyst.expected_date.isoformat()
                if catalyst.expected_date
                else "TBD"
            )
            if catalyst.expected_window:
                when = catalyst.expected_window
            asset = f" ({catalyst.related_asset})" if catalyst.related_asset else ""
            lines.append(f"- {when}: {catalyst.title}{asset}")
    else:
        lines.append("- No non-conference catalysts were captured.")

    lines.extend(["", "## Conference Catalysts", ""])
    if conference_catalysts:
        for catalyst in conference_catalysts:
            when = (
                catalyst.expected_date.isoformat()
                if catalyst.expected_date
                else "TBD"
            )
            if catalyst.expected_window:
                when = catalyst.expected_window
            asset = f" ({catalyst.related_asset})" if catalyst.related_asset else ""
            lines.append(f"- {when}: {catalyst.title}{asset}")
    else:
        lines.append("- No conference catalysts were captured.")

    lines.extend(["", "## Evidence", ""])
    evidence_items = (
        *memo.evidence,
        *(evidence for finding in memo.findings for evidence in finding.evidence),
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
        lines.append("- No source-backed evidence captured.")

    lines.extend(["", "## Follow-Up Questions", ""])
    lines.extend(_bullet_lines(memo.follow_up_questions))
    lines.append("")
    return "\n".join(lines)


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
    summary = (
        f"First-pass research found {len(trials)} ClinicalTrials.gov records for "
        f"{context.company}, with {len(pipeline_assets)} disclosed pipeline assets "
        f"provided and {len(asset_trial_matches)} deterministic asset-trial matches. "
        "This is still a partial view and should be cross-checked against company "
        "filings, HKEX disclosures, China trial registries, cash runway, and "
        "competitive data before any investment action."
    )
    if not trials and not pipeline_assets:
        summary = (
            f"No ClinicalTrials.gov records were found for {context.company} in this "
            "first-pass search. The company may still have China-only, partner-run, "
            "or differently named asset records that require manual source collection."
        )
    elif pipeline_assets and not asset_trial_matches:
        summary += (
            " None of the provided assets matched trial interventions or titles, so "
            "asset naming, aliases, and China-only registrations need manual review."
        )
    if competitor_assets:
        summary += (
            f" Competitive landscape input included {len(competitor_assets)} "
            f"competitor assets and {len(competitive_matches)} deterministic "
            "matches."
        )
    if cash_runway_estimate and cash_runway_estimate.runway_months is not None:
        summary += (
            f" Cash runway was estimated at "
            f"{cash_runway_estimate.runway_months:.1f} months."
        )
    if valuation_metrics:
        summary += (
            f" Enterprise value was estimated at "
            f"{valuation_metrics.enterprise_value:g} {valuation_metrics.currency}."
        )
    if target_price_analysis:
        summary += (
            f" Catalyst-adjusted probability-weighted target price was "
            f"{target_price_analysis.probability_weighted_target_price:.2f} "
            f"{target_price_analysis.currency}, with implied upside/downside of "
            f"{target_price_analysis.implied_upside_downside_pct:.1f}%."
        )

    return InvestmentMemo(
        company=context.company,
        ticker=context.ticker,
        market=context.market,
        decision=decision,
        summary=summary,
        bull_case=(
            "There is at least one registry-backed clinical record to anchor follow-up."
            if trials
            else (
                "No registry-backed bull case can be formed from this data source yet."
            ),
        ),
        bear_case=(
            "ClinicalTrials.gov coverage alone is incomplete for HK and China biotech "
            "research.",
            "Trial registry presence does not prove positive efficacy, safety, "
            "approval probability, or commercial value.",
        ),
        key_assets=pipeline_assets,
        catalysts=catalysts,
        findings=tuple(findings),
        follow_up_questions=(
            "Collect latest annual/interim reports, prospectus, investor presentation, "
            "and HKEX announcements.",
            "Search China drug trial registration records by company Chinese name, "
            "asset codes, and major indications.",
            "Map disclosed pipeline assets to trial records and identify missing core "
            "products.",
            "Estimate cash runway and financing risk from the latest financial "
            "statement.",
            "Review catalyst-adjusted target-price assumptions before using any "
            "price range as research guidance.",
        ),
        evidence=evidence,
    )


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

        title = "Primary completion date for registered clinical trial"
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
                title=f"Company-disclosed next milestone: {asset.next_milestone}",
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
        risks = (
            "Some disclosed assets did not match ClinicalTrials.gov records by "
            "name or alias: "
            + ", ".join(unmatched_assets),
        )

    return AgentFinding(
        agent_name="pipeline_matcher",
        summary=(
            f"{context.company} has {len(assets)} disclosed pipeline assets in the "
            f"input set; {len(matched_assets)} assets matched {len(matches)} "
            "ClinicalTrials.gov records by intervention or title."
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
        risks.append("No curated pipeline asset input was provided")
    if not financial_snapshot:
        risks.append("No financial snapshot input was provided")
    if not valuation_snapshot:
        risks.append("No valuation snapshot input was provided")
    if not competitor_assets:
        risks.append("No curated competitive landscape input was provided")

    warning_count = _input_warning_count(input_validation)
    if warning_count:
        risks.append(f"Input validation produced {warning_count} warning(s)")

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
        return ["- None captured yet."]
    return [f"- {value}" for value in values]


def _finding_risk_lines(findings: tuple[AgentFinding, ...]) -> list[str]:
    risks = [
        risk
        for finding in findings
        for risk in finding.risks
    ]
    if not risks:
        return ["- No agent-level risks captured yet."]
    return [f"- {risk}" for risk in risks]
