"""Regression tests for Stage A valuation pod + report quality agents."""

from __future__ import annotations

import unittest

from biotech_alpha.agent_runtime import FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    ReportQualityLLMAgent,
    ValuationBalanceSheetLLMAgent,
    ValuationCommercialLLMAgent,
    ValuationCommitteeLLMAgent,
    _normalize_valuation_payload,
    _postprocess_report_quality_payload,
)
from biotech_alpha.llm import FakeLLMClient
from biotech_alpha.llm.client import LLMError


class ValuationCommitteeLLMAgentTest(unittest.TestCase):
    def test_committee_enriches_sotp_bridge_from_sub_agents(self) -> None:
        client = FakeLLMClient()
        client.queue(
            """{
              "summary": "committee initial output",
              "method": "sotp_committee",
              "scope": "full_company",
              "assumptions": ["base assumptions"],
              "valuation_range": {"bear": 1, "base": 1, "bull": 1},
              "sensitivity": [],
              "risks": [],
              "confidence": 0.8,
              "needs_human_review": true,
              "currency": "HKD",
              "sotp_bridge": [],
              "method_weights": [],
              "conflict_resolution": []
            }"""
        )
        agent = ValuationCommitteeLLMAgent(
            llm_client=client,
            depends_on=("publish_research_facts",),
        )
        context = AgentContext(company="DualityBio", ticker="09606.HK")
        store = FactStore(
            {
                "valuation_snapshot": {"shares_outstanding": 100.0},
                "valuation_commercial_payload": {
                    "method": "multiple",
                    "currency": "HKD",
                    "valuation_range": {"bear": 80, "base": 100, "bull": 120},
                },
                "valuation_rnpv_payload": {
                    "method": "rNPV",
                    "currency": "HKD",
                    "valuation_range": {"bear": 60, "base": 90, "bull": 150},
                },
                "valuation_balance_sheet_payload": {
                    "method": "balance_sheet_adjustment",
                    "currency": "HKD",
                    "valuation_range": {"bear": 10, "base": 20, "bull": 30},
                },
            }
        )

        step = agent.run(context, store)

        self.assertTrue(step.ok)
        payload = step.outputs["valuation_committee_payload"]
        self.assertEqual(payload["method"], "sotp_committee")
        self.assertEqual(payload["valuation_range"]["base"], 210.0)
        self.assertEqual(len(payload["sotp_bridge"]), 3)
        self.assertEqual(payload["final_per_share_range"]["base"], 2.1)

    def test_committee_excludes_duplicate_component_ranges(self) -> None:
        client = FakeLLMClient()
        client.queue(
            """{
              "summary": "committee output",
              "method": "sotp_committee",
              "scope": "full_company",
              "assumptions": [],
              "valuation_range": {"bear": 0, "base": 0, "bull": 0},
              "sensitivity": [],
              "risks": [],
              "confidence": 0.8,
              "needs_human_review": true,
              "currency": "HKD",
              "sotp_bridge": [],
              "method_weights": [],
              "conflict_resolution": []
            }"""
        )
        agent = ValuationCommitteeLLMAgent(llm_client=client)
        context = AgentContext(company="DualityBio", ticker="09606.HK")
        store = FactStore(
            {
                "valuation_snapshot": {"shares_outstanding": 10.0},
                "valuation_commercial_payload": {
                    "method": "multiple",
                    "currency": "HKD",
                    "valuation_range": {"bear": 10, "base": 20, "bull": 30},
                },
                "valuation_rnpv_payload": {
                    "method": "rNPV",
                    "currency": "HKD",
                    "valuation_range": {"bear": 10, "base": 20, "bull": 30},
                },
                "valuation_balance_sheet_payload": {
                    "method": "balance_sheet_adjustment",
                    "currency": "HKD",
                    "valuation_range": {"bear": 1, "base": 2, "bull": 3},
                },
            }
        )

        step = agent.run(context, store)

        self.assertTrue(step.ok)
        payload = step.outputs["valuation_committee_payload"]
        self.assertEqual(payload["valuation_range"]["base"], 22.0)
        duplicates = [
            item
            for item in payload["conflict_resolution"]
            if item.get("conflict") == "duplicate_component_valuation_range"
        ]
        self.assertTrue(duplicates)
        self.assertIn("conservative_rnpv_floor", payload)
        self.assertIn("market_implied_value", payload)


class ValuationPodRoleBoundaryTest(unittest.TestCase):
    def test_commercial_agent_does_not_fall_back_to_rnpv_without_revenue(
        self,
    ) -> None:
        client = FakeLLMClient()
        client.queue(
            """{
              "summary": "bad commercial output",
              "method": "rNPV",
              "scope": "pipeline assets",
              "assumptions": ["uses pipeline rNPV"],
              "valuation_range": {"bear": 1, "base": 2, "bull": 3},
              "sensitivity": [],
              "risks": [],
              "confidence": 0.8,
              "needs_human_review": false,
              "currency": "HKD",
              "value_type": "per_share",
              "unit_basis": "reported",
              "fx_assumption": "HKD",
              "shares_outstanding_used": 100
            }"""
        )
        agent = ValuationCommercialLLMAgent(llm_client=client)
        context = AgentContext(company="Leads Biolabs", ticker="09887.HK")
        store = FactStore(
            {
                "financials_snapshot": {"revenue_ttm": None},
                "valuation_snapshot": {"shares_outstanding": 100.0},
            }
        )

        step = agent.run(context, store)

        self.assertTrue(step.ok)
        payload = step.outputs["valuation_commercial_payload"]
        self.assertEqual(payload["method"], "multiple")
        self.assertEqual(payload["valuation_range"]["base"], 0.0)
        self.assertEqual(payload["value_type"], "equity_value")

    def test_balance_sheet_agent_forces_net_cash_adjustment(self) -> None:
        client = FakeLLMClient()
        client.queue(
            """{
              "summary": "bad balance-sheet output",
              "method": "rNPV",
              "scope": "pipeline plus cash",
              "assumptions": ["uses pipeline rNPV"],
              "valuation_range": {"bear": 10, "base": 20, "bull": 30},
              "sensitivity": [],
              "risks": [],
              "confidence": 0.8,
              "needs_human_review": false,
              "currency": "HKD",
              "value_type": "per_share",
              "unit_basis": "reported",
              "fx_assumption": "HKD",
              "shares_outstanding_used": 100
            }"""
        )
        agent = ValuationBalanceSheetLLMAgent(llm_client=client)
        context = AgentContext(company="Leads Biolabs", ticker="09887.HK")
        store = FactStore(
            {
                "valuation_snapshot": {
                    "cash": 120.0,
                    "debt": 20.0,
                    "shares_outstanding": 100.0,
                }
            }
        )

        step = agent.run(context, store)

        self.assertTrue(step.ok)
        payload = step.outputs["valuation_balance_sheet_payload"]
        self.assertEqual(payload["method"], "balance_sheet_adjustment")
        self.assertEqual(payload["valuation_range"]["base"], 100.0)
        self.assertEqual(payload["value_type"], "equity_value")


class ReportQualityLLMAgentTest(unittest.TestCase):
    def test_report_quality_prompt_includes_memo_review_payload(self) -> None:
        client = FakeLLMClient()
        client.queue(
            """{
              "summary": "memo language review completed",
              "publish_gate": "review_required",
              "critical_issues": [],
              "consistency_findings": [],
              "missing_evidence_findings": [],
              "language_quality_findings": ["需要避免把观察信号写成交易建议。"],
              "valuation_coherence_findings": [],
              "recommended_fixes": ["复核执行结论中的市场语言。"],
              "issue_classification": [],
              "confidence": 0.61
            }"""
        )
        agent = ReportQualityLLMAgent(llm_client=client)
        context = AgentContext(company="DualityBio", ticker="09606.HK")
        store = FactStore(
            {
                "scorecard_summary": {"watchlist_score": 70},
                "memo_review_payload": {
                    "available": True,
                    "markdown_excerpt": "## 执行结论\n市场语言需要复核。",
                },
                "report_synthesizer_payload": {
                    "executive_verdict_paragraph": "维持观察名单。"
                },
            }
        )

        step = agent.run(context, store)

        self.assertTrue(step.ok)
        self.assertEqual(
            step.outputs["report_quality_payload"]["publish_gate"],
            "review_required",
        )
        self.assertIn("Memo review payload", client.calls[0].prompt)
        self.assertIn("市场语言需要复核", client.calls[0].prompt)
        self.assertIn("Report synthesizer payload", client.calls[0].prompt)

    def test_report_quality_falls_back_to_review_required_on_llm_error(self) -> None:
        client = FakeLLMClient()
        client.queue(raise_error=LLMError("simulated failure"))
        agent = ReportQualityLLMAgent(llm_client=client)
        context = AgentContext(company="DualityBio", ticker="09606.HK")
        store = FactStore({"scorecard_summary": {"watchlist_score": 70}})

        step = agent.run(context, store)

        self.assertTrue(step.ok)
        payload = step.outputs["report_quality_payload"]
        self.assertEqual(payload["publish_gate"], "review_required")
        self.assertIn("report_quality_unavailable", payload["critical_issues"][0])
        self.assertTrue(step.finding.needs_human_review)

    def test_report_quality_downgrades_soft_only_block(self) -> None:
        payload = {
            "summary": "soft issues only",
            "publish_gate": "block",
            "critical_issues": ["文案重复，建议优化表述。"],
            "consistency_findings": [],
            "missing_evidence_findings": [],
            "language_quality_findings": ["存在少量英文片段。"],
            "valuation_coherence_findings": [],
            "recommended_fixes": ["统一术语。"],
            "issue_classification": [
                {
                    "issue": "wording repeat",
                    "severity": "soft_warning",
                    "rationale": "style only",
                }
            ],
        }
        patched = _postprocess_report_quality_payload(
            payload=payload,
            store=FactStore({}),
        )
        self.assertEqual(patched["publish_gate"], "review_required")

    def test_report_quality_downgrades_market_expectation_gap_only(self) -> None:
        payload = {
            "summary": "missing market expectation explanation",
            "publish_gate": "block",
            "critical_issues": [
                "估值口径缺少市场预期解释：保守rNPV低于当前市值。"
            ],
            "consistency_findings": [],
            "missing_evidence_findings": [],
            "language_quality_findings": [],
            "valuation_coherence_findings": [
                "需要解释market-implied assumptions。"
            ],
            "recommended_fixes": ["补充市场隐含假设。"],
            "issue_classification": [],
        }
        patched = _postprocess_report_quality_payload(
            payload=payload,
            store=FactStore({}),
        )
        self.assertEqual(patched["publish_gate"], "review_required")


class ValuationNormalizationTest(unittest.TestCase):
    def test_normalize_payload_sets_required_contract_fields(self) -> None:
        normalized = _normalize_valuation_payload(
            payload={
                "method": "rNPV",
                "currency": "HKD",
                "valuation_range": {"bear": 1, "base": 2, "bull": 3},
            },
            component="valuation-pipeline-rnpv-agent",
            valuation_snapshot={"shares_outstanding": 100.0},
        )
        self.assertEqual(normalized["value_type"], "per_share")
        self.assertEqual(normalized["unit_basis"], "reported_by_sub_agent")
        self.assertIn("HKD", normalized["fx_assumption"])
        self.assertEqual(normalized["shares_outstanding_used"], 100.0)


if __name__ == "__main__":
    unittest.main()
