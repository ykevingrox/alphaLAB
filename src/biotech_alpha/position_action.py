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
        "De-risk on any high-impact catalyst miss or material trial delay.",
        "De-risk if new high-severity contradictory evidence appears.",
    ]
    if _is_valid_positive_number(target_price_analysis.bull.target_price):
        triggers.insert(
            0,
            (
                "De-risk if spot price moves above bull target "
                f"({target_price_analysis.bull.target_price:.2f} "
                f"{target_price_analysis.currency}) without matching evidence."
            ),
        )
    if runway_months is not None:
        triggers.append(
            f"De-risk if cash runway estimate falls below 12 months "
            f"(current: {runway_months:.1f} months)."
        )
    notes = [
        "Research support only; not a trading instruction.",
        (
            "Entry zone references bear/base valuation anchors and must be "
            "cross-checked against liquidity and catalyst timing."
        ),
    ]
    if low is None or high is None:
        notes.append(
            "Entry zone unavailable due to incomplete/invalid target-price inputs; "
            "keep sizing at 0.0% until anchors are restored."
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

    zone_text = "entry zone unavailable"
    if plan.entry_zone_low is not None and plan.entry_zone_high is not None:
        zone_text = (
            f"entry zone {plan.entry_zone_low:.2f}-{plan.entry_zone_high:.2f} "
            f"{currency}"
        )
    summary = (
        f"{company} research-only action plan suggests "
        f"{plan.suggested_position_pct:.1f}% sizing with {zone_text}."
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
