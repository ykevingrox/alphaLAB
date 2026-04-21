from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from biotech_alpha.target_price import (
    build_target_price_analysis,
    load_target_price_assumptions,
    target_price_assumptions_template,
    target_price_summary_csv_text,
    validate_target_price_assumptions_file,
    write_target_price_artifacts,
    write_target_price_assumptions_template,
)


class TargetPriceAssumptionsTest(unittest.TestCase):
    def test_template_loads_and_validates_with_placeholder_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "target_price.json"
            write_target_price_assumptions_template(
                path=path,
                company="Example Biotech",
                ticker="9999.HK",
            )

            assumptions = load_target_price_assumptions(path)
            report = validate_target_price_assumptions_file(path)

            self.assertEqual(assumptions.currency, "HKD")
            self.assertEqual(len(assumptions.assets), 1)
            self.assertEqual(assumptions.assets[0].name, "Example Drug")
            self.assertEqual(len(assumptions.event_impacts), 1)
            self.assertTrue(report.has_assumptions)
            self.assertEqual(report.asset_count, 1)
            self.assertEqual(report.event_impact_count, 1)
            self.assertEqual(report.current_equity_value, 12400000000)
            self.assertIn("replace placeholder as_of_date", report.warnings)

    def test_validate_rejects_missing_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "target_price.json"
            path.write_text(
                json.dumps(
                    {
                        "as_of_date": "2026-04-21",
                        "currency": "HKD",
                        "share_price": 12.4,
                        "shares_outstanding": 1000000000,
                        "cash_and_equivalents": 1200000000,
                        "total_debt": 300000000,
                        "expected_dilution_pct": 0.0,
                        "assets": [],
                    }
                ),
                encoding="utf-8",
            )

            report = validate_target_price_assumptions_file(path)

            self.assertFalse(report.has_assumptions)
            self.assertTrue(report.errors)

    def test_validate_warns_for_unknown_event_impact_asset(self) -> None:
        payload = target_price_assumptions_template(
            company="Example Biotech",
            ticker="9999.HK",
        )
        payload["as_of_date"] = "2026-04-21"
        payload["assets"][0]["name"] = "Known Drug"
        payload["assets"][0]["source"] = "model.xlsx"
        payload["assets"][0]["source_date"] = "2026-04-21"
        payload["event_impacts"][0]["asset_name"] = "Unknown Drug"

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "target_price.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            report = validate_target_price_assumptions_file(path)

            self.assertTrue(report.has_assumptions)
            self.assertIn(
                "event impact references unknown asset: Unknown Drug",
                report.warnings,
            )

    def test_builds_catalyst_adjusted_target_price_scenarios(self) -> None:
        payload = target_price_assumptions_template(
            company="Example Biotech",
            ticker="9999.HK",
        )
        payload["as_of_date"] = "2026-04-21"
        payload["assets"][0]["name"] = "Known Drug"
        payload["assets"][0]["source"] = "model.xlsx"
        payload["assets"][0]["source_date"] = "2026-04-21"
        payload["event_impacts"][0]["asset_name"] = "Known Drug"

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "target_price.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            assumptions = load_target_price_assumptions(path)
            analysis = build_target_price_analysis(assumptions)

            self.assertGreater(analysis.base.equity_value, 0)
            self.assertGreater(
                analysis.base.equity_value,
                analysis.pre_event_equity_value,
            )
            self.assertGreater(analysis.event_value_delta, 0)
            self.assertLess(analysis.bear.target_price, analysis.base.target_price)
            self.assertLess(analysis.base.target_price, analysis.bull.target_price)
            self.assertFalse(analysis.needs_human_review)
            self.assertIn("Known Drug positive_readout", analysis.key_drivers[0])

            csv_text = target_price_summary_csv_text(analysis)
            self.assertIn("scenario,currency,pipeline_rnpv", csv_text)
            self.assertIn("bear,HKD", csv_text)
            self.assertIn("base,HKD", csv_text)
            self.assertIn("bull,HKD", csv_text)

    def test_writes_target_price_artifacts(self) -> None:
        payload = target_price_assumptions_template(
            company="Example Biotech",
            ticker="9999.HK",
        )
        payload["as_of_date"] = "2026-04-21"
        payload["assets"][0]["name"] = "Known Drug"
        payload["assets"][0]["source"] = "model.xlsx"
        payload["assets"][0]["source_date"] = "2026-04-21"
        payload["event_impacts"][0]["asset_name"] = "Known Drug"

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "target_price.json"
            input_path.write_text(json.dumps(payload), encoding="utf-8")
            assumptions = load_target_price_assumptions(input_path)
            analysis = build_target_price_analysis(assumptions)

            artifacts = write_target_price_artifacts(
                output_dir=Path(tmpdir) / "processed",
                company="Example Biotech",
                assumptions=assumptions,
                analysis=analysis,
            )

            self.assertEqual(
                set(artifacts),
                {
                    "event_impact",
                    "target_price_scenarios",
                    "target_price_summary_csv",
                },
            )
            for path in artifacts.values():
                self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
