from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from biotech_alpha.models import Evidence, PipelineAsset
from biotech_alpha.research import result_summary, run_single_company_research


class FakeClinicalTrialsClient:
    def __init__(
        self,
        response: dict[str, Any] | None = None,
        responses_by_term: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.response = response
        self.responses_by_term = responses_by_term or {}
        self.search_terms: list[str] = []
        self.page_size: int | None = None

    def version(self) -> dict[str, Any]:
        return {"apiVersion": "test", "dataTimestamp": "2026-04-19T00:00:00Z"}

    def search_studies(
        self,
        term: str,
        *,
        page_size: int = 10,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        self.search_terms.append(term)
        self.page_size = page_size
        self.page_token = page_token
        if term in self.responses_by_term:
            return self.responses_by_term[term]
        return self.response or {"studies": []}


class SingleCompanyResearchTest(unittest.TestCase):
    def test_run_single_company_research_writes_artifacts(self) -> None:
        response = {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT00000001",
                            "briefTitle": "Study of Example Drug",
                        },
                        "statusModule": {
                            "overallStatus": "RECRUITING",
                            "primaryCompletionDateStruct": {"date": "2026-12-01"},
                            "lastUpdatePostDateStruct": {"date": "2026-04-01"},
                        },
                        "sponsorCollaboratorsModule": {
                            "leadSponsor": {"name": "Example Biotech"}
                        },
                        "designModule": {
                            "phases": ["PHASE2"],
                            "enrollmentInfo": {"count": 120},
                        },
                        "conditionsModule": {"conditions": ["Cancer"]},
                        "armsInterventionsModule": {
                            "interventions": [{"name": "Example Drug"}]
                        },
                    }
                }
            ]
        }
        client = FakeClinicalTrialsClient(response)
        now = datetime(2026, 4, 20, 8, 0, tzinfo=UTC)
        asset = PipelineAsset(
            name="Example Drug",
            aliases=("EXD-001",),
            target="Example target",
            indication="Cancer",
            phase="Phase 2",
            next_milestone="2026 data readout",
            evidence=(
                Evidence(
                    claim="Example Drug is a disclosed pipeline asset.",
                    source="company-presentation.pdf",
                    confidence=0.7,
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            financials_path = Path(tmpdir) / "financials.json"
            financials_path.write_text(
                json.dumps(
                    {
                        "as_of_date": "2025-12-31",
                        "currency": "HKD",
                        "cash_and_equivalents": 1200,
                        "short_term_debt": 300,
                        "quarterly_cash_burn": 150,
                        "source": "annual-report.pdf",
                    }
                ),
                encoding="utf-8",
            )
            competitors_path = Path(tmpdir) / "competitors.json"
            competitors_path.write_text(
                json.dumps(
                    {
                        "competitors": [
                            {
                                "company": "Competitor Bio",
                                "asset_name": "Rival Drug",
                                "target": "Example target",
                                "indication": "Cancer",
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
                ),
                encoding="utf-8",
            )
            valuation_path = Path(tmpdir) / "valuation.json"
            valuation_path.write_text(
                json.dumps(
                    {
                        "as_of_date": "2026-04-20",
                        "currency": "HKD",
                        "market_cap": 2500,
                        "cash_and_equivalents": 300,
                        "total_debt": 100,
                        "revenue_ttm": 200,
                        "source": "market-snapshot",
                    }
                ),
                encoding="utf-8",
            )
            result = run_single_company_research(
                company="Example Biotech",
                ticker="9999.HK",
                limit=1,
                output_dir=tmpdir,
                pipeline_assets=(asset,),
                financials_path=financials_path,
                competitors_path=competitors_path,
                valuation_path=valuation_path,
                client=client,
                now=now,
            )

            self.assertEqual(
                client.search_terms,
                ["Example Biotech", "Example Drug", "EXD-001"],
            )
            self.assertEqual(client.page_size, 1)
            self.assertEqual(result.memo.decision, "watchlist")
            self.assertEqual(len(result.trials), 1)
            self.assertEqual(len(result.pipeline_assets), 1)
            self.assertEqual(len(result.asset_trial_matches), 1)
            self.assertEqual(len(result.competitor_assets), 1)
            self.assertEqual(len(result.competitive_matches), 1)
            self.assertIsNotNone(result.cash_runway_estimate)
            self.assertEqual(result.cash_runway_estimate.runway_months, 18)
            self.assertIsNotNone(result.valuation_metrics)
            self.assertEqual(result.valuation_metrics.enterprise_value, 2300)
            self.assertEqual(len(result.memo.catalysts), 2)

            summary = result_summary(result)
            self.assertEqual(summary["trial_count"], 1)
            self.assertEqual(
                summary["search_terms"],
                ("Example Biotech", "Example Drug", "EXD-001"),
            )
            self.assertEqual(summary["pipeline_asset_count"], 1)
            self.assertEqual(summary["asset_trial_match_count"], 1)
            self.assertEqual(summary["competitor_asset_count"], 1)
            self.assertEqual(summary["competitive_match_count"], 1)
            self.assertEqual(summary["cash_runway_months"], 18)
            self.assertEqual(summary["enterprise_value"], 2300)
            self.assertEqual(summary["revenue_multiple"], 11.5)
            self.assertEqual(summary["input_warning_count"], 1)
            self.assertEqual(summary["catalyst_count"], 2)

            artifacts = result.artifacts
            self.assertIsNotNone(artifacts.manifest_json)
            self.assertIsNotNone(artifacts.raw_clinical_trials)
            self.assertIsNotNone(artifacts.normalized_trials)
            self.assertIsNotNone(artifacts.trial_summary_csv)
            self.assertIsNotNone(artifacts.catalyst_calendar_csv)
            self.assertIsNotNone(artifacts.pipeline_assets)
            self.assertIsNotNone(artifacts.asset_trial_matches)
            self.assertIsNotNone(artifacts.competitor_assets)
            self.assertIsNotNone(artifacts.competitive_matches)
            self.assertIsNotNone(artifacts.cash_runway)
            self.assertIsNotNone(artifacts.valuation)
            self.assertIsNotNone(artifacts.memo_json)
            self.assertIsNotNone(artifacts.memo_markdown)
            for path in (
                artifacts.manifest_json,
                artifacts.raw_clinical_trials,
                artifacts.normalized_trials,
                artifacts.trial_summary_csv,
                artifacts.catalyst_calendar_csv,
                artifacts.pipeline_assets,
                artifacts.asset_trial_matches,
                artifacts.competitor_assets,
                artifacts.competitive_matches,
                artifacts.cash_runway,
                artifacts.valuation,
                artifacts.memo_json,
                artifacts.memo_markdown,
            ):
                self.assertTrue(Path(path).exists())

            memo_payload = json.loads(Path(artifacts.memo_json).read_text())
            self.assertEqual(memo_payload["company"], "Example Biotech")
            self.assertEqual(
                memo_payload["catalysts"][0]["expected_date"],
                "2026-12-01",
            )
            self.assertEqual(memo_payload["key_assets"][0]["name"], "Example Drug")
            csv_text = Path(artifacts.trial_summary_csv).read_text()
            self.assertIn("registry_id,title,sponsor,status,phase", csv_text)
            self.assertIn("NCT00000001,Study of Example Drug", csv_text)
            catalyst_csv = Path(artifacts.catalyst_calendar_csv).read_text()
            self.assertIn("title,category,expected_date", catalyst_csv)
            self.assertIn("2026-12-01", catalyst_csv)
            self.assertIn("2026 data readout", catalyst_csv)
            memo_markdown = Path(artifacts.memo_markdown).read_text()
            self.assertIn("## Key Risks", memo_markdown)
            self.assertIn("## Competitive Landscape", memo_markdown)
            self.assertIn("Input validation produced 1 warning(s)", memo_markdown)
            self.assertIn("Example Drug matched NCT00000001", memo_markdown)
            self.assertIn("Rival Drug by target_indication", memo_markdown)
            self.assertIn("enterprise value is 2300 HKD", memo_markdown)

            raw_payload = json.loads(Path(artifacts.raw_clinical_trials).read_text())
            self.assertEqual(
                raw_payload["search_terms"],
                ["Example Biotech", "Example Drug", "EXD-001"],
            )
            self.assertEqual(
                sorted(raw_payload["responses"]),
                ["EXD-001", "Example Biotech", "Example Drug"],
            )
            manifest = json.loads(Path(artifacts.manifest_json).read_text())
            self.assertEqual(manifest["run_id"], "20260420T080000Z")
            self.assertEqual(manifest["counts"]["trials"], 1)
            self.assertEqual(manifest["counts"]["pipeline_assets"], 1)
            self.assertEqual(manifest["counts"]["competitor_assets"], 1)
            self.assertEqual(manifest["counts"]["competitive_matches"], 1)
            self.assertEqual(manifest["counts"]["cash_runway"], 1)
            self.assertEqual(manifest["counts"]["valuation"], 1)
            self.assertIn("financials", manifest["input_validation"])
            self.assertIn("competitors", manifest["input_validation"])
            self.assertIn("valuation", manifest["input_validation"])
            self.assertIn(
                "replace placeholder source",
                manifest["input_validation"]["financials"]["warnings"],
            )
            self.assertIn("memo_markdown", manifest["artifacts"])
            cash_runway = json.loads(Path(artifacts.cash_runway).read_text())
            self.assertEqual(cash_runway["estimate"]["runway_months"], 18)
            valuation = json.loads(Path(artifacts.valuation).read_text())
            self.assertEqual(valuation["metrics"]["enterprise_value"], 2300)
            competitive_matches = json.loads(
                Path(artifacts.competitive_matches).read_text()
            )
            self.assertEqual(
                competitive_matches["matches"][0]["competitor_asset"],
                "Rival Drug",
            )

    def test_run_single_company_research_handles_empty_search(self) -> None:
        client = FakeClinicalTrialsClient({"studies": []})
        result = run_single_company_research(
            company="No Data Bio",
            save=False,
            client=client,
            now=datetime(2026, 4, 20, tzinfo=UTC),
        )

        self.assertEqual(result.memo.decision, "insufficient_data")
        self.assertTrue(result.clinical_trial_finding.needs_human_review)
        self.assertTrue(result.memo.findings[1].needs_human_review)
        self.assertIn(
            "No curated pipeline asset input was provided",
            result.memo.findings[1].risks,
        )
        self.assertEqual(result.artifacts.memo_json, None)

    def test_asset_queries_find_trials_not_found_by_company_query(self) -> None:
        company_response = {"studies": []}
        asset_response = {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT00000002",
                            "briefTitle": "Study of Partnered Drug",
                        },
                        "statusModule": {"overallStatus": "RECRUITING"},
                        "designModule": {"phases": ["PHASE1"]},
                        "armsInterventionsModule": {
                            "interventions": [{"name": "Partnered Drug"}]
                        },
                    }
                }
            ]
        }
        duplicate_alias_response = {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT00000002",
                            "briefTitle": "Study of Partnered Drug Duplicate",
                        },
                        "statusModule": {"overallStatus": "RECRUITING"},
                        "designModule": {"phases": ["PHASE1"]},
                    }
                }
            ]
        }
        client = FakeClinicalTrialsClient(
            responses_by_term={
                "Example Biotech": company_response,
                "Partnered Drug": asset_response,
                "PRD-001": duplicate_alias_response,
            }
        )
        asset = PipelineAsset(name="Partnered Drug", aliases=("PRD-001",))

        result = run_single_company_research(
            company="Example Biotech",
            pipeline_assets=(asset,),
            save=False,
            client=client,
            now=datetime(2026, 4, 20, tzinfo=UTC),
        )

        self.assertEqual(
            client.search_terms,
            ["Example Biotech", "Partnered Drug", "PRD-001"],
        )
        self.assertEqual(len(result.trials), 1)
        self.assertEqual(result.trials[0].registry_id, "NCT00000002")
        self.assertEqual(len(result.asset_trial_matches), 1)
        self.assertEqual(result.memo.decision, "watchlist")


if __name__ == "__main__":
    unittest.main()
