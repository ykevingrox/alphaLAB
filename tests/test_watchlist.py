from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from biotech_alpha.watchlist import (
    load_watchlist_entries,
    rank_watchlist_entries,
    watchlist_entries_as_dicts,
    watchlist_entries_to_csv_text,
)


class WatchlistTest(unittest.TestCase):
    def test_loads_and_ranks_saved_research_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "single_company"
            self._write_run(
                root=root,
                slug="alpha",
                run_id="20260420T010000Z",
                company="Alpha Bio",
                ticker="1111.HK",
                score=58.0,
                bucket="watchlist",
                warnings=["replace placeholder source"],
            )
            self._write_run(
                root=root,
                slug="beta",
                run_id="20260420T020000Z",
                company="Beta Bio",
                ticker="2222.HK",
                score=72.5,
                bucket="priority_review",
                warnings=[],
            )

            entries = rank_watchlist_entries(load_watchlist_entries(root))
            rows = watchlist_entries_as_dicts(entries)

            self.assertEqual(
                [entry.company for entry in entries],
                ["Beta Bio", "Alpha Bio"],
            )
            self.assertEqual(rows[0]["rank"], 1)
            self.assertEqual(rows[0]["watchlist_score"], 72.5)
            self.assertEqual(rows[1]["input_warning_count"], 1)
            self.assertEqual(rows[0]["cash_runway_months"], 24.0)
            self.assertEqual(rows[0]["enterprise_value"], 1500.0)
            self.assertEqual(rows[0]["revenue_multiple"], 7.5)
            self.assertEqual(rows[0]["targets"], ["PD-1"])
            self.assertEqual(rows[0]["indications"], ["NSCLC"])
            self.assertEqual(rows[0]["target_concentration_count"], 2)
            self.assertEqual(rows[0]["research_position_limit_pct"], 1.0)
            self.assertEqual(rows[1]["research_position_limit_pct"], 0.5)
            self.assertIn("input_validation_warnings", rows[1]["guardrail_flags"])

    def test_csv_output_includes_header_and_joined_monitoring_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "single_company"
            self._write_run(
                root=root,
                slug="alpha",
                run_id="20260420T010000Z",
                company="Alpha Bio",
                ticker=None,
                score=40.0,
                bucket="low_priority",
                warnings=[],
            )

            entries = rank_watchlist_entries(load_watchlist_entries(root))
            text = watchlist_entries_to_csv_text(entries)

            self.assertIn("rank,company,ticker,run_id", text)
            self.assertIn("Check next clinical catalyst; Review data quality", text)
            self.assertIn("PD-1", text)

    def test_concentration_guardrail_caps_high_score_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "single_company"
            for index, score in enumerate((82.0, 76.0, 64.0), start=1):
                self._write_run(
                    root=root,
                    slug=f"company-{index}",
                    run_id=f"20260420T0{index}0000Z",
                    company=f"Company {index}",
                    ticker=None,
                    score=score,
                    bucket="deep_dive_candidate",
                    warnings=[],
                )

            rows = watchlist_entries_as_dicts(
                rank_watchlist_entries(load_watchlist_entries(root))
            )

            self.assertEqual(rows[0]["target_concentration_count"], 3)
            self.assertEqual(rows[0]["indication_concentration_count"], 3)
            self.assertEqual(rows[0]["research_position_limit_pct"], 1.0)
            self.assertIn("target_concentration", rows[0]["guardrail_flags"])
            self.assertIn("indication_concentration", rows[0]["guardrail_flags"])

    def _write_run(
        self,
        *,
        root: Path,
        slug: str,
        run_id: str,
        company: str,
        ticker: str | None,
        score: float,
        bucket: str,
        warnings: list[str],
    ) -> None:
        run_dir = root / slug
        memo_dir = root.parent / "memos" / slug
        run_dir.mkdir(parents=True)
        memo_dir.mkdir(parents=True)

        scorecard_path = run_dir / f"{run_id}_scorecard.json"
        cash_path = run_dir / f"{run_id}_cash_runway.json"
        pipeline_path = run_dir / f"{run_id}_pipeline_assets.json"
        valuation_path = run_dir / f"{run_id}_valuation.json"
        memo_path = memo_dir / f"{run_id}_memo.md"
        manifest_path = run_dir / f"{run_id}_manifest.json"

        scorecard_path.write_text(
            json.dumps(
                {
                    "total_score": score,
                    "bucket": bucket,
                    "needs_human_review": bool(warnings),
                    "monitoring_rules": [
                        "Check next clinical catalyst",
                        "Review data quality",
                    ],
                }
            ),
            encoding="utf-8",
        )
        cash_path.write_text(
            json.dumps({"estimate": {"runway_months": 24.0}}),
            encoding="utf-8",
        )
        pipeline_path.write_text(
            json.dumps(
                {
                    "assets": [
                        {
                            "name": "Example Drug",
                            "target": "PD-1",
                            "indication": "NSCLC",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        valuation_path.write_text(
            json.dumps(
                {
                    "metrics": {
                        "enterprise_value": 1500.0,
                        "revenue_multiple": 7.5,
                    }
                }
            ),
            encoding="utf-8",
        )
        memo_path.write_text("# memo\n", encoding="utf-8")
        manifest_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "company": company,
                    "ticker": ticker,
                    "retrieved_at": "2026-04-20T01:00:00+00:00",
                    "input_validation": {
                        "pipeline_assets": {"warnings": warnings},
                    },
                    "counts": {
                        "trials": 3,
                        "pipeline_assets": 2,
                        "asset_trial_matches": 1,
                        "competitor_assets": 4,
                        "competitive_matches": 2,
                        "catalysts": 1,
                    },
                    "artifacts": {
                        "scorecard": str(scorecard_path),
                        "cash_runway": str(cash_path),
                        "pipeline_assets": str(pipeline_path),
                        "valuation": str(valuation_path),
                        "memo_markdown": str(memo_path),
                    },
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
