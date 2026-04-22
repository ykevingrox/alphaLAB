from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from biotech_alpha.auto_inputs import AutoInputArtifacts, SourceDocument
from biotech_alpha.company_report import (
    company_report_summary,
    discover_company_inputs,
    resolve_company_identity,
    run_company_report,
)


class FakeClinicalTrialsClient:
    def __init__(self) -> None:
        self.search_terms: list[str] = []

    def version(self) -> dict[str, Any]:
        return {"apiVersion": "test"}

    def search_studies(
        self,
        term: str,
        *,
        page_size: int = 10,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        self.search_terms.append(term)
        return {"studies": []}


class CompanyReportTest(unittest.TestCase):
    def test_resolves_identity_from_ticker_only(self) -> None:
        identity = resolve_company_identity(
            ticker="09606.HK",
            registry_path=None,
        )
        self.assertEqual(identity.company, "09606.HK")
        self.assertEqual(identity.ticker, "09606.HK")
        self.assertEqual(identity.market, "HK")
        self.assertEqual(identity.search_term, "09606.HK")

    def test_resolves_company_from_optional_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "company_registry.json"
            registry.write_text(
                json.dumps(
                    {
                        "companies": [
                            {
                                "company": "DualityBio",
                                "ticker": "09606.HK",
                                "market": "HK",
                                "sector": "biotech",
                                "search_term": "DualityBio",
                                "aliases": ["映恩生物"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            identity = resolve_company_identity(
                company="映恩生物",
                registry_path=registry,
            )

            self.assertEqual(identity.company, "映恩生物")
            self.assertEqual(identity.ticker, "09606.HK")
            self.assertEqual(identity.market, "HK")
            self.assertEqual(identity.search_term, "DualityBio")
            self.assertEqual(identity.aliases, ("映恩生物",))
            self.assertEqual(identity.registry_match, "DualityBio")

    def test_discovers_curated_inputs_by_ticker_or_company_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            financials = root / "dualitybio_09606_financials.json"
            pipeline = root / "dualitybio_09606_pipeline_assets.json"
            conference = root / "dualitybio_09606_conference_catalysts.json"
            financials.write_text("{}", encoding="utf-8")
            pipeline.write_text("{}", encoding="utf-8")
            conference.write_text("{}", encoding="utf-8")
            identity = resolve_company_identity(
                company="DualityBio",
                ticker="09606.HK",
                registry_path=None,
            )

            paths = discover_company_inputs(identity, input_dir=root)

            self.assertEqual(paths.financials, financials)
            self.assertEqual(paths.pipeline_assets, pipeline)
            self.assertEqual(paths.conference_catalysts, conference)
            self.assertIsNone(paths.competitors)

    def test_company_report_runs_with_missing_input_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = FakeClinicalTrialsClient()
            result = run_company_report(
                company="No Data Bio",
                input_dir=Path(tmpdir) / "input",
                output_dir=tmpdir,
                limit=1,
                client=client,
                now=datetime(2026, 4, 21, tzinfo=UTC),
            )

            self.assertEqual(result.identity.company, "No Data Bio")
            self.assertEqual(result.identity.market, "HK")
            self.assertEqual(client.search_terms, ["No Data Bio"])
            self.assertEqual(result.research_result.memo.decision, "insufficient_data")
            self.assertEqual(len(result.missing_inputs), 6)
            self.assertIn(
                "pipeline-template",
                result.missing_inputs[0].template_command,
            )
            self.assertIn(
                "Create the pipeline template",
                result.missing_inputs[0].next_action,
            )
            self.assertIsNotNone(result.missing_inputs_report)
            payload = json.loads(Path(result.missing_inputs_report).read_text())
            self.assertEqual(payload["run_id"], "20260421T000000Z")
            self.assertEqual(payload["missing_inputs"][0]["key"], "pipeline_assets")
            self.assertIn("next_actions", payload)
            self.assertIn("First create", payload["next_actions"][0])
            self.assertEqual(payload["quality_gate"]["level"], "incomplete")
            self.assertIn("company-report", payload["rerun_command"])
            self.assertNotIn("--auto-inputs", payload["rerun_command"])

    def test_company_report_uses_generated_inputs_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generated = root / "generated"
            generated.mkdir()
            pipeline = generated / "09606_hk_pipeline_assets.json"
            financials = generated / "09606_hk_financials.json"
            pipeline.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "name": "DB-1303",
                                "aliases": ["BNT323"],
                                "target": "HER2",
                                "indication": "breast cancer",
                                "phase": "Phase 3",
                                "evidence": [
                                    {
                                        "claim": "DB-1303 is disclosed.",
                                        "source": "source.pdf",
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            financials.write_text(
                json.dumps(
                    {
                        "as_of_date": "2025-12-31",
                        "currency": "RMB",
                        "cash_and_equivalents": 1000,
                        "short_term_debt": 0,
                        "quarterly_cash_burn": 100,
                        "source": "source.pdf",
                    }
                ),
                encoding="utf-8",
            )

            with patch("biotech_alpha.auto_inputs.generate_auto_inputs") as generate:
                generate.return_value = AutoInputArtifacts(
                    pipeline_assets=pipeline,
                    financials=financials,
                    source_documents=(
                        SourceDocument(
                            source_type="hkex_annual_results",
                            title="Annual Results",
                            url="https://example.com/results.pdf",
                            publication_date="2026-03-23",
                            file_path=root / "results.pdf",
                            text_path=root / "results.txt",
                            stock_code="09606",
                            stock_name="DUALITYBIO-B",
                        ),
                    ),
                )
                client = FakeClinicalTrialsClient()
                result = run_company_report(
                    company="映恩生物",
                    ticker="09606.HK",
                    input_dir=root / "manual",
                    generated_input_dir=generated,
                    output_dir=root / "out",
                    auto_inputs=True,
                    limit=1,
                    client=client,
                    now=datetime(2026, 4, 21, tzinfo=UTC),
                )

            self.assertEqual(result.identity.search_term, "DUALITYBIO")
            self.assertIn("DUALITYBIO-B", result.identity.aliases)
            self.assertIn("DUALITYBIO", result.identity.aliases)
            self.assertEqual(client.search_terms[0], "DUALITYBIO")
            self.assertEqual(result.input_paths.pipeline_assets, pipeline)
            self.assertEqual(result.input_paths.financials, financials)
            self.assertEqual(len(result.research_result.pipeline_assets), 1)
            self.assertIsNotNone(result.missing_inputs_report)
            payload = json.loads(Path(result.missing_inputs_report).read_text())
            summary = company_report_summary(result)
            self.assertIn("--auto-inputs", payload["rerun_command"])
            self.assertIn("--auto-inputs", summary["rerun_command"])
            self.assertTrue(
                any("--auto-inputs" in action for action in summary["next_actions"])
            )

    def test_company_report_prefers_manual_inputs_over_generated_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            manual = root / "manual"
            generated = root / "generated"
            manual.mkdir()
            generated.mkdir()

            manual_pipeline = manual / "09606_hk_pipeline_assets.json"
            generated_pipeline = generated / "09606_hk_pipeline_assets.json"
            manual_financials = manual / "09606_hk_financials.json"
            generated_financials = generated / "09606_hk_financials.json"

            manual_pipeline.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "name": "MANUAL-DRUG",
                                "aliases": [],
                                "target": "HER2",
                                "indication": "cancer",
                                "phase": "Phase 2",
                                "evidence": [
                                    {"claim": "manual", "source": "manual.pdf"}
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            generated_pipeline.write_text(
                json.dumps(
                    {
                        "assets": [
                            {
                                "name": "GENERATED-DRUG",
                                "aliases": [],
                                "target": "HER2",
                                "indication": "cancer",
                                "phase": "Phase 2",
                                "evidence": [
                                    {"claim": "generated", "source": "generated.pdf"}
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            manual_financials.write_text(
                json.dumps(
                    {
                        "as_of_date": "2025-12-31",
                        "currency": "HKD",
                        "cash_and_equivalents": 1000,
                        "short_term_debt": 0,
                        "quarterly_cash_burn": 100,
                        "source": "manual.pdf",
                    }
                ),
                encoding="utf-8",
            )
            generated_financials.write_text(
                json.dumps(
                    {
                        "as_of_date": "2025-12-31",
                        "currency": "HKD",
                        "cash_and_equivalents": 2000,
                        "short_term_debt": 0,
                        "quarterly_cash_burn": 100,
                        "source": "generated.pdf",
                    }
                ),
                encoding="utf-8",
            )

            with patch("biotech_alpha.auto_inputs.generate_auto_inputs") as generate:
                generate.return_value = AutoInputArtifacts(
                    pipeline_assets=generated_pipeline,
                    financials=generated_financials,
                )
                result = run_company_report(
                    company="DualityBio",
                    ticker="09606.HK",
                    input_dir=manual,
                    generated_input_dir=generated,
                    output_dir=root / "out",
                    auto_inputs=True,
                    limit=1,
                    client=FakeClinicalTrialsClient(),
                    now=datetime(2026, 4, 21, tzinfo=UTC),
                )

            self.assertEqual(result.input_paths.pipeline_assets, manual_pipeline)
            self.assertEqual(result.input_paths.financials, manual_financials)
            self.assertEqual(
                result.research_result.pipeline_assets[0].name,
                "MANUAL-DRUG",
            )

    def test_company_report_continues_when_auto_inputs_raise_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("biotech_alpha.auto_inputs.generate_auto_inputs") as generate:
                generate.side_effect = RuntimeError("hkex unavailable")
                result = run_company_report(
                    company="DualityBio",
                    ticker="09606.HK",
                    input_dir=Path(tmpdir) / "manual",
                    generated_input_dir=Path(tmpdir) / "generated",
                    output_dir=Path(tmpdir) / "out",
                    auto_inputs=True,
                    limit=1,
                    client=FakeClinicalTrialsClient(),
                    now=datetime(2026, 4, 21, tzinfo=UTC),
                )

            self.assertIsNotNone(result.auto_input_artifacts)
            self.assertTrue(result.auto_input_artifacts.warnings)
            self.assertIn(
                "auto input generation failed",
                result.auto_input_artifacts.warnings[0],
            )
            self.assertEqual(result.research_result.memo.decision, "insufficient_data")
            self.assertEqual(len(result.missing_inputs), 6)

    def test_company_report_handles_auto_inputs_warning_only_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with patch("biotech_alpha.auto_inputs.generate_auto_inputs") as generate:
                generate.return_value = AutoInputArtifacts(
                    warnings=("unable to resolve HKEX stock id",)
                )
                result = run_company_report(
                    company="DualityBio",
                    ticker="09606.HK",
                    input_dir=root / "manual",
                    generated_input_dir=root / "generated",
                    output_dir=root / "out",
                    auto_inputs=True,
                    limit=1,
                    client=FakeClinicalTrialsClient(),
                    now=datetime(2026, 4, 21, tzinfo=UTC),
                )

            self.assertEqual(len(result.missing_inputs), 6)
            self.assertEqual(
                result.auto_input_artifacts.warnings,
                ("unable to resolve HKEX stock id",),
            )


if __name__ == "__main__":
    unittest.main()
