from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from biotech_alpha.competition import (
    competitive_landscape_finding,
    competitor_template,
    load_competitor_assets,
    match_competitors_to_pipeline,
    validate_competitor_file,
    write_competitor_template,
)
from biotech_alpha.models import PipelineAsset


class CompetitionTest(unittest.TestCase):
    def test_competitor_template_can_be_written_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "competitors.json"

            written_path = write_competitor_template(
                path=path,
                company="Example Biotech",
                ticker="9999.HK",
            )
            payload = json.loads(written_path.read_text())
            competitors = load_competitor_assets(written_path)
            report = validate_competitor_file(written_path)

        self.assertEqual(payload["company"], "Example Biotech")
        self.assertEqual(payload["ticker"], "9999.HK")
        self.assertEqual(len(competitors), 1)
        self.assertEqual(competitors[0].asset_name, "Example competitor asset")
        self.assertIn(
            "Example competitor asset: replace placeholder asset",
            report.warnings,
        )

    def test_competitor_template_refuses_to_overwrite_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "competitors.json"
            write_competitor_template(path=path, company="Example Biotech")

            with self.assertRaises(FileExistsError):
                write_competitor_template(path=path, company="Example Biotech")

    def test_match_competitors_to_pipeline_by_target_and_indication(self) -> None:
        assets = (
            PipelineAsset(
                name="Example Drug",
                target="PD-1/VEGF",
                indication="NSCLC",
            ),
        )
        payload = {
            "competitors": [
                {
                    "company": "Competitor Bio",
                    "asset_name": "Rival Drug",
                    "target": "PD-1/VEGF",
                    "indication": "NSCLC",
                    "phase": "Phase 3",
                    "evidence": [
                        {
                            "claim": "Rival Drug is in Phase 3.",
                            "source": "competitor.pdf",
                        }
                    ],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "competitors.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            competitors = load_competitor_assets(path)

        matches = match_competitors_to_pipeline(assets, competitors)
        finding = competitive_landscape_finding(
            company="Example Biotech",
            assets=assets,
            competitors=competitors,
            matches=matches,
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].match_scope, "target_indication")
        self.assertEqual(matches[0].confidence, 0.8)
        self.assertIn("1 company assets matched 1", finding.summary)
        self.assertTrue(finding.needs_human_review)

    def test_validate_competitor_file_reports_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "competitors.json"
            path.write_text(json.dumps({"competitors": [{"company": "No Asset"}]}))

            report = validate_competitor_file(path)

        self.assertEqual(report.competitor_count, 0)
        self.assertTrue(report.errors)

    def test_competitor_template_requires_company(self) -> None:
        with self.assertRaises(ValueError):
            competitor_template(company=" ")


if __name__ == "__main__":
    unittest.main()
