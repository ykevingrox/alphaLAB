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
    _run_llm_agent_pipeline,
    _run_date_from_run_id,
    _valuation_pod_payload_from_llm_facts,
    build_llm_agent_facts,
    company_report_summary,
    decision_log_history,
    decision_log_index,
    discover_company_inputs,
    resolve_company_identity,
    run_company_report,
    stage_c_review_index,
    stage_c_review_markdown,
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


def _minimal_research_stub():
    class _Memo:
        findings: tuple = ()
        evidence: tuple = ()

    class _Ctx:
        company = "Stub"
        ticker = "09606.HK"
        market = "HK"
        as_of_date = None

    class _Research:
        run_id = "20260428T000000Z"
        memo = _Memo()
        context = _Ctx()
        pipeline_assets = ()
        trials = ()
        asset_trial_matches = ()
        financial_snapshot = None
        valuation_snapshot = None
        valuation_metrics = None
        cash_runway_estimate = None
        competitor_assets = ()
        competitive_matches = ()
        target_price_analysis = None
        scorecard = None
        input_validation: dict = {}

    return _Research()


class CompanyReportTest(unittest.TestCase):
    def test_resolves_identity_from_ticker_only(self) -> None:
        identity = resolve_company_identity(
            ticker="09606.HK",
            registry_path=None,
        )
        self.assertEqual(identity.company, "映恩生物")
        self.assertEqual(identity.ticker, "09606.HK")
        self.assertEqual(identity.market, "HK")
        self.assertEqual(identity.search_term, "DualityBio")

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
        cde_text = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>CDE</title>
    <item>
      <title>DualityBio CXHL123456 临床试验申请受理 用于肺癌</title>
      <link>https://cde.example.cn/abc</link>
      <guid>cde-abc</guid>
      <pubDate>Thu, 23 Apr 2026 11:00:00 +0800</pubDate>
      <category>受理信息</category>
    </item>
  </channel>
</rss>
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            feed_path = root / "hkex_feed.xml"
            state_path = root / "hkex_seen.json"
            cde_feed_path = root / "cde_feed.xml"
            cde_state_path = root / "cde_seen.json"
            feed_path.write_text(rss_text, encoding="utf-8")
            cde_feed_path.write_text(cde_text, encoding="utf-8")
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
                cde_feed_file=cde_feed_path,
                cde_state_file=cde_state_path,
                cde_query="DualityBio",
            )
            self.assertIsNotNone(result.hkexnews_updates_path)
            assert result.hkexnews_updates_path is not None
            hkex_payload = json.loads(
                Path(result.hkexnews_updates_path).read_text(encoding="utf-8")
            )
            self.assertEqual(hkex_payload["new_count"], 1)
            self.assertEqual(hkex_payload["ticker_filter"], "09606.HK")
            self.assertTrue(hkex_payload["typed_new_items"])
            self.assertEqual(
                hkex_payload["typed_new_items"][0]["event_type"],
                "corporate",
            )
            summary = company_report_summary(result)
            self.assertEqual(
                summary["hkexnews_updates_path"],
                str(result.hkexnews_updates_path),
            )
            self.assertEqual(summary["hkexnews_updates"]["new_count"], 1)
            self.assertTrue(summary["cde_updates"])
            self.assertTrue(summary["cde_updates"]["normalized_new_records"])
            self.assertTrue(summary["hkexnews_event_impacts"])
            self.assertTrue(summary["hkexnews_dilution_hint"])
            self.assertTrue(summary["peer_valuation"])
            manifest = json.loads(
                Path(result.research_result.artifacts.manifest_json).read_text()
            )
            self.assertIn("hkexnews_updates", manifest["artifacts"])
            self.assertIn("hkexnews_event_impacts", manifest["artifacts"])
            self.assertIn("hkexnews_dilution_hint", manifest["artifacts"])
            self.assertIn("peer_valuation", manifest["artifacts"])
            self.assertIn("cde_updates", manifest["artifacts"])
            self.assertEqual(manifest["hkexnews_updates"]["new_count"], 1)
            self.assertTrue(manifest["hkexnews_updates"]["typed_new_items"])
            memo_text = Path(result.research_result.artifacts.memo_markdown).read_text(
                encoding="utf-8"
            )
            self.assertIn("## HKEXnews Updates", memo_text)
            self.assertIn("## China CDE Updates", memo_text)
            self.assertIn("### Normalized Trial Registry Draft", memo_text)
            self.assertIn("[corporate] 09606 - Voluntary Announcement", memo_text)
            catalyst_csv = Path(
                result.research_result.artifacts.catalyst_calendar_csv
            ).read_text(encoding="utf-8")
            self.assertIn("HKEXnews: 09606 - Voluntary Announcement", catalyst_csv)

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
            self.assertIn("## LLM Agent 附录", memo_text)
            self.assertIn("运行状态：2/2 步成功", memo_text)
            self.assertIn("LLM 总 token：30", memo_text)
            self.assertIn("Pipeline evidence is thin enough", memo_text)
            self.assertIn("No asset-level clinical anchor was found", memo_text)
            findings_path = (
                Path(tmpdir) / "memos" / "20260421T000000Z_llm_findings.json"
            )
            self.assertTrue(findings_path.exists())

    def test_saved_report_writes_decision_log_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            client = FakeClinicalTrialsClient()
            llm = FakeLLMClient(model="fake-qwen")
            llm.queue(
                json.dumps(
                    {
                        "bull_case": [
                            {
                                "claim": "Market value may reflect BD validation.",
                                "evidence_key": "strategic_economics_payload",
                                "confidence": 0.5,
                            }
                        ],
                        "bear_case": [
                            {
                                "claim": "Evidence gaps still limit conviction.",
                                "evidence_key": "data_collector_payload",
                                "confidence": 0.6,
                            }
                        ],
                        "debate_resolution": "Keep deterministic view unchanged.",
                        "fundamental_view": "watchlist",
                        "timing_view": "unknown",
                        "decision_log": {
                            "current_decision": "watchlist",
                            "key_assumptions": ["BD validation remains relevant"],
                            "reasons_to_revisit": ["New clinical update"],
                            "invalidation_triggers": ["Evidence weakens"],
                            "evidence_gaps": ["Need more source detail"],
                            "next_review_triggers": ["Next disclosure"],
                        },
                        "confidence": 0.52,
                        "needs_human_review": True,
                    }
                )
            )

            result = run_company_report(
                company="No Data Bio",
                input_dir=Path(tmpdir) / "input",
                output_dir=tmpdir,
                limit=1,
                client=client,
                now=datetime(2026, 4, 21, tzinfo=UTC),
                llm_agents=("decision-debate",),
                llm_client=llm,
            )

            self.assertIsNotNone(result.decision_log_path)
            assert result.decision_log_path is not None
            payload = json.loads(Path(result.decision_log_path).read_text())
            self.assertEqual(payload["identity"]["ticker"], None)
            self.assertEqual(payload["run_id"], "20260421T000000Z")
            self.assertEqual(payload["summary"]["fundamental_view"], "watchlist")
            summary = company_report_summary(result)
            self.assertEqual(
                summary["decision_log_summary"]["current_decision"],
                "watchlist",
            )
            manifest_path = result.research_result.artifacts.manifest_json
            assert manifest_path is not None
            manifest = json.loads(Path(manifest_path).read_text())
            self.assertIn("decision_log", manifest["artifacts"])

    def test_decision_log_history_loads_same_company_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "processed" / "company_report" / "dualitybio_09606_hk"
            path.mkdir(parents=True)
            artifact = path / "20260421T000000Z_decision_log.json"
            artifact.write_text(
                json.dumps(
                    {
                        "run_id": "20260421T000000Z",
                        "identity": {
                            "company": "映恩生物",
                            "ticker": "09606.HK",
                            "market": "HK",
                        },
                        "summary": {
                            "fundamental_view": "watchlist",
                            "timing_view": "neutral",
                            "current_decision": "watchlist",
                            "confidence": 0.5,
                        },
                        "payload": {
                            "decision_log": {
                                "current_decision": "watchlist",
                                "key_assumptions": ["BD remains credible"],
                                "reasons_to_revisit": ["new data"],
                                "invalidation_triggers": ["weak data"],
                                "evidence_gaps": ["need partner economics"],
                                "next_review_triggers": ["next disclosure"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            newer = path / "20260428T000000Z_decision_log.json"
            newer.write_text(
                json.dumps(
                    {
                        "run_id": "20260428T000000Z",
                        "identity": {
                            "company": "映恩生物",
                            "ticker": "09606.HK",
                            "market": "HK",
                        },
                        "summary": {
                            "fundamental_view": "watchlist",
                            "timing_view": "fragile",
                            "current_decision": "watchlist",
                            "confidence": 0.55,
                        },
                        "payload": {
                            "decision_log": {
                                "current_decision": "watchlist",
                                "key_assumptions": ["BD remains credible"],
                                "reasons_to_revisit": ["new data"],
                                "invalidation_triggers": ["weak data"],
                                "evidence_gaps": [
                                    "need partner economics",
                                    "need catalyst timing",
                                ],
                                "next_review_triggers": ["next disclosure"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            history = decision_log_history(
                output_dir=root,
                ticker="09606.HK",
                registry_path=None,
            )

            self.assertTrue(history["available"])
            self.assertEqual(history["count"], 2)
            self.assertEqual(history["entries"][0]["run_id"], "20260428T000000Z")
            self.assertEqual(
                history["entries"][1]["decision_log"]["key_assumptions"],
                ["BD remains credible"],
            )
            self.assertTrue(history["change_summary"]["timing_view_changed"])
            self.assertEqual(
                history["change_summary"]["new_evidence_gaps"],
                ["need catalyst timing"],
            )

    def test_decision_log_index_loads_all_company_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first_dir = root / "processed" / "company_report" / "dualitybio"
            second_dir = root / "processed" / "company_report" / "leads"
            first_dir.mkdir(parents=True)
            second_dir.mkdir(parents=True)
            for target, run_id, ticker in (
                (first_dir, "20260421T000000Z", "09606.HK"),
                (second_dir, "20260428T000000Z", "09887.HK"),
            ):
                (target / f"{run_id}_decision_log.json").write_text(
                    json.dumps(
                        {
                            "run_id": run_id,
                            "identity": {
                                "company": ticker,
                                "ticker": ticker,
                                "market": "HK",
                            },
                            "summary": {
                                "fundamental_view": "watchlist",
                                "timing_view": "neutral",
                                "current_decision": "watchlist",
                                "confidence": 0.5,
                            },
                            "payload": {"decision_log": {}},
                        }
                    ),
                    encoding="utf-8",
                )

            index = decision_log_index(output_dir=root, limit=10)

            self.assertTrue(index["available"])
            self.assertEqual(index["count"], 2)
            self.assertEqual(index["entries"][0]["run_id"], "20260428T000000Z")
            self.assertEqual(index["entries"][0]["identity"]["ticker"], "09887.HK")

    def test_stage_c_review_index_groups_support_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / "processed" / "single_company" / "09606-hk"
            run_dir.mkdir(parents=True)
            (run_dir / "20260428T000000Z_report_quality.json").write_text(
                json.dumps(
                    {
                        "summary": "Needs review.",
                        "publish_gate": "review_required",
                        "critical_issues": [
                            "report_quality_unavailable: schema error"
                        ],
                        "recommended_fixes": ["rerun quality"],
                        "language_quality_findings": [],
                        "valuation_coherence_findings": [],
                        "confidence": 0.2,
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "20260428T000000Z_valuation_pod.json").write_text(
                json.dumps(
                    {
                        "available": True,
                        "summary": {
                            "component_count": 4,
                            "has_committee": True,
                            "committee_publishable": False,
                        },
                        "payload": {
                            "commercial": {
                                "method": "rNPV",
                                "summary": (
                                    "当前股价远高于保守rNPV，存在高估和下行空间。"
                                ),
                                "role_boundary_flags": [
                                    "commercial_rnpv_fallback_blocked"
                                ],
                                "valuation_range": {
                                    "bear": 1,
                                    "base": 2,
                                    "bull": 3,
                                },
                            },
                            "rnpv": {
                                "method": "rNPV",
                                "valuation_range": {
                                    "bear": 1,
                                    "base": 2,
                                    "bull": 3,
                                },
                            },
                            "committee": {"method": "sotp_committee"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            memos = root / "memos"
            memos.mkdir()
            (memos / "20260428T000000Z_llm_findings.json").write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "agent_name": "valuation_committee_llm_agent",
                                "summary": "committee summary",
                                "risks": [],
                                "confidence": 0.5,
                                "needs_human_review": True,
                            },
                            {
                                "agent_name": "report_quality_llm_agent",
                                "summary": "quality summary",
                                "risks": [],
                                "confidence": 0.5,
                                "needs_human_review": True,
                            },
                        ],
                        "steps": [],
                        "fallback_modules": [],
                        "warnings": [],
                    }
                ),
                encoding="utf-8",
            )

            review = stage_c_review_index(
                output_dir=root,
                query="09606.HK",
                limit=5,
            )

            self.assertTrue(review["available"])
            self.assertEqual(review["count"], 1)
            entry = review["entries"][0]
            self.assertEqual(entry["identity"]["ticker"], "09606.HK")
            self.assertIn("report_quality_unavailable", entry["review_flags"])
            self.assertIn(
                "valuation_committee_not_publishable",
                entry["review_flags"],
            )
            self.assertIn(
                "valuation_commercial_method_drift",
                entry["review_flags"],
            )
            self.assertIn(
                "valuation_overvaluation_language_without_market_bridge",
                entry["review_flags"],
            )
            self.assertIn(
                (
                    "valuation_role_boundary_commercial_"
                    "commercial_rnpv_fallback_blocked"
                ),
                entry["review_flags"],
            )
            self.assertEqual(entry["llm_findings"]["agent_count"], 2)
            self.assertIn(
                "market_expectations_llm_agent",
                entry["llm_findings"]["missing_expected_agents"],
            )
            self.assertIn(
                "missing_llm_finding_market_expectations_llm_agent",
                entry["review_flags"],
            )
            self.assertIn("missing_decision_log_artifact", entry["review_flags"])
            self.assertEqual(entry["review_severity"], "critical")
            self.assertTrue(
                any("valuation pod roles" in action for action in entry["next_actions"])
            )
            self.assertEqual(
                review["summary"]["publish_gate_counts"]["review_required"],
                1,
            )
            self.assertEqual(review["summary"]["severity_counts"]["critical"], 1)

            filtered = stage_c_review_index(
                output_dir=root,
                flags=("valuation_commercial_method_drift",),
                latest_per_identity=True,
                min_severity="critical",
            )
            self.assertEqual(filtered["count"], 1)
            markdown = stage_c_review_markdown(filtered)
            self.assertIn("# Stage C Artifact Review", markdown)
            self.assertIn("Checklist:", markdown)
            self.assertIn("valuation pod roles", markdown)

    def test_stage_c_review_index_reads_decision_log_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run_dir = root / "processed" / "company_report" / "duality"
            run_dir.mkdir(parents=True)
            (run_dir / "20260428T000000Z_decision_log.json").write_text(
                json.dumps(
                    {
                        "run_id": "20260428T000000Z",
                        "identity": {
                            "company": "映恩生物",
                            "ticker": "09606.HK",
                            "market": "HK",
                        },
                        "summary": {
                            "fundamental_view": "watchlist",
                            "timing_view": "neutral",
                            "current_decision": "watchlist",
                        },
                        "payload": {
                            "decision_log": {
                                "current_decision": "watchlist",
                                "next_review_triggers": ["next disclosure"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            review = stage_c_review_index(output_dir=root, query="映恩")

            self.assertTrue(review["available"])
            self.assertEqual(review["entries"][0]["identity"]["ticker"], "09606.HK")
            self.assertNotIn(
                "decision_log_missing_next_review_trigger",
                review["entries"][0]["review_flags"],
            )

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

            self.assertEqual(result.identity.search_term, "DualityBio")
            self.assertIn("DUALITYBIO-B", result.identity.aliases)
            self.assertIn("DUALITYBIO", result.identity.aliases)
            self.assertEqual(client.search_terms[0], "DualityBio")
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

    def test_build_llm_agent_facts_uses_valuation_cash_fields(self) -> None:
        class _StubResearch:
            def __init__(self) -> None:
                class _Memo:
                    findings: tuple = ()

                class _Ctx:
                    company = "Stub"
                    ticker = "00000.HK"
                    market = "HK"
                    as_of_date = None

                class _Valuation:
                    currency = "HKD"
                    market_cap = 1000.0
                    share_price = 10.0
                    shares_outstanding = 100.0
                    cash_and_equivalents = 120.0
                    total_debt = 20.0
                    revenue_ttm = None

                self.memo = _Memo()
                self.context = _Ctx()
                self.pipeline_assets = ()
                self.trials = ()
                self.asset_trial_matches = ()
                self.financial_snapshot = None
                self.valuation_snapshot = _Valuation()
                self.valuation_metrics = None
                self.cash_runway_estimate = None
                self.input_validation: dict = {}

        facts = build_llm_agent_facts(research_result=_StubResearch())

        market = facts["financials_snapshot"]["market_snapshot"]
        self.assertEqual(market["cash"], 120.0)
        self.assertEqual(market["debt"], 20.0)

    def test_build_llm_agent_facts_threads_technical_features(self) -> None:
        research = _minimal_research_stub()
        technical = {
            "symbol": "9606.HK",
            "technical_state": "constructive",
            "provider": "unit-test",
            "returns": {"1m_pct": 8.0, "3m_pct": 12.0},
            "relative_strength": {
                "state": "outperforming",
                "3m_spread_pct": 6.0,
            },
            "volume_trend": {"state": "rising"},
        }

        facts = build_llm_agent_facts(
            research_result=research,
            technical_features=technical,
        )

        self.assertEqual(facts["technical_feature_payload"], technical)
        self.assertEqual(
            facts["market_sentiment_payload"]["fund_flow_proxy_state"],
            "accumulation_proxy",
        )

    def test_build_llm_agent_facts_threads_prior_decision_logs(self) -> None:
        research = _minimal_research_stub()
        prior = {"count": 1, "entries": [{"run_id": "20260420T000000Z"}]}

        facts = build_llm_agent_facts(
            research_result=research,
            prior_decision_logs=prior,
        )

        self.assertEqual(facts["prior_decision_logs_payload"], prior)

    def test_build_llm_agent_facts_threads_input_validation_payload(self) -> None:
        research = _minimal_research_stub()
        research.input_validation = {
            "financials": {"warnings": ["cash source stale"]},
        }

        facts = build_llm_agent_facts(research_result=research)

        self.assertEqual(
            facts["input_validation_payload"]["financials"]["warnings"],
            ["cash source stale"],
        )

    def test_build_llm_agent_facts_threads_memo_scaffold_payload(self) -> None:
        research = _minimal_research_stub()

        facts = build_llm_agent_facts(research_result=research)

        scaffold = facts["memo_scaffold_payload"]
        self.assertEqual(scaffold["ticker"], "09606.HK")
        self.assertIn("deterministic_summary", scaffold)
        self.assertEqual(scaffold["catalyst_count"], 0)

    def test_build_llm_agent_facts_threads_memo_review_payload(self) -> None:
        research = _minimal_research_stub()

        facts = build_llm_agent_facts(research_result=research)

        review = facts["memo_review_payload"]
        self.assertTrue(review["available"])
        self.assertIn("markdown_excerpt", review)
        self.assertIn("## 执行结论", review["markdown_excerpt"])
        self.assertEqual(review["render_mode"], "fallback_fields")

    def test_build_llm_agent_facts_threads_catalyst_calendar(self) -> None:
        class _Evidence:
            claim = "company disclosed readout window"
            source = "annual_results"
            source_date = "2026-03-25"
            confidence = 0.7
            is_inferred = False

        class _Catalyst:
            title = "DB-1303 Phase 3 readout"
            category = "clinical"
            expected_date = None
            expected_window = "2H 2026"
            related_asset = "DB-1303"
            confidence = 0.7
            evidence = (_Evidence(),)

        class _Memo:
            findings: tuple = ()
            evidence: tuple = ()
            catalysts = (_Catalyst(),)

        research = _minimal_research_stub()
        research.memo = _Memo()

        facts = build_llm_agent_facts(research_result=research)

        payload = facts["catalyst_calendar_payload"]
        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            payload["catalysts"][0]["title"],
            "DB-1303 Phase 3 readout",
        )
        self.assertEqual(
            payload["catalysts"][0]["evidence"][0]["source"],
            "annual_results",
        )

    def test_llm_pipeline_fetches_technical_features_for_timing_agent(self) -> None:
        technical = {
            "symbol": "9606.HK",
            "technical_state": "constructive",
            "provider": "unit-test",
        }
        calls: list[str | None] = []

        def provider(identity):
            calls.append(identity.ticker)
            return technical

        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    "timing_view": "neutral",
                    "horizon": "3-6 months",
                    "macro_regime": "insufficient_data",
                    "technical_state": "constructive",
                    "sentiment_state": "unknown",
                    "key_triggers": ["monitor technical feature stability"],
                    "invalidation_signals": ["technical payload disappears"],
                    "confidence": 0.4,
                    "needs_human_review": True,
                }
            )
        )

        result, _trace = _run_llm_agent_pipeline(
            research_result=_minimal_research_stub(),
            identity=resolve_company_identity(
                ticker="09606.HK", registry_path=None
            ),
            llm_agents=("market-regime-timing",),
            llm_client=client,
            output_dir="data",
            save=False,
            llm_trace_path=None,
            technical_features_provider=provider,
        )

        self.assertEqual(calls, ["09606.HK"])
        self.assertEqual(result.facts["technical_feature_payload"], technical)
        self.assertIn("market_regime_timing_payload", result.facts)

    def test_llm_pipeline_fetches_technical_features_for_expectations_agent(
        self,
    ) -> None:
        technical = {
            "symbol": "9606.HK",
            "technical_state": "constructive",
            "provider": "unit-test",
        }
        calls: list[str | None] = []

        def provider(identity):
            calls.append(identity.ticker)
            return technical

        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    "market_implied_assumptions": [
                        "Market value requires strategic optionality."
                    ],
                    "valuation_band_context": "unknown",
                    "rnpv_gap_explanation": (
                        "Conservative rNPV below market value is not enough "
                        "to call overvaluation."
                    ),
                    "expectation_risk_flags": ["BD evidence is incomplete."],
                    "evidence_gaps": ["Need disclosed partner economics."],
                    "confidence": 0.35,
                    "needs_human_review": True,
                }
            )
        )

        result, _trace = _run_llm_agent_pipeline(
            research_result=_minimal_research_stub(),
            identity=resolve_company_identity(
                ticker="09606.HK", registry_path=None
            ),
            llm_agents=("market-expectations",),
            llm_client=client,
            output_dir="data",
            save=False,
            llm_trace_path=None,
            technical_features_provider=provider,
        )

        self.assertEqual(calls, ["09606.HK"])
        self.assertEqual(result.facts["technical_feature_payload"], technical)
        self.assertIn("market_expectations_payload", result.facts)

    def test_llm_pipeline_runs_decision_debate_agent(self) -> None:
        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    "bull_case": [
                        {
                            "claim": "Market value may reflect BD validation.",
                            "evidence_key": "strategic_economics_payload",
                            "confidence": 0.5,
                        }
                    ],
                    "bear_case": [
                        {
                            "claim": "Evidence gaps still limit conviction.",
                            "evidence_key": "data_collector_payload",
                            "confidence": 0.6,
                        }
                    ],
                    "debate_resolution": "Keep the existing watchlist stance.",
                    "fundamental_view": "watchlist",
                    "timing_view": "unknown",
                    "decision_log": {
                        "current_decision": "watchlist",
                        "key_assumptions": ["BD validation remains relevant"],
                        "reasons_to_revisit": ["New clinical update"],
                        "invalidation_triggers": ["Evidence weakens"],
                        "evidence_gaps": ["Need more source detail"],
                        "next_review_triggers": ["Next disclosure"],
                    },
                    "confidence": 0.52,
                    "needs_human_review": True,
                }
            )
        )

        result, _trace = _run_llm_agent_pipeline(
            research_result=_minimal_research_stub(),
            identity=resolve_company_identity(
                ticker="09606.HK", registry_path=None
            ),
            llm_agents=("decision-debate",),
            llm_client=client,
            output_dir="data",
            save=False,
            llm_trace_path=None,
        )

        self.assertIn("decision_debate_payload", result.facts)
        self.assertIn("decision_debate_llm_finding", result.facts)

    def test_llm_pipeline_skips_technical_provider_without_market_agent(
        self,
    ) -> None:
        def provider(_identity):
            raise AssertionError("technical provider should not be called")

        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    "macro_regime": "insufficient_data",
                    "summary": "Macro context unavailable.",
                    "sector_drivers": [],
                    "sector_headwinds": ["missing live macro data"],
                    "confidence": 0.2,
                }
            )
        )

        result, _trace = _run_llm_agent_pipeline(
            research_result=_minimal_research_stub(),
            identity=resolve_company_identity(
                ticker="09606.HK", registry_path=None
            ),
            llm_agents=("macro-context",),
            llm_client=client,
            output_dir="data",
            save=False,
            llm_trace_path=None,
            technical_features_provider=provider,
        )

        self.assertIsNone(result.facts["technical_feature_payload"])

    def test_valuation_pod_summary_flags_duplicate_ranges(self) -> None:
        payload = _valuation_pod_payload_from_llm_facts(
            {
                "valuation_commercial_payload": {
                    "method": "multiple",
                    "valuation_range": {"bear": 1, "base": 2, "bull": 3},
                },
                "valuation_rnpv_payload": {
                    "method": "rNPV",
                    "valuation_range": {"bear": 1, "base": 2, "bull": 3},
                },
                "valuation_balance_sheet_payload": {
                    "method": "balance_sheet_adjustment",
                    "valuation_range": {"bear": 0, "base": 1, "bull": 1},
                },
                "valuation_committee_payload": {
                    "method": "sotp_committee",
                    "currency": "HKD",
                    "needs_human_review": True,
                    "conservative_rnpv_floor": {"base": 3},
                    "market_implied_value": {"market_cap": 10},
                    "scenario_repricing_range": {"base": 4},
                },
            }
        )

        summary = payload["summary"]
        self.assertEqual(summary["duplicate_component_range_count"], 1)
        self.assertEqual(summary["component_methods"]["commercial"], "multiple")
        self.assertEqual(summary["conservative_rnpv_floor"]["base"], 3)


class LLMContextDateTest(unittest.TestCase):
    def test_run_date_from_run_id(self) -> None:
        self.assertEqual(
            _run_date_from_run_id("20260422T120057Z"),
            "2026-04-22",
        )
        self.assertIsNone(_run_date_from_run_id("not-a-run-id"))


if __name__ == "__main__":
    unittest.main()
