from __future__ import annotations

import unittest

from biotech_alpha.financials import CashRunwayEstimate
from biotech_alpha.models import PipelineAsset, TrialSummary
from biotech_alpha.skeptic import scientific_skeptic_finding
from biotech_alpha.valuation import ValuationMetrics


class SkepticTest(unittest.TestCase):
    def test_skeptic_flags_missing_inputs_and_early_trials(self) -> None:
        trials = (
            TrialSummary(
                registry="ClinicalTrials.gov",
                registry_id="NCT00000001",
                title="Early study",
                status="COMPLETED",
                phase="PHASE1",
            ),
        )

        finding = scientific_skeptic_finding(
            company="Example Biotech",
            trials=trials,
            pipeline_assets=(),
            asset_trial_matches=(),
            competitor_assets=(),
            competitive_matches=(),
            cash_runway_estimate=None,
            valuation_metrics=None,
            input_warning_count=2,
        )

        self.assertEqual(finding.agent_name, "scientific_skeptic_agent")
        self.assertTrue(finding.needs_human_review)
        self.assertIn(
            "No active or upcoming ClinicalTrials.gov records were found",
            finding.risks,
        )
        self.assertIn(
            "No phase 2/3 ClinicalTrials.gov records were found",
            finding.risks,
        )
        self.assertIn("No cash runway estimate was available", finding.risks)
        self.assertIn(
            "Input quality is not clean: 2 validation warning(s)",
            finding.risks,
        )

    def test_skeptic_flags_unmatched_pipeline_and_high_multiple(self) -> None:
        finding = scientific_skeptic_finding(
            company="Example Biotech",
            trials=(
                TrialSummary(
                    registry="ClinicalTrials.gov",
                    registry_id="NCT00000001",
                    title="Phase 2 study",
                    status="RECRUITING",
                    phase="PHASE2",
                ),
            ),
            pipeline_assets=(PipelineAsset(name="Unmatched Drug"),),
            asset_trial_matches=(),
            competitor_assets=(),
            competitive_matches=(),
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
                revenue_multiple=25,
                market_cap_method="market_cap",
                needs_human_review=False,
            ),
            input_warning_count=0,
        )

        self.assertIn(
            "Pipeline assets without registry matches: Unmatched Drug",
            finding.risks,
        )
        self.assertIn("Cash runway is below 24 months", finding.risks)
        self.assertIn("Revenue multiple is above 20x", finding.risks)


if __name__ == "__main__":
    unittest.main()
