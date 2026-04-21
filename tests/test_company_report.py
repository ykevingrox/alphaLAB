from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from biotech_alpha.company_report import (
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
            financials.write_text("{}", encoding="utf-8")
            pipeline.write_text("{}", encoding="utf-8")
            identity = resolve_company_identity(
                company="DualityBio",
                ticker="09606.HK",
                registry_path=None,
            )

            paths = discover_company_inputs(identity, input_dir=root)

            self.assertEqual(paths.financials, financials)
            self.assertEqual(paths.pipeline_assets, pipeline)
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
            self.assertEqual(len(result.missing_inputs), 5)
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
            self.assertIn("company-report", payload["rerun_command"])


if __name__ == "__main__":
    unittest.main()
