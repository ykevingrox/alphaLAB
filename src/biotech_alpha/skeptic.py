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
            f"输入质量未达标：存在 {input_warning_count} 条校验告警"
        )

    if not risks:
        risks.append(
            "未触发主要确定性反证点，但来源覆盖仍需人工复核。"
        )

    return AgentFinding(
        agent_name="scientific_skeptic_agent",
        summary=(
            f"{company} 的反证审阅在当前结构化输入下识别到 {len(risks)} 个关键反证点。"
        ),
        risks=tuple(risks),
        confidence=0.6,
        needs_human_review=True,
    )


def _clinical_risks(trials: tuple[TrialSummary, ...]) -> tuple[str, ...]:
    if not trials:
        return ("未发现可用于审阅的 ClinicalTrials.gov 记录",)

    risks: list[str] = []
    active_statuses = {"RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING"}
    active_trials = [trial for trial in trials if trial.status in active_statuses]
    late_stage_trials = [
        trial
        for trial in trials
        if trial.phase and ("PHASE2" in trial.phase or "PHASE3" in trial.phase)
    ]
    if not active_trials:
        risks.append("未发现活跃或即将启动的 ClinicalTrials.gov 记录")
    if not late_stage_trials:
        risks.append("未发现二/三期 ClinicalTrials.gov 记录")
    return tuple(risks)


def _pipeline_risks(
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
) -> tuple[str, ...]:
    if not pipeline_assets:
        return ("未提供可用于资产级审阅的结构化管线输入",)

    matched_assets = {match.asset_name for match in asset_trial_matches}
    unmatched_assets = [
        asset.name for asset in pipeline_assets if asset.name not in matched_assets
    ]
    if unmatched_assets:
        return (
            "以下管线资产未与注册库匹配：" + ", ".join(unmatched_assets),
        )
    return ()


def _competition_risks(
    competitor_assets: tuple[CompetitorAsset, ...],
    competitive_matches: tuple[CompetitiveMatch, ...],
) -> tuple[str, ...]:
    if not competitor_assets:
        return ("未提供结构化竞品集合",)
    if not competitive_matches:
        return ("竞品资产未与公司资产形成确定性匹配",)

    crowded_assets = [
        asset_name
        for asset_name in {match.asset_name for match in competitive_matches}
        if (
            sum(1 for match in competitive_matches if match.asset_name == asset_name)
            >= 3
        )
    ]
    if crowded_assets:
        return ("目标/适应症赛道拥挤：" + ", ".join(crowded_assets),)
    return ()


def _cash_risks(
    cash_runway_estimate: CashRunwayEstimate | None,
) -> tuple[str, ...]:
    if not cash_runway_estimate:
        return ("现金流可持续期估算不可用",)
    if cash_runway_estimate.runway_months is None:
        return ("无法计算现金流可持续期",)
    if cash_runway_estimate.runway_months < 12:
        return ("现金流可持续期低于 12 个月",)
    if cash_runway_estimate.runway_months < 24:
        return ("现金流可持续期低于 24 个月",)
    return ()


def _valuation_risks(
    valuation_metrics: ValuationMetrics | None,
) -> tuple[str, ...]:
    if not valuation_metrics:
        return ("估值上下文不可用",)
    risks = list(valuation_metrics.warnings)
    if (
        valuation_metrics.revenue_multiple is not None
        and valuation_metrics.revenue_multiple > 20
    ):
        risks.append("营收倍数高于 20x")
    return tuple(risks)
