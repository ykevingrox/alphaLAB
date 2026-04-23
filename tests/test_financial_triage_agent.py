"""Tests for the FinancialTriageLLMAgent."""

from __future__ import annotations

import json
import os
import unittest

from biotech_alpha.agent_runtime import AgentGraph, DeterministicAgent, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    FINANCIAL_TRIAGE_PROMPT,
    FinancialTriageLLMAgent,
    PipelineTriageLLMAgent,
    ScientificSkepticLLMAgent,
)
from biotech_alpha.llm import FakeLLMClient


def _financials_snapshot() -> dict:
    return {
        "financial_snapshot": {
            "as_of_date": "2025-12-31",
            "currency": "RMB",
            "cash_and_equivalents": 2_000_000_000.0,
            "short_term_debt": 50_000_000.0,
            "quarterly_cash_burn": 180_000_000.0,
            "operating_cash_flow_ttm": -720_000_000.0,
            "source": "annual_report",
            "source_date": "2026-03-23",
        },
        "runway_estimate": {
            "currency": "RMB",
            "net_cash": 1_950_000_000.0,
            "monthly_cash_burn": 60_000_000.0,
            "runway_months": 32.5,
            "method": "operating_cash_flow_ttm",
            "needs_human_review": False,
            "warnings": [],
        },
        "market_snapshot": {
            "currency": "HKD",
            "market_cap": 15_000_000_000.0,
            "share_price": 120.0,
            "shares_outstanding": 125_000_000.0,
            "cash": None,
            "debt": None,
            "revenue_ttm": None,
        },
        "valuation_metrics": {
            "enterprise_value": 13_000_000_000.0,
            "ev_to_revenue": None,
        },
        "financial_warnings": [
            "revenue_ttm unavailable; revenue multiple not calculated",
        ],
    }


def _initial_facts() -> dict:
    return {
        "financials_snapshot": _financials_snapshot(),
        "trial_summary": {"total": 8, "late_stage": 1, "active": 4},
        "input_warnings": [],
    }


def _ctx() -> AgentContext:
    return AgentContext(
        company="DualityBio", ticker="09606.HK", market="HK",
    )


def _happy_payload() -> dict:
    return {
        "runway_sanity": "inconsistent",
        "summary": (
            "Runway number is internally inconsistent; cash / monthly burn "
            "implies ~32 months while currency and revenue visibility are "
            "concerning."
        ),
        "implied_runway_months": 32.5,
        "confidence": 0.75,
        "findings": [
            {
                "severity": "high",
                "metric": "currency",
                "description": (
                    "financial_snapshot is in RMB while market_snapshot "
                    "is in HKD; EV-to-cash comparisons are not apples "
                    "to apples without FX alignment."
                ),
                "suggested_action": (
                    "Normalize both snapshots to a single reporting "
                    "currency before downstream analysis."
                ),
            },
            {
                "severity": "medium",
                "metric": "revenue_ttm",
                "description": (
                    "revenue_ttm is null on a company carrying an EV "
                    "above USD 1.5B; commercial traction cannot be "
                    "verified."
                ),
                "suggested_action": None,
            },
        ],
    }


class FinancialTriageHappyPathTest(unittest.TestCase):
    def test_produces_finding_with_severity_and_metric_tags(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=800,
            completion_tokens=240,
        )
        agent = FinancialTriageLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertAlmostEqual(step.finding.confidence, 0.75)
        self.assertTrue(
            any("[runway_sanity] inconsistent" in r for r in step.finding.risks),
            msg=str(step.finding.risks),
        )
        self.assertTrue(
            any("[high][currency]" in r for r in step.finding.risks)
        )
        self.assertTrue(
            any("[medium][revenue_ttm]" in r for r in step.finding.risks)
        )
        self.assertIn("financial_triage_llm_finding", step.outputs)
        self.assertIn("financial_triage_payload", step.outputs)

    def test_uses_fallback_when_financials_snapshot_missing(self) -> None:
        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    "runway_sanity": "insufficient_data",
                    "summary": "Fallback financial triage due to missing snapshot.",
                    "findings": [],
                }
            )
        )
        agent = FinancialTriageLLMAgent(llm_client=client)

        step = agent.run(
            _ctx(),
            FactStore({"financials_snapshot": None}),
        )

        self.assertFalse(step.skipped)
        self.assertIsNone(step.error)
        self.assertTrue(any("fallback_context:financial_triage" in w for w in step.warnings))

    def test_schema_violation_records_error(self) -> None:
        client = FakeLLMClient()
        client.queue('{"runway_sanity": "consistent"}')
        agent = FinancialTriageLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")

    def test_bad_enum_is_rejected(self) -> None:
        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    "runway_sanity": "probably_ok",
                    "summary": "Runway looks OK.",
                    "findings": [],
                }
            )
        )
        agent = FinancialTriageLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("runway_sanity", step.error or "")


class FinancialTriageInGraphTest(unittest.TestCase):
    def test_triple_agent_chain_feeds_skeptic(self) -> None:
        pipeline_facts = {
            "pipeline_snapshot": {
                "assets": [
                    {
                        "name": "DB-1312",
                        "phase": "Phase 1",
                        "next_milestone": "in 2017",
                    }
                ]
            },
            "trial_summary": {"total": 8, "late_stage": 1, "active": 4},
            "input_warnings": [],
            "source_text_excerpt": {
                "title": "Annual Results",
                "anchor_assets": ["DB-1312"],
                "missing_assets": [],
                "total_chars": 1000,
                "excerpt_chars": 120,
                "truncated": False,
                "excerpt": (
                    "DB-1312 B7-H4 Phase 1 dose-escalation; next "
                    "milestone listed as 'in 2017'.\n"
                ),
            },
            "financials_snapshot": _financials_snapshot(),
        }

        pipeline_payload = {
            "coverage_confidence": 0.95,
            "summary": "One high-severity milestone anomaly.",
            "assets": [
                {
                    "name": "DB-1312",
                    "severity": "high",
                    "issues": [
                        "next_milestone 'in 2017' predates report year",
                    ],
                }
            ],
        }
        skeptic_payload = {
            "summary": (
                "Currency and milestone anomalies combine to make the "
                "bull case unsafe to underwrite."
            ),
            "bear_case": ["Currency mismatch obscures EV / cash math"],
            "risks": [
                {
                    "description": (
                        "Currency mismatch between financial and "
                        "market snapshots"
                    ),
                    "severity": "high",
                }
            ],
            "confidence": 0.7,
        }

        triage_client = FakeLLMClient()
        triage_client.queue(json.dumps(pipeline_payload))
        financial_client = FakeLLMClient()
        financial_client.queue(json.dumps(_happy_payload()))
        skeptic_client = FakeLLMClient()
        skeptic_client.queue(json.dumps(skeptic_payload))

        def publish(ctx, store):
            for key, value in pipeline_facts.items():
                store.put(key, value)
            return None

        graph = AgentGraph()
        graph.add(DeterministicAgent("publish", publish))
        graph.add(
            PipelineTriageLLMAgent(
                llm_client=triage_client, depends_on=("publish",)
            )
        )
        graph.add(
            FinancialTriageLLMAgent(
                llm_client=financial_client, depends_on=("publish",)
            )
        )
        graph.add(
            ScientificSkepticLLMAgent(
                llm_client=skeptic_client,
                depends_on=(
                    "publish",
                    "pipeline_triage_llm_agent",
                    "financial_triage_llm_agent",
                ),
            )
        )

        result = graph.run(_ctx())

        names = [s.agent_name for s in result.steps]
        self.assertEqual(names[0], "publish")
        self.assertIn("pipeline_triage_llm_agent", names)
        self.assertIn("financial_triage_llm_agent", names)
        self.assertEqual(names[-1], "scientific_skeptic_llm_agent")
        self.assertEqual(len(result.findings), 3)
        self.assertIn("financial_triage_payload", result.facts)
        self.assertIn("pipeline_triage_payload", result.facts)
        self.assertIn("scientific_skeptic_llm_finding", result.facts)


@unittest.skipUnless(
    os.getenv("BIOTECH_ALPHA_ONLINE_LLM_TESTS") == "1",
    "online LLM tests disabled; set BIOTECH_ALPHA_ONLINE_LLM_TESTS=1 to enable",
)
class FinancialTriageOnlineTest(unittest.TestCase):
    def test_live_financial_triage_call_matches_schema(self) -> None:
        from biotech_alpha.llm import (
            LLMConfig,
            LLMTraceRecorder,
            OpenAICompatibleLLMClient,
        )

        config = LLMConfig.from_env()
        recorder = LLMTraceRecorder()
        client = OpenAICompatibleLLMClient(config, trace_recorder=recorder)
        agent = FinancialTriageLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertGreaterEqual(len(recorder.entries), 1)


if __name__ == "__main__":
    unittest.main()
