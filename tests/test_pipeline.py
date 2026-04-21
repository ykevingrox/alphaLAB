from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from biotech_alpha.models import TrialSummary
from biotech_alpha.pipeline import (
    load_pipeline_assets,
    match_pipeline_assets_to_trials,
    pipeline_asset_template,
    validate_pipeline_asset_file,
    write_pipeline_asset_template,
)


class PipelineAssetTest(unittest.TestCase):
    def test_load_pipeline_assets_from_json_object(self) -> None:
        payload = {
            "assets": [
                {
                    "name": "Ivonescimab",
                    "aliases": ["AK112", "SMT112"],
                    "target": "PD-1/VEGF",
                    "indication": "NSCLC",
                    "phase": "Phase 3",
                    "next_milestone": "2026 readout",
                    "evidence": [
                        {
                            "claim": "Ivonescimab appears in the pipeline table.",
                            "source": "company-presentation.pdf",
                            "confidence": 0.8,
                        }
                    ],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "assets.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            assets = load_pipeline_assets(path)

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].name, "Ivonescimab")
        self.assertEqual(assets[0].aliases, ("AK112", "SMT112"))
        self.assertEqual(assets[0].target, "PD-1/VEGF")
        self.assertEqual(assets[0].evidence[0].confidence, 0.8)

    def test_match_pipeline_assets_to_trials_by_intervention_and_title(self) -> None:
        payload = {
            "assets": [
                {"name": "Ivonescimab", "aliases": ["AK112"]},
                {"name": "Ligufalimab", "aliases": ["AK117"]},
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "assets.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            assets = load_pipeline_assets(path)

        trials = (
            TrialSummary(
                registry="ClinicalTrials.gov",
                registry_id="NCT00000001",
                title="Study of AK112 in lung cancer",
                interventions=("Ivonescimab injection",),
            ),
            TrialSummary(
                registry="ClinicalTrials.gov",
                registry_id="NCT00000002",
                title="Study of AK117 in solid tumors",
                interventions=(),
            ),
        )

        matches = match_pipeline_assets_to_trials(assets, trials)

        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0].match_reason, "intervention")
        self.assertEqual(matches[0].confidence, 0.9)
        self.assertEqual(matches[1].match_reason, "title")
        self.assertEqual(matches[1].confidence, 0.75)

    def test_pipeline_asset_template_can_be_written_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "example_pipeline_assets.json"

            written_path = write_pipeline_asset_template(
                path=path,
                company="Example Biotech",
                ticker="9999.HK",
            )
            payload = json.loads(written_path.read_text())
            assets = load_pipeline_assets(written_path)
            report = validate_pipeline_asset_file(written_path)

        self.assertEqual(payload["company"], "Example Biotech")
        self.assertEqual(payload["ticker"], "9999.HK")
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].name, "Example asset name")
        self.assertIn(
            "Example asset name: replace template placeholder asset name",
            report.warnings,
        )

    def test_pipeline_asset_template_refuses_to_overwrite_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "assets.json"
            write_pipeline_asset_template(path=path, company="Example Biotech")

            with self.assertRaises(FileExistsError):
                write_pipeline_asset_template(path=path, company="Example Biotech")

            write_pipeline_asset_template(
                path=path,
                company="Replacement Biotech",
                overwrite=True,
            )
            payload = json.loads(path.read_text())

        self.assertEqual(payload["company"], "Replacement Biotech")

    def test_validate_pipeline_asset_file_reports_actionable_warnings(self) -> None:
        payload = {"assets": [{"name": "Sparse Asset"}]}

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "assets.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            report = validate_pipeline_asset_file(path)

        self.assertEqual(report.asset_count, 1)
        self.assertEqual(report.evidence_count, 0)
        self.assertEqual(report.errors, ())
        self.assertIn("Sparse Asset: missing evidence", report.warnings)
        self.assertIn("Sparse Asset: missing indication", report.warnings)

    def test_validate_pipeline_asset_file_reports_invalid_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "assets.json"
            path.write_text(json.dumps({"assets": [{"aliases": ["NO-NAME"]}]}))

            report = validate_pipeline_asset_file(path)

        self.assertEqual(report.asset_count, 0)
        self.assertTrue(report.errors)

    def test_pipeline_asset_template_requires_company(self) -> None:
        with self.assertRaises(ValueError):
            pipeline_asset_template(company=" ")


if __name__ == "__main__":
    unittest.main()
