from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from biotech_alpha.models import AgentFinding, ClinicalDataPoint, Evidence, PipelineAsset
from biotech_alpha.research import memo_to_markdown, result_summary, run_single_company_research


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
            response = self.responses_by_term[term]
            if isinstance(response, Exception):
                raise response
            return response
        return self.response or {"studies": []}


class SingleCompanyResearchTest(unittest.TestCase):
    def test_key_risks_tags_medium_high_llm_triage_sources(self) -> None:
        memo_text = memo_to_markdown(
            run_single_company_research(
                company="Example Biotech",
                save=False,
                client=FakeClinicalTrialsClient({"studies": []}),
                now=datetime(2026, 4, 20, tzinfo=UTC),
            ).memo,
            llm_findings=(
                AgentFinding(
                    agent_name="pipeline_triage_agent",
                    summary="triage",
                    risks=("[medium] phase label mismatch",),
                    confidence=0.6,
                    needs_human_review=True,
                ),
            ),
        )
        self.assertIn(
            "[medium] phase label mismatch (source: llm[pipeline_triage_agent])",
            memo_text,
        )

    def test_memo_includes_report_quality_section_when_payload_present(self) -> None:
        result = run_single_company_research(
            company="Example Biotech",
            save=False,
            client=FakeClinicalTrialsClient({"studies": []}),
            now=datetime(2026, 4, 20, tzinfo=UTC),
        )
        memo_text = memo_to_markdown(
            result.memo,
            report_quality_payload={
                "publish_gate": "review_required",
                "summary": "需要人工复核后发布。",
                "critical_issues": ["估值口径与风险段落有潜在冲突。"],
                "recommended_fixes": ["补充估值口径说明并统一币种。"],
            },
        )
        self.assertIn("## 报告质量门", memo_text)
        self.assertIn("publish_gate: `review_required`", memo_text)
        self.assertIn("估值口径与风险段落有潜在冲突", memo_text)

    def test_memo_includes_report_synthesizer_text_when_payload_present(self) -> None:
        result = run_single_company_research(
            company="Example Biotech",
            save=False,
            client=FakeClinicalTrialsClient({"studies": []}),
            now=datetime(2026, 4, 20, tzinfo=UTC),
        )
        memo_text = memo_to_markdown(
            result.memo,
            report_synthesizer_payload={
                "executive_verdict_paragraph": "这是综合编辑后的执行结论。",
                "section_transitions": {
                    "investment_thesis": "投资主线过渡句。",
                    "risks": "风险过渡句。",
                },
            },
        )
        self.assertIn("这是综合编辑后的执行结论。", memo_text)
        self.assertIn("投资主线过渡句。", memo_text)
        self.assertIn("风险过渡句。", memo_text)

    def test_core_asset_deep_dive_prefers_phase2_plus_assets(self) -> None:
        client = FakeClinicalTrialsClient({"studies": []})
        assets = (
            PipelineAsset(name="A-101", phase="Phase 1"),
            PipelineAsset(name="B-202", phase="Phase 2"),
            PipelineAsset(name="C-303", phase="Phase 3"),
            PipelineAsset(name="D-404", phase="BLA under review"),
        )
        result = run_single_company_research(
            company="Example Biotech",
            pipeline_assets=assets,
            client=client,
            include_asset_queries=False,
            save=False,
            now=datetime(2026, 4, 20, tzinfo=UTC),
        )

        self.assertEqual(
            tuple(asset.name for asset in result.memo.key_assets),
            ("D-404", "C-303", "B-202"),
        )

    def test_clinical_trial_search_failure_degrades_to_warning(self) -> None:
        asset = PipelineAsset(name="DB-1303", target="HER2")
        client = FakeClinicalTrialsClient(
            responses_by_term={
                "DualityBio": {"studies": []},
                "DB-1303": RuntimeError("remote disconnected"),
            }
        )

        result = run_single_company_research(
            company="DualityBio",
            pipeline_assets=(asset,),
            client=client,
            include_asset_queries=True,
            limit=1,
            save=False,
            now=datetime(2026, 4, 20, tzinfo=UTC),
        )

        report = result.input_validation["clinical_trials"]
        self.assertEqual(report["failed_search_count"], 1)
        self.assertIn("DB-1303", report["warnings"][0])
        self.assertEqual(result.trials, ())

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
            regulatory_pathway="BLA submission planned",
            next_binary_event="BLA submission in Q3 2026",
            next_milestone="2026 data readout",
            clinical_data=(
                ClinicalDataPoint(
                    metric="ORR",
                    value="42",
                    unit="%",
                    sample_size=58,
                    context="relapsed disease",
                ),
                ClinicalDataPoint(
                    metric="mPFS",
                    value="8.6",
                    unit="months",
                    sample_size=58,
                    context="interim cutoff",
                ),
            ),
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
            target_price_path = Path(tmpdir) / "target_price.json"
            target_price_path.write_text(
                json.dumps(
                    {
                        "as_of_date": "2026-04-20",
                        "currency": "HKD",
                        "share_price": 12.4,
                        "shares_outstanding": 1000000000,
                        "cash_and_equivalents": 1200000000,
                        "total_debt": 300000000,
                        "expected_dilution_pct": 0.0,
                        "assets": [
                            {
                                "name": "Known Drug",
                                "indication": "Cancer",
                                "phase": "Phase 2",
                                "peak_sales": 3000000000,
                                "probability_of_success": 0.35,
                                "economics_share": 1.0,
                                "operating_margin": 0.35,
                                "launch_year": 2030,
                                "discount_rate": 0.12,
                                "source": "model.xlsx",
                                "source_date": "2026-04-20",
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
                target_price_assumptions_path=target_price_path,
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
            self.assertIsNotNone(result.target_price_analysis)
            self.assertGreater(
                result.target_price_analysis.probability_weighted_target_price,
                0,
            )
            self.assertGreater(result.scorecard.total_score, 55)
            self.assertEqual(result.scorecard.bucket, "watchlist")
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
            self.assertGreater(summary["probability_weighted_target_price"], 0)
            self.assertIsNotNone(summary["target_price_summary"])
            self.assertEqual(summary["watchlist_score"], result.scorecard.total_score)
            self.assertEqual(summary["watchlist_bucket"], "watchlist")
            self.assertTrue(summary["scorecard_dimensions"])
            self.assertIn("contribution", summary["scorecard_dimensions"][0])
            self.assertIsNotNone(summary["research_action_plan"])
            self.assertEqual(
                summary["research_action_plan"]["guidance_type"],
                "research_only",
            )
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
            self.assertIsNotNone(artifacts.scorecard)
            self.assertIsNotNone(artifacts.event_impact)
            self.assertIsNotNone(artifacts.target_price_scenarios)
            self.assertIsNotNone(artifacts.target_price_summary_csv)
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
                artifacts.scorecard,
                artifacts.event_impact,
                artifacts.target_price_scenarios,
                artifacts.target_price_summary_csv,
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
            self.assertIn("## 关键风险与证伪条件", memo_markdown)
            self.assertIn("## 竞争格局", memo_markdown)
            self.assertIn("## 投资主线", memo_markdown)
            self.assertIn("## 估值细化", memo_markdown)
            self.assertIn("## 催化剂路线图", memo_markdown)
            self.assertIn("## 评分卡透明度", memo_markdown)
            self.assertIn("### 路径：提升至核心候选", memo_markdown)
            self.assertIn("## 研究行动计划（非交易指令）", memo_markdown)
            self.assertIn("临床数据: ORR 42% (n=58); relapsed disease", memo_markdown)
            self.assertIn("监管路径 BLA submission planned", memo_markdown)
            self.assertIn("二元事件 BLA submission in Q3 2026", memo_markdown)
            self.assertIn(
                "Example Drug 与竞品",
                memo_markdown,
            )
            self.assertIn("现金流可持续期：贡献度 6.4", memo_markdown)
            self.assertIn("入场区间 1.05-1.27 HKD", memo_markdown)
            self.assertIn(
                "仅供研究支持，不构成交易指令",
                memo_markdown.lower(),
            )
            self.assertIn("输入校验产生 1 条告警", memo_markdown)
            self.assertIn("Example Drug matched NCT00000001", memo_markdown)
            self.assertIn("Rival Drug 在 靶点+适应症维度匹配", memo_markdown)
            self.assertIn("企业价值约为 2300 HKD", memo_markdown)
            self.assertIn("现金流可持续期低于 24 个月", memo_markdown)

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
            self.assertEqual(manifest["market"], "HK")
            self.assertEqual(manifest["counts"]["trials"], 1)
            self.assertEqual(manifest["counts"]["pipeline_assets"], 1)
            self.assertEqual(manifest["counts"]["competitor_assets"], 1)
            self.assertEqual(manifest["counts"]["competitive_matches"], 1)
            self.assertEqual(manifest["counts"]["cash_runway"], 1)
            self.assertEqual(manifest["counts"]["valuation"], 1)
            self.assertEqual(manifest["counts"]["target_price"], 1)
            self.assertEqual(manifest["counts"]["scorecard"], 1)
            self.assertTrue(manifest["scorecard_dimensions"])
            self.assertIn("weight", manifest["scorecard_dimensions"][0])
            self.assertEqual(
                manifest["research_action_plan"]["guidance_type"],
                "research_only",
            )
            self.assertEqual(
                manifest["quality_gate"]["level"],
                "research_ready_with_review",
            )
            self.assertIn("financials", manifest["input_validation"])
            self.assertIn("competitors", manifest["input_validation"])
            self.assertIn("valuation", manifest["input_validation"])
            self.assertIn("target_price", manifest["input_validation"])
            self.assertIn(
                "replace placeholder source",
                manifest["input_validation"]["financials"]["warnings"],
            )
            self.assertIn("memo_markdown", manifest["artifacts"])
            cash_runway = json.loads(Path(artifacts.cash_runway).read_text())
            self.assertEqual(cash_runway["estimate"]["runway_months"], 18)
            valuation = json.loads(Path(artifacts.valuation).read_text())
            self.assertEqual(valuation["metrics"]["enterprise_value"], 2300)
            event_impact = json.loads(Path(artifacts.event_impact).read_text())
            self.assertGreater(event_impact["event_value_delta"], 0)
            target_price_csv = Path(artifacts.target_price_summary_csv).read_text()
            self.assertIn("base,HKD", target_price_csv)
            scorecard = json.loads(Path(artifacts.scorecard).read_text())
            self.assertEqual(scorecard["bucket"], "watchlist")
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
            "未提供结构化管线资产输入",
            result.memo.findings[1].risks,
        )
        summary = result_summary(result)
        self.assertIsNone(summary["research_action_plan"])
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
