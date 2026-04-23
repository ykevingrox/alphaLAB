"""Research-only position action planning utilities."""

from __future__ import annotations

from dataclasses import dataclass
import math

from biotech_alpha.models import AgentFinding
from biotech_alpha.target_price import TargetPriceAnalysis


@dataclass(frozen=True)
class ResearchActionPlan:
    """Structured research-only action plan derived from valuation signals."""

    guidance_type: str
    suggested_position_pct: float
    entry_zone_low: float | None
    entry_zone_high: float | None
    exit_trigger_conditions: tuple[str, ...]
    notes: tuple[str, ...]
    needs_human_review: bool


def build_research_action_plan(
    *,
    decision: str,
    target_price_analysis: TargetPriceAnalysis,
    runway_months: float | None = None,
) -> ResearchActionPlan:
    """Create a conservative, research-only action plan."""

    suggested_position_pct = {
        "core_candidate": 3.0,
        "watchlist": 1.0,
        "avoid": 0.0,
        "insufficient_data": 0.0,
    }.get(decision, 0.0)
    low, high = _entry_zone(target_price_analysis)
    if low is None or high is None:
        # No valid valuation anchor means no sizing signal.
        suggested_position_pct = 0.0
    triggers = [
        "若高影响催化剂失效或试验显著延期，则执行去风险。",
        "若出现新的高严重度矛盾证据，则执行去风险。",
    ]
    if _is_valid_positive_number(target_price_analysis.bull.target_price):
        triggers.insert(
            0,
            (
                "若现价显著高于乐观目标价 "
                f"（{target_price_analysis.bull.target_price:.2f} "
                f"{target_price_analysis.currency}）但缺乏证据支撑，则执行去风险。"
            ),
        )
    if runway_months is not None:
        triggers.append(
            f"若现金流可持续期估算低于 12 个月则去风险（当前：{runway_months:.1f} 个月）。"
        )
    notes = [
        "仅供研究支持，不构成交易指令。",
        (
            "入场区间仅基于悲观/基准估值锚，需结合流动性与催化剂时点复核。"
        ),
    ]
    if low is None or high is None:
        notes.append(
            "目标价输入不完整或无效，入场区间不可用；在锚点恢复前维持 0.0% 仓位。"
        )
    return ResearchActionPlan(
        guidance_type="research_only",
        suggested_position_pct=suggested_position_pct,
        entry_zone_low=low,
        entry_zone_high=high,
        exit_trigger_conditions=tuple(triggers),
        notes=tuple(notes),
        needs_human_review=True,
    )


def research_action_plan_finding(
    *,
    company: str,
    plan: ResearchActionPlan,
    currency: str,
) -> AgentFinding:
    """Expose the plan as a standard agent finding."""

    zone_text = "入场区间不可用"
    if plan.entry_zone_low is not None and plan.entry_zone_high is not None:
        zone_text = (
            f"入场区间 {plan.entry_zone_low:.2f}-{plan.entry_zone_high:.2f} "
            f"{currency}"
        )
    summary = (
        f"{company} 的研究行动计划建议仓位 "
        f"{plan.suggested_position_pct:.1f}%，{zone_text}。"
    )
    return AgentFinding(
        agent_name="research_action_plan_agent",
        summary=summary,
        risks=(
            f"guidance_type={plan.guidance_type}",
            *plan.exit_trigger_conditions,
            *plan.notes,
        ),
        confidence=0.45,
        needs_human_review=plan.needs_human_review,
    )


def _entry_zone(analysis: TargetPriceAnalysis) -> tuple[float | None, float | None]:
    current = analysis.current_share_price
    bear = analysis.bear.target_price
    base = analysis.base.target_price
    if (
        not _is_valid_positive_number(current)
        or not _is_valid_positive_number(bear)
        or not _is_valid_positive_number(base)
    ):
        return None, None
    low = min(current, bear)
    high = min(max(current, bear), base)
    if low > high:
        low, high = high, low
    return (round(low, 2), round(high, 2))


def _is_valid_positive_number(value: float) -> bool:
    return math.isfinite(value) and value > 0
