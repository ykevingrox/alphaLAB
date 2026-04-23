from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from biotech_alpha.cli import (
    _publish_quick_report_shortcuts,
    _print_quick_report_summary,
    _split_company_or_ticker,
    _resolve_macro_signals_provider,
    _resolve_market_data_provider,
    main,
)


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

    def test_conference_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "conference.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "conference-template",
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
                validate_exit = main(["conference-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertEqual(report["catalyst_count"], 1)

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
            self.assertNotIn("scorecard_dimensions", payload["entries"][0])

    def test_watchlist_rank_can_include_scorecard_dimensions(self) -> None:
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
                        "dimensions": [
                            {
                                "name": "clinical_progress",
                                "score": 60.0,
                                "weight": 1.0,
                                "contribution": 8.6,
                                "rationale": "phase 2 coverage",
                            }
                        ],
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
                        "--with-scorecard-dimensions",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["entries"][0]["scorecard_dimensions"])
            self.assertEqual(
                payload["entries"][0]["scorecard_dimensions"][0]["name"],
                "clinical_progress",
            )

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

    def test_watchlist_rank_min_quality_gate_filters_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "single_company" / "alpha"
            root.mkdir(parents=True)
            for run_id, score, level in (
                ("20260420T010000Z", 51.0, "research_ready_with_review"),
                ("20260421T010000Z", 71.0, "decision_ready"),
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
                            "quality_gate": {"level": level},
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
                        "--min-quality-gate",
                        "decision_ready",
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["entry_count"], 1)
            self.assertEqual(payload["min_quality_gate"], "decision_ready")
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

    def test_hkexnews_track_reads_feed_file_and_tracks_state(self) -> None:
        rss_text = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>HKEXnews</title>
    <item>
      <title>09887 - Voluntary Announcement</title>
      <link>https://www.hkexnews.hk/123</link>
      <guid>hkex-123</guid>
      <pubDate>Thu, 23 Apr 2026 10:00:00 +0800</pubDate>
      <category>Announcement</category>
    </item>
  </channel>
</rss>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            feed_path = Path(tmpdir) / "feed.xml"
            state_path = Path(tmpdir) / "seen.json"
            feed_path.write_text(rss_text, encoding="utf-8")

            first_output = io.StringIO()
            with redirect_stdout(first_output):
                first_exit = main(
                    [
                        "hkexnews-track",
                        "--feed-file",
                        str(feed_path),
                        "--ticker",
                        "09887.HK",
                        "--state-file",
                        str(state_path),
                    ]
                )
            first_payload = json.loads(first_output.getvalue())
            self.assertEqual(first_exit, 0)
            self.assertEqual(first_payload["new_count"], 1)
            self.assertEqual(first_payload["new_items"][0]["guid"], "hkex-123")

            second_output = io.StringIO()
            with redirect_stdout(second_output):
                second_exit = main(
                    [
                        "hkexnews-track",
                        "--feed-file",
                        str(feed_path),
                        "--ticker",
                        "09887.HK",
                        "--state-file",
                        str(state_path),
                    ]
                )
            second_payload = json.loads(second_output.getvalue())
            self.assertEqual(second_exit, 0)
            self.assertEqual(second_payload["new_count"], 0)

    def test_cde_track_reads_feed_file_and_tracks_state(self) -> None:
        rss_text = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CDE</title>
    <item>
      <title>DualityBio CXHL123456 临床试验申请受理 用于肺癌</title>
      <link>https://cde.example.cn/123</link>
      <guid>cde-123</guid>
      <pubDate>Thu, 23 Apr 2026 10:00:00 +0800</pubDate>
      <category>受理信息</category>
    </item>
  </channel>
</rss>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            feed_path = Path(tmpdir) / "cde.xml"
            state_path = Path(tmpdir) / "seen.json"
            feed_path.write_text(rss_text, encoding="utf-8")

            first_output = io.StringIO()
            with redirect_stdout(first_output):
                first_exit = main(
                    [
                        "cde-track",
                        "--feed-file",
                        str(feed_path),
                        "--query",
                        "DualityBio",
                        "--state-file",
                        str(state_path),
                    ]
                )
            first_payload = json.loads(first_output.getvalue())
            self.assertEqual(first_exit, 0)
            self.assertEqual(first_payload["new_count"], 1)
            self.assertEqual(first_payload["typed_new_items"][0]["event_type"], "clinical")
            self.assertTrue(first_payload["normalized_new_records"])

            second_output = io.StringIO()
            with redirect_stdout(second_output):
                second_exit = main(
                    [
                        "cde-track",
                        "--feed-file",
                        str(feed_path),
                        "--query",
                        "DualityBio",
                        "--state-file",
                        str(state_path),
                    ]
                )
            second_payload = json.loads(second_output.getvalue())
            self.assertEqual(second_exit, 0)
            self.assertEqual(second_payload["new_count"], 0)

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

    def test_event_impact_outputs_json_and_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            assumptions_path = Path(tmpdir) / "target_price.json"
            assumptions_path.write_text(
                json.dumps(_target_price_payload()),
                encoding="utf-8",
            )
            output_dir = Path(tmpdir) / "target_price_outputs"

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "event-impact",
                        "--company",
                        "Example Biotech",
                        "--assumptions",
                        str(assumptions_path),
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertGreater(payload["summary"]["base_target_price"], 0)
            self.assertIn("analysis", payload)
            self.assertIn("event_impact", payload["artifacts"])
            for path in payload["artifacts"].values():
                self.assertTrue(Path(path).exists())

    def test_event_impact_outputs_csv_without_saving(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            assumptions_path = Path(tmpdir) / "target_price.json"
            assumptions_path.write_text(
                json.dumps(_target_price_payload()),
                encoding="utf-8",
            )

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "event-impact",
                        "--company",
                        "Example Biotech",
                        "--assumptions",
                        str(assumptions_path),
                        "--format",
                        "csv",
                        "--no-save",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("scenario,currency,pipeline_rnpv", output.getvalue())
            self.assertIn("base,HKD", output.getvalue())

    def test_company_report_command_prints_summary(self) -> None:
        fake_summary = {
            "identity": {"company": "Example Bio"},
            "research": {"decision": "insufficient_data"},
            "missing_input_count": 6,
        }
        with patch("biotech_alpha.cli.run_company_report") as run_mock:
            with patch("biotech_alpha.cli.company_report_summary") as summary_mock:
                run_mock.return_value = object()
                summary_mock.return_value = fake_summary
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = main(
                        [
                            "company-report",
                            "--company",
                            "Example Bio",
                            "--auto-inputs",
                            "--overwrite-auto-inputs",
                            "--limit",
                            "1",
                            "--no-save",
                        ]
                    )

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["identity"]["company"], "Example Bio")
        self.assertEqual(payload["missing_input_count"], 6)
        run_mock.assert_called_once()
        self.assertTrue(run_mock.call_args.kwargs["auto_inputs"])
        self.assertTrue(run_mock.call_args.kwargs["overwrite_auto_inputs"])


def _target_price_payload() -> dict[str, object]:
    return {
        "as_of_date": "2026-04-21",
        "currency": "HKD",
        "share_price": 12.4,
        "shares_outstanding": 1000000000,
        "cash_and_equivalents": 1200000000,
        "total_debt": 300000000,
        "expected_dilution_pct": 0.0,
        "assets": [
            {
                "name": "Known Drug",
                "indication": "NSCLC",
                "phase": "Phase 2",
                "peak_sales": 3000000000,
                "probability_of_success": 0.35,
                "economics_share": 1.0,
                "operating_margin": 0.35,
                "launch_year": 2030,
                "discount_rate": 0.12,
                "source": "model.xlsx",
                "source_date": "2026-04-21",
            }
        ],
        "event_impacts": [
            {
                "event_type": "positive_readout",
                "asset_name": "Known Drug",
                "probability_of_success_delta": 0.15,
                "peak_sales_delta_pct": 0.1,
                "launch_year_delta": 0,
                "discount_rate_delta": 0.0,
            }
        ],
    }


class ResolveMarketDataProviderTest(unittest.TestCase):
    """Regression tests for the CLI --market-data-freshness-days knob."""

    def test_none_choice_returns_no_provider(self) -> None:
        self.assertIsNone(_resolve_market_data_provider("none"))

    def test_hk_public_without_freshness_returns_bare_callable(self) -> None:
        from biotech_alpha.market_data_providers import hk_public_quote_provider

        provider = _resolve_market_data_provider("hk-public")
        self.assertIs(provider, hk_public_quote_provider)

    def test_hk_public_with_freshness_wraps_callable(self) -> None:
        from functools import partial

        from biotech_alpha.market_data_providers import hk_public_quote_provider

        provider = _resolve_market_data_provider(
            "hk-public", freshness_days=0.5
        )
        self.assertIsInstance(provider, partial)
        self.assertIs(provider.func, hk_public_quote_provider)
        self.assertEqual(provider.keywords, {"freshness_days": 0.5})

    def test_non_positive_freshness_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_market_data_provider("hk-public", freshness_days=0.0)
        with self.assertRaises(ValueError):
            _resolve_market_data_provider("hk-public", freshness_days=-1.0)

    def test_freshness_without_provider_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _resolve_market_data_provider("none", freshness_days=1.0)


class CompanyReportFreshnessCliTest(unittest.TestCase):
    """Verify --market-data-freshness-days threads into the provider."""

    def test_flag_passes_through_to_run_company_report(self) -> None:
        from functools import partial

        from biotech_alpha.market_data_providers import (
            hk_public_quote_provider,
        )

        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client", return_value=None
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value={"identity": {}, "status": "ok"},
        ):
            run.return_value = object()
            exit_code = main(
                [
                    "company-report",
                    "--ticker",
                    "09606.HK",
                    "--market-data",
                    "hk-public",
                    "--market-data-freshness-days",
                    "1.5",
                    "--no-save",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(run.call_count, 1)
            provider = run.call_args.kwargs["market_data_provider"]
            self.assertIsInstance(provider, partial)
            self.assertIs(provider.func, hk_public_quote_provider)
            self.assertEqual(
                provider.keywords, {"freshness_days": 1.5}
            )

    def test_default_leaves_provider_unwrapped(self) -> None:
        from biotech_alpha.market_data_providers import (
            hk_public_quote_provider,
        )

        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client", return_value=None
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value={"identity": {}, "status": "ok"},
        ):
            run.return_value = object()
            main(
                [
                    "company-report",
                    "--ticker",
                    "09606.HK",
                    "--market-data",
                    "hk-public",
                    "--no-save",
                ]
            )
            provider = run.call_args.kwargs["market_data_provider"]
            self.assertIs(provider, hk_public_quote_provider)


class ResolveMacroSignalsProviderTest(unittest.TestCase):
    """Unit test the tiny resolver for --macro-signals."""

    def test_none_returns_none(self) -> None:
        self.assertIsNone(_resolve_macro_signals_provider("none"))

    def test_yahoo_hk_returns_cached_live_callable(self) -> None:
        from biotech_alpha.macro_signals_providers import (
            CachingMacroSignalsProvider,
            FallbackMacroSignalsProvider,
        )

        provider = _resolve_macro_signals_provider("yahoo-hk")
        self.assertIsInstance(provider, CachingMacroSignalsProvider)
        assert isinstance(provider, CachingMacroSignalsProvider)
        self.assertIsInstance(provider.inner, FallbackMacroSignalsProvider)


class CompanyReportMacroSignalsCliTest(unittest.TestCase):
    """Verify --macro-signals threads into run_company_report."""

    def test_flag_passes_through_to_run_company_report(self) -> None:
        from datetime import timedelta

        from biotech_alpha.macro_signals_providers import (
            CachingMacroSignalsProvider,
            FallbackMacroSignalsProvider,
        )

        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client", return_value=None
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value={"identity": {}, "status": "ok"},
        ):
            run.return_value = object()
            exit_code = main(
                [
                    "company-report",
                    "--ticker",
                    "09606.HK",
                    "--macro-signals",
                    "yahoo-hk",
                    "--no-save",
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(run.call_count, 1)
            provider = run.call_args.kwargs["macro_signals_provider"]
            self.assertIsInstance(provider, CachingMacroSignalsProvider)
            assert isinstance(provider, CachingMacroSignalsProvider)
            self.assertIsInstance(
                provider.inner, FallbackMacroSignalsProvider
            )
            self.assertEqual(provider.ttl, timedelta(hours=6.0))

    def test_no_cache_flag_returns_bare_callable(self) -> None:
        from biotech_alpha.macro_signals_providers import (
            FallbackMacroSignalsProvider,
        )

        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client", return_value=None
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value={"identity": {}, "status": "ok"},
        ):
            run.return_value = object()
            main(
                [
                    "company-report",
                    "--ticker",
                    "09606.HK",
                    "--macro-signals",
                    "yahoo-hk",
                    "--no-macro-signals-cache",
                    "--no-save",
                ]
            )
            provider = run.call_args.kwargs["macro_signals_provider"]
            self.assertIsInstance(provider, FallbackMacroSignalsProvider)

    def test_custom_ttl_flag_threads_through(self) -> None:
        from datetime import timedelta

        from biotech_alpha.macro_signals_providers import (
            CachingMacroSignalsProvider,
        )

        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client", return_value=None
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value={"identity": {}, "status": "ok"},
        ):
            run.return_value = object()
            main(
                [
                    "company-report",
                    "--ticker",
                    "09606.HK",
                    "--macro-signals",
                    "yahoo-hk",
                    "--macro-signals-cache-ttl-hours",
                    "1.5",
                    "--no-save",
                ]
            )
            provider = run.call_args.kwargs["macro_signals_provider"]
            assert isinstance(provider, CachingMacroSignalsProvider)
            self.assertEqual(provider.ttl, timedelta(hours=1.5))

    def test_default_has_no_macro_provider(self) -> None:
        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client", return_value=None
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value={"identity": {}, "status": "ok"},
        ):
            run.return_value = object()
            main(
                [
                    "company-report",
                    "--ticker",
                    "09606.HK",
                    "--no-save",
                ]
            )
            self.assertIsNone(
                run.call_args.kwargs["macro_signals_provider"]
            )


class QuickReportCliTest(unittest.TestCase):
    def test_split_company_or_ticker_detects_hk_ticker(self) -> None:
        company, ticker = _split_company_or_ticker("09606.hk")
        self.assertIsNone(company)
        self.assertEqual(ticker, "09606.HK")

    def test_split_company_or_ticker_keeps_company_name(self) -> None:
        company, ticker = _split_company_or_ticker("DualityBio")
        self.assertEqual(company, "DualityBio")
        self.assertIsNone(ticker)

    def test_report_command_uses_smart_defaults(self) -> None:
        fake_summary = {
            "identity": {"company": "DualityBio", "ticker": "09606.HK"},
            "research": {
                "run_id": "dualitybio_20260422",
                "decision": "watchlist",
                "watchlist_bucket": "starter",
                "watchlist_score": 42,
                "pipeline_asset_count": 3,
                "trial_count": 2,
                "competitor_asset_count": 1,
                "catalyst_count": 4,
                "input_warning_count": 0,
                "artifacts": {
                    "memo_markdown": "data/memos/dualitybio/memo.md",
                    "manifest_json": "data/processed/manifest.json",
                },
            },
            "quality_gate": {
                "level": "research_ready_with_review",
                "rationale": "report generated but requires manual review",
            },
            "missing_input_count": 0,
            "extraction_audit": {
                "asset_count": 3,
                "counts": {
                    "supported": 2,
                    "needs_review": 1,
                    "missing_anchor": 0,
                },
                "source_excerpt": {
                    "anchor_count": 3,
                    "missing_anchor_count": 0,
                },
                "top_review_assets": [
                    {
                        "name": "DB-1312",
                        "reasons": ["missing phase"],
                    }
                ],
            },
            "next_actions": ["Review the memo."],
            "llm_agents": {
                "steps": [
                    {"agent_name": "pipeline", "ok": True, "skipped": False},
                ],
                "cost_summary": {"total_tokens": 123},
            },
            "llm_trace_path": "data/traces/dualitybio_20260422.jsonl",
        }
        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client",
            return_value=object(),
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value=fake_summary,
        ):
            run.return_value = object()
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["report", "09606.HK", "--no-save"])

            self.assertEqual(exit_code, 0)
            terminal = output.getvalue()
            self.assertIn("[1/4] Resolve query: 09606.HK", terminal)
            self.assertIn("[4/4] Report complete", terminal)
            self.assertIn("Company: DualityBio (09606.HK)", terminal)
            self.assertIn(
                "Extraction audit: 2/3 supported, 1 need review",
                terminal,
            )
            self.assertIn("Audit focus: DB-1312 (missing phase)", terminal)
            self.assertIn("Artifacts", terminal)
            self.assertIn("- Not saved (--no-save)", terminal)
            kwargs = run.call_args.kwargs
            self.assertTrue(kwargs["auto_inputs"])
            self.assertEqual(kwargs["llm_agents"][0], "provisional-pipeline")
            self.assertIsNotNone(kwargs["market_data_provider"])
            self.assertIsNotNone(kwargs["macro_signals_provider"])
            self.assertIsNotNone(kwargs["competitor_discovery_client"])

    def test_report_command_can_skip_competitor_discovery(self) -> None:
        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client",
            return_value=object(),
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value={"identity": {"ticker": "09606.HK"}, "status": "ok"},
        ):
            run.return_value = object()
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "report",
                        "09606.HK",
                        "--json",
                        "--no-save",
                        "--no-competitor-discovery",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertIsNone(
                run.call_args.kwargs["competitor_discovery_client"]
            )

    def test_quick_report_prints_extraction_audit_artifact_path(self) -> None:
        summary = {
            "identity": {"company": "DualityBio", "ticker": "09606.HK"},
            "research": {
                "run_id": "20260422T000000Z",
                "decision": "watchlist",
                "watchlist_bucket": "starter",
                "watchlist_score": 42,
                "pipeline_asset_count": 1,
                "trial_count": 0,
                "competitor_asset_count": 0,
                "catalyst_count": 0,
                "input_warning_count": 0,
                "artifacts": {
                    "manifest_json": "data/processed/manifest.json",
                    "extraction_audit": "data/processed/audit.json",
                },
            },
            "quality_gate": {"level": "decision_ready", "rationale": "ok"},
            "missing_input_count": 0,
            "extraction_audit": {
                "asset_count": 1,
                "counts": {"supported": 1, "needs_review": 0},
                "source_excerpt": {"anchor_count": 1, "missing_anchor_count": 0},
            },
            "next_actions": [],
        }

        output = io.StringIO()
        with redirect_stdout(output):
            _print_quick_report_summary(summary, save=True)

        self.assertIn(
            "- Extraction audit report: data/processed/audit.json",
            output.getvalue(),
        )

    def test_publish_quick_report_shortcuts_writes_latest_report_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memo = Path(tmpdir) / "memo.md"
            memo.write_text("# memo\n", encoding="utf-8")
            summary = {
                "identity": {"company": "DualityBio"},
                "research": {"artifacts": {"memo_markdown": str(memo)}},
            }
            payload = _publish_quick_report_shortcuts(
                summary=summary,
                output_dir=tmpdir,
                save=True,
            )
            self.assertIn("latest_report_zh", payload)
            latest_main = Path(payload["latest_report"])
            latest_zh = Path(payload["latest_report_zh"])
            self.assertTrue(latest_main.exists())
            self.assertTrue(latest_zh.exists())
            self.assertEqual(latest_main.read_text(encoding="utf-8"), "## 中文\n\n# memo\n")
            self.assertEqual(latest_zh.read_text(encoding="utf-8"), "## 中文\n\n# memo\n")

    def test_report_command_json_keeps_machine_readable_summary(self) -> None:
        fake_summary = {"identity": {"ticker": "09606.HK"}, "status": "ok"}
        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client",
            return_value=object(),
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value=fake_summary,
        ):
            run.return_value = object()
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["report", "09606.HK", "--json", "--no-save"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue()), fake_summary)

    def test_report_command_auto_degrades_when_llm_client_missing(self) -> None:
        with patch(
            "biotech_alpha.cli.run_company_report"
        ) as run, patch(
            "biotech_alpha.cli._build_llm_client",
            side_effect=RuntimeError("missing key"),
        ), patch(
            "biotech_alpha.cli.company_report_summary",
            return_value={"identity": {}, "status": "ok"},
        ):
            run.return_value = object()
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["report", "DualityBio", "--no-save"])

            self.assertEqual(exit_code, 0)
            self.assertIn(
                "unavailable; continuing without LLM", output.getvalue()
            )
            kwargs = run.call_args.kwargs
            self.assertEqual(kwargs["llm_agents"], ())
            self.assertIsNone(kwargs["llm_client"])

    def test_technical_timing_command_outputs_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "ohlcv.csv"
            lines = ["date,open,high,low,close,volume"]
            for idx in range(1, 31):
                close = 10 + idx * 0.1
                lines.append(f"2026-04-{idx:02d},10,11,9,{close:.2f},100000")
            csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["technical-timing", "--ohlcv", str(csv_path)])
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["guidance_type"], "research_only")

    def test_memo_diff_bilingual_and_export_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prev = Path(tmpdir) / "prev.md"
            curr = Path(tmpdir) / "curr.md"
            bi = Path(tmpdir) / "bi.md"
            html = Path(tmpdir) / "memo.html"
            pipeline = Path(tmpdir) / "pipeline.json"
            catalyst = Path(tmpdir) / "catalyst.csv"
            target = Path(tmpdir) / "target.json"
            prev.write_text("## Investment Committee Memo\n- A\n", encoding="utf-8")
            curr.write_text("## Investment Committee Memo\n- B\n", encoding="utf-8")
            pipeline.write_text(
                json.dumps({"assets": [{"name": "A1", "phase": "Phase 2"}]}),
                encoding="utf-8",
            )
            catalyst.write_text(
                "title,category,expected_date,expected_window,related_asset,confidence,evidence_count\n"
                "Readout,clinical,2026-05-01,Q2,Asset,0.7,1\n",
                encoding="utf-8",
            )
            target.write_text(
                json.dumps(
                    {
                        "analysis": {
                            "base": {
                                "asset_rnpv": [
                                    {"asset_name": "A1", "rnpv": 120},
                                    {"asset_name": "A2", "rnpv": 80},
                                ]
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            diff_output = io.StringIO()
            with redirect_stdout(diff_output):
                diff_exit = main(
                    ["memo-diff", "--previous", str(prev), "--current", str(curr)]
                )
            self.assertEqual(diff_exit, 0)
            self.assertTrue(json.loads(diff_output.getvalue())["has_changes"])
            bilingual_exit = main(
                ["memo-bilingual", "--input", str(curr), "--output", str(bi)]
            )
            self.assertEqual(bilingual_exit, 0)
            self.assertIn("## 中文", bi.read_text(encoding="utf-8"))
            export_output = io.StringIO()
            with redirect_stdout(export_output):
                export_exit = main(
                    [
                        "memo-export",
                        "--input",
                        str(curr),
                        "--html-output",
                        str(html),
                        "--pipeline-assets",
                        str(pipeline),
                        "--catalyst-csv",
                        str(catalyst),
                        "--target-price-json",
                        str(target),
                    ]
                )
            self.assertEqual(export_exit, 0)
            self.assertTrue(html.exists())
            html_text = html.read_text(encoding="utf-8")
            self.assertIn("id='pipeline-gantt'", html_text)
            self.assertIn("id='catalyst-timeline'", html_text)
            self.assertIn("id='rnpv-stack'", html_text)


if __name__ == "__main__":
    unittest.main()
