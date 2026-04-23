from __future__ import annotations

import unittest

from biotech_alpha.position_action import (
    build_research_action_plan,
    research_action_plan_finding,
)
from biotech_alpha.target_price import TargetPriceAnalysis, TargetPriceScenario


class PositionActionTest(unittest.TestCase):
    def test_build_research_action_plan_with_entry_zone(self) -> None:
        analysis = _analysis(current=10.0, bear=8.0, base=12.0, bull=16.0)
        plan = build_research_action_plan(
            decision="watchlist",
            target_price_analysis=analysis,
            runway_months=18.0,
        )

        self.assertEqual(plan.guidance_type, "research_only")
        self.assertEqual(plan.suggested_position_pct, 1.0)
        self.assertEqual(plan.entry_zone_low, 8.0)
        self.assertEqual(plan.entry_zone_high, 10.0)
        self.assertTrue(
            any("below 12 months" in trigger for trigger in plan.exit_trigger_conditions)
        )

    def test_build_research_action_plan_handles_inverted_edge(self) -> None:
        analysis = _analysis(current=11.0, bear=14.0, base=9.0, bull=18.0)
        plan = build_research_action_plan(
            decision="core_candidate",
            target_price_analysis=analysis,
        )

        self.assertEqual(plan.suggested_position_pct, 3.0)
        self.assertIsNotNone(plan.entry_zone_low)
        self.assertIsNotNone(plan.entry_zone_high)
        self.assertLessEqual(plan.entry_zone_low or 0, plan.entry_zone_high or 0)

    def test_research_action_plan_finding_renders_summary(self) -> None:
        analysis = _analysis(current=10.0, bear=8.0, base=12.0, bull=16.0)
        plan = build_research_action_plan(
            decision="watchlist",
            target_price_analysis=analysis,
        )
        finding = research_action_plan_finding(
            company="Example Biotech",
            plan=plan,
            currency="HKD",
        )

        self.assertEqual(finding.agent_name, "research_action_plan_agent")
        self.assertIn("entry zone 8.00-10.00 HKD", finding.summary)
        self.assertTrue(any("research support only" in risk.lower() for risk in finding.risks))


def _analysis(*, current: float, bear: float, base: float, bull: float) -> TargetPriceAnalysis:
    return TargetPriceAnalysis(
        as_of_date="2026-04-23",
        currency="HKD",
        current_share_price=current,
        shares_outstanding=1_000_000_000,
        diluted_shares=1_000_000_000,
        current_equity_value=current * 1_000_000_000,
        pre_event_equity_value=10_000_000_000,
        event_value_delta=0.0,
        asset_value_delta=0.0,
        bear=_scenario("bear", bear),
        base=_scenario("base", base),
        bull=_scenario("bull", bull),
        probability_weighted_target_price=base,
        implied_upside_downside_pct=0.0,
        key_drivers=(),
        sensitivity_points=(),
        missing_assumptions=(),
        needs_human_review=True,
    )


def _scenario(name: str, target_price: float) -> TargetPriceScenario:
    return TargetPriceScenario(
        name=name,
        currency="HKD",
        pipeline_rnpv=0.0,
        net_cash=0.0,
        equity_value=target_price * 1_000_000_000,
        target_price=target_price,
        asset_rnpv=(),
    )


if __name__ == "__main__":
    unittest.main()
