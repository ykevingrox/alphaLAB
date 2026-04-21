from __future__ import annotations

import unittest

from biotech_alpha.financials import CashRunwayEstimate
from biotech_alpha.models import (
    Catalyst,
    CompetitiveMatch,
    CompetitorAsset,
    PipelineAsset,
    TrialAssetMatch,
    TrialSummary,
)
from biotech_alpha.scorecard import build_watchlist_scorecard, scorecard_finding
from biotech_alpha.valuation import ValuationMetrics


class ScorecardTest(unittest.TestCase):
    def test_build_watchlist_scorecard_from_complete_inputs(self) -> None:
        scorecard = build_watchlist_scorecard(
            trials=(
                TrialSummary(
                    registry="ClinicalTrials.gov",
                    registry_id="NCT00000001",
                    title="Phase 2 trial",
                    status="RECRUITING",
                    phase="PHASE2",
                ),
            ),
            pipeline_assets=(PipelineAsset(name="Example Drug"),),
            asset_trial_matches=(
                TrialAssetMatch(
                    asset_name="Example Drug",
                    registry_id="NCT00000001",
                    match_reason="intervention",
                    matched_text="Example Drug",
                    confidence=0.9,
                ),
            ),
            competitor_assets=(CompetitorAsset(company="Rival", asset_name="Drug"),),
            competitive_matches=(
                CompetitiveMatch(
                    asset_name="Example Drug",
                    competitor_company="Rival",
                    competitor_asset="Drug",
                    match_scope="target",
                    confidence=0.55,
                ),
            ),
            catalysts=(Catalyst(title="Readout", category="clinical"),),
            cash_runway_estimate=CashRunwayEstimate(
                currency="HKD",
                net_cash=900,
                monthly_cash_burn=50,
                runway_months=18,
                method="test",
                needs_human_review=False,
            ),
            valuation_metrics=ValuationMetrics(
                currency="HKD",
                market_cap=2500,
                enterprise_value=2300,
                revenue_multiple=11.5,
                market_cap_method="market_cap",
                needs_human_review=False,
            ),
            input_warning_count=1,
            skeptic_risk_count=2,
        )
        finding = scorecard_finding(company="Example Biotech", scorecard=scorecard)

        self.assertEqual(scorecard.bucket, "watchlist")
        self.assertGreater(scorecard.total_score, 55)
        self.assertTrue(scorecard.needs_human_review)
        self.assertIn(
            "Resolve input validation warnings",
            scorecard.monitoring_rules[1],
        )
        self.assertEqual(finding.agent_name, "watchlist_scorecard_agent")
        self.assertEqual(finding.score, scorecard.total_score)

    def test_build_watchlist_scorecard_penalizes_missing_inputs(self) -> None:
        scorecard = build_watchlist_scorecard(
            trials=(),
            pipeline_assets=(),
            asset_trial_matches=(),
            competitor_assets=(),
            competitive_matches=(),
            catalysts=(),
            cash_runway_estimate=None,
            valuation_metrics=None,
            input_warning_count=0,
            skeptic_risk_count=5,
        )

        self.assertEqual(scorecard.bucket, "low_priority")
        self.assertLess(scorecard.total_score, 35)
        self.assertIn(
            "Curate company pipeline assets from latest filings or deck.",
            scorecard.monitoring_rules,
        )


if __name__ == "__main__":
    unittest.main()
