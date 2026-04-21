"""Deterministic skeptical review for first-pass research memos."""

from __future__ import annotations

from biotech_alpha.financials import CashRunwayEstimate
from biotech_alpha.models import (
    AgentFinding,
    CompetitiveMatch,
    CompetitorAsset,
    PipelineAsset,
    TrialAssetMatch,
    TrialSummary,
)
from biotech_alpha.valuation import ValuationMetrics


def scientific_skeptic_finding(
    *,
    company: str,
    trials: tuple[TrialSummary, ...],
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    competitive_matches: tuple[CompetitiveMatch, ...],
    cash_runway_estimate: CashRunwayEstimate | None,
    valuation_metrics: ValuationMetrics | None,
    input_warning_count: int,
) -> AgentFinding:
    """Create a deterministic counter-thesis from known weak points."""

    risks: list[str] = []
    risks.extend(_clinical_risks(trials))
    risks.extend(_pipeline_risks(pipeline_assets, asset_trial_matches))
    risks.extend(_competition_risks(competitor_assets, competitive_matches))
    risks.extend(_cash_risks(cash_runway_estimate))
    risks.extend(_valuation_risks(valuation_metrics))
    if input_warning_count:
        risks.append(
            f"Input quality is not clean: {input_warning_count} validation warning(s)"
        )

    if not risks:
        risks.append(
            "No major deterministic counter-thesis was triggered, but source "
            "coverage still requires human review."
        )

    return AgentFinding(
        agent_name="scientific_skeptic_agent",
        summary=(
            f"{company} skeptical review identified {len(risks)} counter-thesis "
            "point(s) from the current structured inputs."
        ),
        risks=tuple(risks),
        confidence=0.6,
        needs_human_review=True,
    )


def _clinical_risks(trials: tuple[TrialSummary, ...]) -> tuple[str, ...]:
    if not trials:
        return ("No ClinicalTrials.gov records were available for review",)

    risks: list[str] = []
    active_statuses = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING"}
    active_trials = [trial for trial in trials if trial.status in active_statuses]
    late_stage_trials = [
        trial
        for trial in trials
        if trial.phase and ("PHASE2" in trial.phase or "PHASE3" in trial.phase)
    ]
    if not active_trials:
        risks.append("No active or upcoming ClinicalTrials.gov records were found")
    if not late_stage_trials:
        risks.append("No phase 2/3 ClinicalTrials.gov records were found")
    return tuple(risks)


def _pipeline_risks(
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
) -> tuple[str, ...]:
    if not pipeline_assets:
        return ("No curated pipeline assets were provided for asset-level review",)

    matched_assets = {match.asset_name for match in asset_trial_matches}
    unmatched_assets = [
        asset.name for asset in pipeline_assets if asset.name not in matched_assets
    ]
    if unmatched_assets:
        return (
            "Pipeline assets without registry matches: " + ", ".join(unmatched_assets),
        )
    return ()


def _competition_risks(
    competitor_assets: tuple[CompetitorAsset, ...],
    competitive_matches: tuple[CompetitiveMatch, ...],
) -> tuple[str, ...]:
    if not competitor_assets:
        return ("No curated competitor set was provided",)
    if not competitive_matches:
        return ("Competitor assets did not match company assets deterministically",)

    crowded_assets = [
        asset_name
        for asset_name in {match.asset_name for match in competitive_matches}
        if (
            sum(1 for match in competitive_matches if match.asset_name == asset_name)
            >= 3
        )
    ]
    if crowded_assets:
        return ("Crowded target/indication areas: " + ", ".join(crowded_assets),)
    return ()


def _cash_risks(
    cash_runway_estimate: CashRunwayEstimate | None,
) -> tuple[str, ...]:
    if not cash_runway_estimate:
        return ("No cash runway estimate was available",)
    if cash_runway_estimate.runway_months is None:
        return ("Cash runway could not be calculated",)
    if cash_runway_estimate.runway_months < 12:
        return ("Cash runway is below 12 months",)
    if cash_runway_estimate.runway_months < 24:
        return ("Cash runway is below 24 months",)
    return ()


def _valuation_risks(
    valuation_metrics: ValuationMetrics | None,
) -> tuple[str, ...]:
    if not valuation_metrics:
        return ("No valuation context was available",)
    risks = list(valuation_metrics.warnings)
    if (
        valuation_metrics.revenue_multiple is not None
        and valuation_metrics.revenue_multiple > 20
    ):
        risks.append("Revenue multiple is above 20x")
    return tuple(risks)
