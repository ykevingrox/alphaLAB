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
    _build_source_text_excerpt,
    _run_date_from_run_id,
    build_llm_agent_facts,
    company_report_summary,
    discover_company_inputs,
    resolve_company_identity,
    run_company_report,
)
from biotech_alpha.llm import FakeLLMClient


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

    def test_discovers_inputs_without_cross_ticker_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            wrong = root / "02142_hk_pipeline_assets.json"
            right = root / "09606_hk_pipeline_assets.json"
            wrong.write_text("{}", encoding="utf-8")
            right.write_text("{}", encoding="utf-8")
            identity = resolve_company_identity(
                company="DualityBio",
                ticker="09606.HK",
                registry_path=None,
            )

            paths = discover_company_inputs(identity, input_dir=root)

            self.assertEqual(paths.pipeline_assets, right)

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

    def test_company_report_can_write_hkexnews_updates_artifact(self) -> None:
        rss_text = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>HKEXnews</title>
    <item>
      <title>09606 - Voluntary Announcement</title>
      <link>https://www.hkexnews.hk/abc</link>
      <guid>hkex-abc</guid>
      <pubDate>Thu, 23 Apr 2026 10:00:00 +0800</pubDate>
      <category>Announcement</category>
    </item>
  </channel>
</rss>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            feed_path = root / "hkex_feed.xml"
            state_path = root / "hkex_seen.json"
            feed_path.write_text(rss_text, encoding="utf-8")
            result = run_company_report(
                company="DualityBio",
                ticker="09606.HK",
                input_dir=root / "input",
                output_dir=root / "out",
                limit=1,
                client=FakeClinicalTrialsClient(),
                now=datetime(2026, 4, 21, tzinfo=UTC),
                hkexnews_feed_file=feed_path,
                hkexnews_state_file=state_path,
            )
            self.assertIsNotNone(result.hkexnews_updates_path)
            assert result.hkexnews_updates_path is not None
            hkex_payload = json.loads(
                Path(result.hkexnews_updates_path).read_text(encoding="utf-8")
            )
            self.assertEqual(hkex_payload["new_count"], 1)
            self.assertEqual(hkex_payload["ticker_filter"], "09606.HK")
            summary = company_report_summary(result)
            self.assertEqual(
                summary["hkexnews_updates_path"],
                str(result.hkexnews_updates_path),
            )
            manifest = json.loads(
                Path(result.research_result.artifacts.manifest_json).read_text()
            )
            self.assertIn("hkexnews_updates", manifest["artifacts"])
            self.assertEqual(manifest["hkexnews_updates"]["new_count"], 1)

    def test_saved_memo_includes_llm_addendum(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = FakeClinicalTrialsClient()
            llm = FakeLLMClient(model="fake-qwen")
            llm.queue(
                json.dumps(
                    {
                        "summary": (
                            "Pipeline evidence is thin enough that the "
                            "investment case needs manual review."
                        ),
                        "bear_case": ["Registry coverage remains limited."],
                        "risks": [
                            {
                                "description": (
                                    "No asset-level clinical anchor was found."
                                ),
                                "severity": "medium",
                                "related_asset": None,
                            }
                        ],
                        "confidence": 0.7,
                    }
                ),
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
            )

            result = run_company_report(
                company="No Data Bio",
                input_dir=Path(tmpdir) / "input",
                output_dir=tmpdir,
                limit=1,
                client=client,
                now=datetime(2026, 4, 21, tzinfo=UTC),
                llm_agents=("scientific-skeptic",),
                llm_client=llm,
            )

            memo_path = result.research_result.artifacts.memo_markdown
            assert memo_path is not None
            memo_text = Path(memo_path).read_text(encoding="utf-8")
            self.assertIn("## LLM Agent Addendum", memo_text)
            self.assertIn("Run status: 2/2 steps OK", memo_text)
            self.assertIn("Total LLM tokens: 30", memo_text)
            self.assertIn("Pipeline evidence is thin enough", memo_text)
            self.assertIn("No asset-level clinical anchor was found", memo_text)
            findings_path = (
                Path(tmpdir) / "memos" / "20260421T000000Z_llm_findings.json"
            )
            self.assertTrue(findings_path.exists())

    def test_company_report_uses_generated_inputs_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generated = root / "generated"
            generated.mkdir()
            pipeline = generated / "09606_hk_pipeline_assets.json"
            financials = generated / "09606_hk_financials.json"
            text_path = root / "results.txt"
            text_path.write_text(
                "DB-1303 HER2 ADC Phase 3 in breast cancer.",
                encoding="utf-8",
            )
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
                                        "source_date": "2026-03-23",
                                        "confidence": 0.8,
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
                            text_path=text_path,
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
            audit = summary["extraction_audit"]
            self.assertEqual(audit["asset_count"], 1)
            self.assertEqual(audit["counts"]["supported"], 1)
            self.assertEqual(audit["source_excerpt"]["anchor_count"], 1)
            audit_path = result.research_result.artifacts.extraction_audit
            self.assertIsNotNone(audit_path)
            audit_payload = json.loads(Path(audit_path).read_text())
            self.assertEqual(audit_payload["run_id"], "20260421T000000Z")
            self.assertEqual(
                audit_payload["extraction_audit"]["counts"]["supported"],
                1,
            )
            manifest = json.loads(
                Path(result.research_result.artifacts.manifest_json).read_text()
            )
            self.assertEqual(
                manifest["artifacts"]["extraction_audit"],
                str(audit_path),
            )
            self.assertEqual(
                summary["research"]["artifacts"]["extraction_audit"],
                str(audit_path),
            )
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
            manual_target_price = manual / "09606_hk_target_price_assumptions.json"
            generated_target_price = (
                generated / "09606_hk_target_price_assumptions.json"
            )

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
            manual_target_price.write_text(
                json.dumps(
                    {
                        "as_of_date": "2026-04-21",
                        "currency": "HKD",
                        "share_price": 10.0,
                        "shares_outstanding": 100_000_000,
                        "cash_and_equivalents": 1_000_000_000,
                        "total_debt": 0,
                        "expected_dilution_pct": 0.0,
                        "assets": [
                            {
                                "name": "MANUAL-DRUG",
                                "indication": "cancer",
                                "phase": "Phase 2",
                                "peak_sales": 2_000_000_000,
                                "probability_of_success": 0.3,
                                "economics_share": 1.0,
                                "operating_margin": 0.35,
                                "launch_year": 2031,
                                "discount_rate": 0.12,
                                "source": "manual.pdf",
                                "source_date": "2026-04-21",
                            }
                        ],
                        "event_impacts": [],
                    }
                ),
                encoding="utf-8",
            )
            generated_target_price.write_text(
                json.dumps(
                    {
                        "as_of_date": "2026-04-21",
                        "currency": "HKD",
                        "share_price": 1.0,
                        "shares_outstanding": 1.0,
                        "cash_and_equivalents": 0,
                        "total_debt": 0,
                        "expected_dilution_pct": 0.0,
                        "assets": [
                            {
                                "name": "GENERATED-DRUG",
                                "indication": "cancer",
                                "phase": "Phase 2",
                                "peak_sales": 1_000_000_000,
                                "probability_of_success": 0.2,
                                "economics_share": 1.0,
                                "operating_margin": 0.35,
                                "launch_year": 2032,
                                "discount_rate": 0.12,
                                "source": "generated.pdf",
                                "source_date": "2026-04-21",
                            }
                        ],
                        "event_impacts": [],
                    }
                ),
                encoding="utf-8",
            )

            with patch("biotech_alpha.auto_inputs.generate_auto_inputs") as generate:
                generate.return_value = AutoInputArtifacts(
                    pipeline_assets=generated_pipeline,
                    financials=generated_financials,
                    target_price_assumptions=generated_target_price,
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
                result.input_paths.target_price_assumptions,
                manual_target_price,
            )
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


class SourceTextExcerptTest(unittest.TestCase):
    """Regression tests for `_build_source_text_excerpt` multi-anchor logic."""

    def _artifacts_with_text(self, root: Path, text: str) -> AutoInputArtifacts:
        text_path = root / "results.txt"
        text_path.write_text(text, encoding="utf-8")
        return AutoInputArtifacts(
            source_documents=(
                SourceDocument(
                    source_type="hkex_annual_results",
                    title="Annual Results",
                    url="https://example.com/results.pdf",
                    publication_date="2026-03-23",
                    file_path=root / "results.pdf",
                    text_path=text_path,
                    stock_code="09606",
                    stock_name="DUALITYBIO-B",
                ),
            ),
        )

    def test_covers_multiple_distant_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            early_filler = "filler-early. " * 400
            mid_filler = "filler-mid. " * 600
            tail_filler = "filler-late. " * 400
            text = (
                early_filler
                + "DB-1303 HER2 ADC Phase 3 topline in 2026.\n"
                + mid_filler
                + "DB-1312 B7-H4 Phase 1 dose-escalation.\n"
                + tail_filler
            )
            artifacts = self._artifacts_with_text(root, text)
            pipeline = {
                "assets": [
                    {"name": "DB-1303"},
                    {"name": "DB-1312"},
                    {"name": "DB-9999"},
                ]
            }

            excerpt = _build_source_text_excerpt(
                auto_input_artifacts=artifacts,
                pipeline_snapshot=pipeline,
            )

            self.assertIsNotNone(excerpt)
            assert excerpt is not None
            self.assertEqual(
                excerpt["anchor_assets"], ["DB-1303", "DB-1312"]
            )
            self.assertEqual(excerpt["missing_assets"], ["DB-9999"])
            self.assertIn("DB-1303", excerpt["excerpt"])
            self.assertIn("DB-1312", excerpt["excerpt"])
            self.assertIn("[... source ~offset", excerpt["excerpt"])

    def test_falls_back_to_prefix_when_no_anchor_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifacts = self._artifacts_with_text(
                root, "some annual results text without any asset names" * 20
            )
            pipeline = {"assets": [{"name": "DB-1303"}]}

            excerpt = _build_source_text_excerpt(
                auto_input_artifacts=artifacts,
                pipeline_snapshot=pipeline,
            )

            assert excerpt is not None
            self.assertEqual(excerpt["anchor_assets"], [])
            self.assertEqual(excerpt["missing_assets"], ["DB-1303"])
            self.assertTrue(excerpt["excerpt"].startswith("some annual "))

    def test_excerpt_is_capped_at_max_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            blocks = []
            for idx in range(6):
                blocks.append("filler. " * 1000)
                blocks.append(f"DB-{idx:04d} asset details here.\n")
            text = "".join(blocks)
            artifacts = self._artifacts_with_text(root, text)
            pipeline = {
                "assets": [{"name": f"DB-{idx:04d}"} for idx in range(6)]
            }

            excerpt = _build_source_text_excerpt(
                auto_input_artifacts=artifacts,
                pipeline_snapshot=pipeline,
                max_chars=2000,
                per_anchor_window=800,
            )

            assert excerpt is not None
            self.assertLessEqual(excerpt["excerpt_chars"], 2400)
            self.assertTrue(excerpt["truncated"])

    def test_prefers_phase_rich_repeated_asset_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            text = (
                "HBM7020 collaboration with Otsuka for autoimmune diseases. "
                + "filler. " * 500
                + "HBM7020 obtained IND clearance to commence Phase I trial."
            )
            artifacts = self._artifacts_with_text(root, text)
            pipeline = {
                "assets": [
                    {
                        "name": "HBM7020",
                        "target": "BCMA/CD3",
                        "phase": "Phase I",
                    }
                ]
            }

            excerpt = _build_source_text_excerpt(
                auto_input_artifacts=artifacts,
                pipeline_snapshot=pipeline,
                max_chars=900,
                per_anchor_window=500,
            )

            assert excerpt is not None
            self.assertIn("Phase I trial", excerpt["excerpt"])
            self.assertEqual(excerpt["anchor_details"][0]["hit_count"], 2)
            self.assertGreater(excerpt["anchor_details"][0]["signal_score"], 0)

    def test_build_llm_agent_facts_threads_excerpt_through(self) -> None:
        class _StubResearch:
            def __init__(self) -> None:
                class _Memo:
                    findings: tuple = ()

                class _Ctx:
                    company = "Stub"
                    ticker = None
                    market = "HK"
                    as_of_date = None

                self.memo = _Memo()
                self.context = _Ctx()
                self.pipeline_assets = ()
                self.trials = ()
                self.asset_trial_matches = ()
                self.financial_snapshot = None
                self.valuation_snapshot = None
                self.valuation_metrics = None
                self.cash_runway_estimate = None
                self.input_validation: dict = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            artifacts = self._artifacts_with_text(
                root, "preamble. DB-1303 Phase 3 topline. tail text."
            )
            research = _StubResearch()

            facts = build_llm_agent_facts(
                research_result=research,
                auto_input_artifacts=artifacts,
            )

            excerpt = facts["source_text_excerpt"]
            self.assertIsNotNone(excerpt)
            assert excerpt is not None
            self.assertEqual(excerpt["anchor_assets"], [])
            self.assertIn("preamble", excerpt["excerpt"])


class LLMContextDateTest(unittest.TestCase):
    def test_run_date_from_run_id(self) -> None:
        self.assertEqual(
            _run_date_from_run_id("20260422T120057Z"),
            "2026-04-22",
        )
        self.assertIsNone(_run_date_from_run_id("not-a-run-id"))


if __name__ == "__main__":
    unittest.main()
