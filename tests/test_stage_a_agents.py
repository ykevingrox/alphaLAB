"""Regression tests for Stage A valuation pod + report quality agents."""

from __future__ import annotations

import unittest

from biotech_alpha.agent_runtime import FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    ReportQualityLLMAgent,
    ValuationCommitteeLLMAgent,
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


class ReportQualityLLMAgentTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

