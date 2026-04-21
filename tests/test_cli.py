from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from biotech_alpha.cli import main


class CliTest(unittest.TestCase):
    def test_pipeline_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "assets.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "pipeline-template",
                        "--company",
                        "Example Biotech",
                        "--ticker",
                        "9999.HK",
                        "--output",
                        str(path),
                    ]
                )

            self.assertEqual(template_exit, 0)
            self.assertEqual(json.loads(template_stdout.getvalue())["path"], str(path))
            self.assertTrue(path.exists())

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["pipeline-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertEqual(report["asset_count"], 1)
            self.assertEqual(report["errors"], [])

    def test_pipeline_validate_returns_nonzero_for_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "assets.json"
            path.write_text(json.dumps({"assets": [{"aliases": ["NO-NAME"]}]}))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["pipeline-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 1)
            self.assertTrue(report["errors"])

    def test_financial_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "financials.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "financial-template",
                        "--company",
                        "Example Biotech",
                        "--ticker",
                        "9999.HK",
                        "--output",
                        str(path),
                    ]
                )

            self.assertEqual(template_exit, 0)
            self.assertEqual(json.loads(template_stdout.getvalue())["path"], str(path))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["financial-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertTrue(report["has_snapshot"])

    def test_financial_validate_returns_nonzero_for_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "financials.json"
            path.write_text(json.dumps({"currency": "HKD"}))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["financial-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 1)
            self.assertTrue(report["errors"])

    def test_competitor_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "competitors.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "competitor-template",
                        "--company",
                        "Example Biotech",
                        "--ticker",
                        "9999.HK",
                        "--output",
                        str(path),
                    ]
                )

            self.assertEqual(template_exit, 0)
            self.assertEqual(json.loads(template_stdout.getvalue())["path"], str(path))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["competitor-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertEqual(report["competitor_count"], 1)

    def test_competitor_validate_returns_nonzero_for_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "competitors.json"
            path.write_text(json.dumps({"competitors": [{"company": "No Asset"}]}))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["competitor-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 1)
            self.assertTrue(report["errors"])

    def test_valuation_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "valuation.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "valuation-template",
                        "--company",
                        "Example Biotech",
                        "--ticker",
                        "9999.HK",
                        "--output",
                        str(path),
                    ]
                )

            self.assertEqual(template_exit, 0)
            self.assertEqual(json.loads(template_stdout.getvalue())["path"], str(path))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["valuation-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertTrue(report["has_snapshot"])

    def test_valuation_validate_returns_nonzero_for_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "valuation.json"
            path.write_text(json.dumps({"currency": "HKD"}))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["valuation-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 1)
            self.assertTrue(report["errors"])

    def test_watchlist_rank_outputs_json_for_saved_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "single_company" / "alpha"
            root.mkdir(parents=True)
            run_id = "20260420T010000Z"
            scorecard_path = root / f"{run_id}_scorecard.json"
            manifest_path = root / f"{run_id}_manifest.json"
            scorecard_path.write_text(
                json.dumps(
                    {
                        "total_score": 61.5,
                        "bucket": "watchlist",
                        "needs_human_review": False,
                        "monitoring_rules": ["Track readout"],
                    }
                ),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "company": "Alpha Bio",
                        "ticker": "1111.HK",
                        "market": "HK",
                        "retrieved_at": "2026-04-20T01:00:00+00:00",
                        "input_validation": {},
                        "counts": {"trials": 2, "pipeline_assets": 1},
                        "artifacts": {"scorecard": str(scorecard_path)},
                    }
                ),
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "watchlist-rank",
                        "--processed-dir",
                        str(Path(tmpdir) / "single_company"),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["entry_count"], 1)
            self.assertFalse(payload["latest_only"])
            self.assertEqual(payload["entries"][0]["company"], "Alpha Bio")
            self.assertEqual(payload["entries"][0]["market"], "HK")
            self.assertEqual(payload["entries"][0]["watchlist_score"], 61.5)

    def test_watchlist_rank_latest_only_dedupes_company_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "single_company" / "alpha"
            root.mkdir(parents=True)
            for run_id, score in (
                ("20260420T010000Z", 51.0),
                ("20260421T010000Z", 71.0),
            ):
                scorecard_path = root / f"{run_id}_scorecard.json"
                manifest_path = root / f"{run_id}_manifest.json"
                scorecard_path.write_text(
                    json.dumps(
                        {
                            "total_score": score,
                            "bucket": "watchlist",
                            "needs_human_review": False,
                            "monitoring_rules": ["Track readout"],
                        }
                    ),
                    encoding="utf-8",
                )
                manifest_path.write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "company": "Alpha Bio",
                            "ticker": "1111.HK",
                            "market": "HK",
                            "retrieved_at": run_id,
                            "input_validation": {},
                            "counts": {"trials": 2, "pipeline_assets": 1},
                            "artifacts": {"scorecard": str(scorecard_path)},
                        }
                    ),
                    encoding="utf-8",
                )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "watchlist-rank",
                        "--processed-dir",
                        str(Path(tmpdir) / "single_company"),
                        "--latest-only",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["loaded_entry_count"], 2)
            self.assertEqual(payload["entry_count"], 1)
            self.assertTrue(payload["latest_only"])
            self.assertEqual(payload["entries"][0]["run_id"], "20260421T010000Z")

    def test_catalyst_alerts_outputs_json_for_changed_calendar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "single_company" / "alpha"
            root.mkdir(parents=True)
            for run_id, date_value in (
                ("20260420T010000Z", "2026-12-01"),
                ("20260421T010000Z", "2027-01-15"),
            ):
                catalyst_path = root / f"{run_id}_catalyst_calendar.csv"
                manifest_path = root / f"{run_id}_manifest.json"
                catalyst_path.write_text(
                    (
                        "title,category,expected_date,expected_window,"
                        "related_asset,confidence,evidence_count\n"
                        f"Readout,clinical,{date_value},,Drug A,0.5,1\n"
                    ),
                    encoding="utf-8",
                )
                manifest_path.write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "company": "Alpha Bio",
                            "ticker": "1111.HK",
                            "market": "HK",
                            "retrieved_at": run_id,
                            "artifacts": {
                                "catalyst_calendar_csv": str(catalyst_path),
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "catalyst-alerts",
                        "--processed-dir",
                        str(Path(tmpdir) / "single_company"),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["alert_count"], 1)
            self.assertEqual(payload["alerts"][0]["change_type"], "date_changed")

    def test_target_price_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "target_price.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "target-price-template",
                        "--company",
                        "Example Biotech",
                        "--ticker",
                        "9999.HK",
                        "--output",
                        str(path),
                    ]
                )

            self.assertEqual(template_exit, 0)
            self.assertEqual(json.loads(template_stdout.getvalue())["path"], str(path))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["target-price-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertTrue(report["has_assumptions"])
            self.assertEqual(report["asset_count"], 1)
            self.assertEqual(report["event_impact_count"], 1)

    def test_target_price_validate_returns_nonzero_for_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "target_price.json"
            path.write_text(json.dumps({"currency": "HKD"}), encoding="utf-8")

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["target-price-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 1)
            self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
