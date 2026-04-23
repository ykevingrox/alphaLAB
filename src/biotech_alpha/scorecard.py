"""Deterministic watchlist scorecard for single-company research."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from biotech_alpha.financials import CashRunwayEstimate
from biotech_alpha.models import (
    AgentFinding,
    Catalyst,
    CompetitiveMatch,
    CompetitorAsset,
    PipelineAsset,
    TrialAssetMatch,
    TrialSummary,
)
from biotech_alpha.valuation import ValuationMetrics


@dataclass(frozen=True)
class ScoreDimension:
    """One watchlist scorecard dimension."""

    name: str
    score: float
    rationale: str
    weight: float = 1.0


@dataclass(frozen=True)
class WatchlistScorecard:
    """Deterministic scorecard for sorting follow-up research priorities."""

    total_score: float
    bucket: str
    dimensions: tuple[ScoreDimension, ...]
    monitoring_rules: tuple[str, ...]
    needs_human_review: bool


def build_watchlist_scorecard(
    *,
    trials: tuple[TrialSummary, ...],
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    competitive_matches: tuple[CompetitiveMatch, ...],
    catalysts: tuple[Catalyst, ...],
    cash_runway_estimate: CashRunwayEstimate | None,
    valuation_metrics: ValuationMetrics | None,
    input_warning_count: int,
    skeptic_risk_count: int,
) -> WatchlistScorecard:
    """Build a deterministic watchlist scorecard from structured inputs."""

    dimensions = (
        _clinical_progress_dimension(trials),
        _pipeline_match_dimension(pipeline_assets, asset_trial_matches),
        _cash_runway_dimension(cash_runway_estimate),
        _competition_dimension(
            pipeline_assets,
            competitor_assets,
            competitive_matches,
        ),
        _valuation_dimension(valuation_metrics),
        _data_quality_dimension(
            pipeline_assets=pipeline_assets,
            competitor_assets=competitor_assets,
            cash_runway_estimate=cash_runway_estimate,
            valuation_metrics=valuation_metrics,
            input_warning_count=input_warning_count,
        ),
        _skeptic_dimension(skeptic_risk_count),
    )
    total_score = round(
        sum(dimension.score for dimension in dimensions) / len(dimensions),
        1,
    )
    return WatchlistScorecard(
        total_score=total_score,
        bucket=_score_bucket(total_score),
        dimensions=dimensions,
        monitoring_rules=_monitoring_rules(
            trials=trials,
            pipeline_assets=pipeline_assets,
            asset_trial_matches=asset_trial_matches,
            competitor_assets=competitor_assets,
            catalysts=catalysts,
            cash_runway_estimate=cash_runway_estimate,
            valuation_metrics=valuation_metrics,
            input_warning_count=input_warning_count,
        ),
        needs_human_review=input_warning_count > 0 or skeptic_risk_count > 0,
    )


def scorecard_finding(
    *,
    company: str,
    scorecard: WatchlistScorecard,
) -> AgentFinding:
    """Convert a scorecard into an agent finding."""
    total_weight = sum(max(dimension.weight, 0.0) for dimension in scorecard.dimensions) or 1.0
    risks = tuple(
        f"{_dimension_display_name(dimension.name)} (score={dimension.score:.1f}, "
        f"weight={dimension.weight:.2f}, "
        f"contribution={dimension.score * (dimension.weight / total_weight):.1f}): "
        f"{dimension.rationale}"
        for dimension in scorecard.dimensions
    )
    return AgentFinding(
        agent_name="watchlist_scorecard_agent",
        summary=(
            f"{company} 观察名单评分为 {scorecard.total_score:.1f}/100 "
            f"({scorecard.bucket})."
        ),
        score=scorecard.total_score,
        risks=risks,
        confidence=0.55,
        needs_human_review=scorecard.needs_human_review,
    )


def scorecard_payload(scorecard: WatchlistScorecard) -> dict[str, object]:
    """Return a JSON-serializable scorecard payload."""

    return asdict(scorecard)


def _clinical_progress_dimension(
    trials: tuple[TrialSummary, ...],
) -> ScoreDimension:
    if not trials:
        return ScoreDimension("clinical_progress", 10, "未发现注册库试验")
    if any(trial.phase and "PHASE3" in trial.phase for trial in trials):
        return ScoreDimension("clinical_progress", 75, "覆盖到三期注册试验")
    if any(trial.phase and "PHASE2" in trial.phase for trial in trials):
        return ScoreDimension("clinical_progress", 60, "覆盖到二期注册试验")
    return ScoreDimension("clinical_progress", 35, "仅有早期或阶段不清晰试验")


def _pipeline_match_dimension(
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
) -> ScoreDimension:
    if not pipeline_assets:
        return ScoreDimension("pipeline_registry_match", 20, "缺少管线输入")
    matched_assets = {match.asset_name for match in asset_trial_matches}
    ratio = len(matched_assets) / len(pipeline_assets)
    return ScoreDimension(
        "pipeline_registry_match",
        round(ratio * 100, 1),
        f"{len(matched_assets)}/{len(pipeline_assets)} 个资产与注册库匹配",
    )


def _cash_runway_dimension(
    cash_runway_estimate: CashRunwayEstimate | None,
) -> ScoreDimension:
    if not cash_runway_estimate or cash_runway_estimate.runway_months is None:
        return ScoreDimension("cash_runway", 20, "现金流可持续期不可用")
    months = cash_runway_estimate.runway_months
    if months >= 36:
        score = 85
    elif months >= 24:
        score = 70
    elif months >= 12:
        score = 45
    else:
        score = 20
    return ScoreDimension("cash_runway", score, f"现金流可持续期约 {months:.1f} 个月")


def _competition_dimension(
    pipeline_assets: tuple[PipelineAsset, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    competitive_matches: tuple[CompetitiveMatch, ...],
) -> ScoreDimension:
    if not competitor_assets:
        return ScoreDimension("competition", 35, "缺少竞品输入")
    if not pipeline_assets:
        return ScoreDimension("competition", 30, "竞品无法映射到本公司资产")
    if not competitive_matches:
        return ScoreDimension("competition", 40, "竞品未与资产形成匹配")
    max_matches = max(
        sum(1 for match in competitive_matches if match.asset_name == asset.name)
        for asset in pipeline_assets
    )
    if max_matches >= 3:
        return ScoreDimension("competition", 35, "目标/适应症赛道拥挤")
    return ScoreDimension("competition", 60, "竞品映射可用于审阅")


def _valuation_dimension(
    valuation_metrics: ValuationMetrics | None,
) -> ScoreDimension:
    if not valuation_metrics:
        return ScoreDimension("valuation", 40, "估值上下文不可用")
    multiple = valuation_metrics.revenue_multiple
    if multiple is None:
        return ScoreDimension("valuation", 50, "营收倍数不可用")
    if multiple > 20:
        score = 30
    elif multiple > 10:
        score = 55
    else:
        score = 70
    return ScoreDimension("valuation", score, f"营收倍数 {multiple:.1f}x")


def _data_quality_dimension(
    *,
    pipeline_assets: tuple[PipelineAsset, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    cash_runway_estimate: CashRunwayEstimate | None,
    valuation_metrics: ValuationMetrics | None,
    input_warning_count: int,
) -> ScoreDimension:
    score = 100
    missing = []
    if not pipeline_assets:
        score -= 20
        missing.append("pipeline")
    if not competitor_assets:
        score -= 15
        missing.append("competitors")
    if not cash_runway_estimate:
        score -= 15
        missing.append("financials")
    if not valuation_metrics:
        score -= 10
        missing.append("valuation")
    score -= input_warning_count * 10
    score = max(score, 0)
    if input_warning_count:
        rationale = f"{input_warning_count} 条校验告警"
    elif missing:
        rationale = "缺失：" + ", ".join(missing)
    else:
        rationale = "核心输入类型齐全"
    return ScoreDimension("data_quality", score, rationale)


def _skeptic_dimension(skeptic_risk_count: int) -> ScoreDimension:
    score = max(100 - skeptic_risk_count * 10, 20)
    return ScoreDimension(
        "skeptical_review",
        score,
        f"{skeptic_risk_count} 条反证风险",
    )


def _monitoring_rules(
    *,
    trials: tuple[TrialSummary, ...],
    pipeline_assets: tuple[PipelineAsset, ...],
    asset_trial_matches: tuple[TrialAssetMatch, ...],
    competitor_assets: tuple[CompetitorAsset, ...],
    catalysts: tuple[Catalyst, ...],
    cash_runway_estimate: CashRunwayEstimate | None,
    valuation_metrics: ValuationMetrics | None,
    input_warning_count: int,
) -> tuple[str, ...]:
    rules = ["Refresh ClinicalTrials.gov search before any memo update."]
    if input_warning_count:
        rules.append("Resolve input validation warnings before ranking the company.")
    if not pipeline_assets:
        rules.append("Curate company pipeline assets from latest filings or deck.")
    elif (
        len({match.asset_name for match in asset_trial_matches})
        < len(pipeline_assets)
    ):
        rules.append(
            "Review unmatched pipeline assets and add aliases or China trials."
        )
    if catalysts:
        rules.append("Review catalyst calendar monthly for date changes.")
    if competitor_assets:
        rules.append("Refresh competitor set when new target/indication data appears.")
    else:
        rules.append("Curate same-target and same-indication competitor assets.")
    if not cash_runway_estimate:
        rules.append("Add latest financial snapshot to estimate cash runway.")
    elif (
        cash_runway_estimate.runway_months is not None
        and cash_runway_estimate.runway_months < 24
    ):
        rules.append("Monitor financing risk because runway is below 24 months.")
    if not valuation_metrics:
        rules.append("Add market valuation snapshot for EV and revenue multiple.")
    elif (
        valuation_metrics.revenue_multiple is not None
        and valuation_metrics.revenue_multiple > 20
    ):
        rules.append("Recheck valuation assumptions because revenue multiple is high.")
    return tuple(rules)


def _score_bucket(score: float) -> str:
    if score >= 75:
        return "deep_dive_candidate"
    if score >= 55:
        return "watchlist"
    if score >= 35:
        return "needs_more_evidence"
    return "low_priority"


def _dimension_display_name(name: str) -> str:
    mapping = {
        "clinical_progress": "临床进展",
        "pipeline_registry_match": "管线-注册匹配",
        "cash_runway": "现金流可持续期",
        "competition": "竞争格局",
        "valuation": "估值",
        "data_quality": "数据质量",
        "skeptical_review": "反证审阅",
    }
    return mapping.get(name, name)
