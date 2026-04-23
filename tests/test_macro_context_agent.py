"""Tests for the MacroContextLLMAgent."""

from __future__ import annotations

import json
import os
import unittest

from biotech_alpha.agent_runtime import (
    AgentGraph,
    DeterministicAgent,
    FactStore,
)
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    MACRO_CONTEXT_PROMPT,
    FinancialTriageLLMAgent,
    MacroContextLLMAgent,
    PipelineTriageLLMAgent,
    ScientificSkepticLLMAgent,
)
from biotech_alpha.llm import FakeLLMClient


def _macro_context_fact() -> dict:
    return {
        "market": "HK",
        "sector": "biotech",
        "ticker": "09606.HK",
        "company": "DualityBio",
        "report_run_date": "2026-04-22",
        "financial_as_of_date": "2025-12-31",
        "source_publication_dates": ["2026-03-23"],
        "source_titles": [
            "2025 Annual Results Announcement",
        ],
        "source_types": ["HKEX_ANNUAL_RESULTS"],
        "known_unknowns": [
            "live HSI / HSBIO index trend",
            "US rate environment and USD/HKD peg status",
        ],
    }


def _initial_facts() -> dict:
    return {
        "macro_context": _macro_context_fact(),
    }


def _ctx() -> AgentContext:
    return AgentContext(
        company="DualityBio",
        ticker="09606.HK",
        market="HK",
        as_of_date="2026-04-22",
    )


def _happy_payload() -> dict:
    return {
        "macro_regime": "transition",
        "summary": (
            "HK biotech is in transition: sponsor-IPO window is reopening "
            "while rate-cut trajectory remains ambiguous."
        ),
        "confidence": 0.55,
        "sector_drivers": [
            "HKEX 18A refinancing channel active",
            "China NMPA backlog easing",
        ],
        "sector_headwinds": [
            "USD/HKD peg tightening offsets local rate cuts",
            "Macro news feed not provided; directional read is partial",
        ],
    }


class MacroContextHappyPathTest(unittest.TestCase):
    def test_produces_finding_with_regime_and_headwind_tags(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=500,
            completion_tokens=180,
        )
        agent = MacroContextLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertAlmostEqual(step.finding.confidence, 0.55)
        # transition regime is not flagged as a risk tag, only contraction
        # or insufficient_data are.
        self.assertFalse(
            any(r.startswith("[macro_regime]") for r in step.finding.risks),
            msg=str(step.finding.risks),
        )
        self.assertTrue(
            any("[headwind]" in r for r in step.finding.risks),
            msg=str(step.finding.risks),
        )
        self.assertIn("macro_context_llm_finding", step.outputs)
        self.assertIn("macro_context_payload", step.outputs)

    def test_insufficient_data_regime_surfaces_risk_tag(self) -> None:
        payload = {
            "macro_regime": "insufficient_data",
            "summary": (
                "Stub lacks live index and rate data; cannot form a "
                "directional read."
            ),
            "confidence": 0.2,
            "sector_drivers": [],
            "sector_headwinds": [
                "Rate trajectory unclear from provided inputs",
            ],
        }
        client = FakeLLMClient()
        client.queue(json.dumps(payload))
        agent = MacroContextLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNone(step.error)
        self.assertTrue(
            any(
                r == "[macro_regime] insufficient_data"
                for r in step.finding.risks
            ),
            msg=str(step.finding.risks),
        )

    def test_uses_fallback_when_macro_context_missing(self) -> None:
        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    "macro_regime": "insufficient_data",
                    "summary": "Fallback macro context with missing stub.",
                    "sector_drivers": [],
                    "sector_headwinds": ["macro data missing in structured inputs"],
                }
            )
        )
        agent = MacroContextLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({"macro_context": None}))

        self.assertFalse(step.skipped)
        self.assertIsNone(step.error)
        self.assertTrue(any("fallback_context:macro_context" in w for w in step.warnings))

    def test_schema_violation_records_error(self) -> None:
        client = FakeLLMClient()
        client.queue('{"macro_regime": "transition"}')
        agent = MacroContextLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")

    def test_bad_regime_enum_is_rejected(self) -> None:
        bad = {
            "macro_regime": "bull",
            "summary": "Looks good.",
            "sector_drivers": [],
            "sector_headwinds": [],
        }
        client = FakeLLMClient()
        client.queue(json.dumps(bad))
        agent = MacroContextLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("macro_regime", step.error or "")


class MacroContextPromptShapeTest(unittest.TestCase):
    def test_prompt_rejects_long_driver_strings(self) -> None:
        from biotech_alpha.llm.schema import validate_json_schema

        bad = {
            "macro_regime": "transition",
            "summary": "fine",
            "sector_drivers": ["x" * 500],
            "sector_headwinds": [],
        }
        with self.assertRaises(Exception):
            validate_json_schema(bad, MACRO_CONTEXT_PROMPT.schema)


class MacroContextInGraphTest(unittest.TestCase):
    def test_four_agent_chain_feeds_skeptic(self) -> None:
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
                "excerpt": "DB-1312 Phase 1.\n",
            },
            "financials_snapshot": {
                "financial_snapshot": {
                    "as_of_date": "2025-12-31",
                    "currency": "RMB",
                    "cash_and_equivalents": 2_000_000_000.0,
                    "short_term_debt": 50_000_000.0,
                    "quarterly_cash_burn": 180_000_000.0,
                },
                "runway_estimate": {
                    "currency": "RMB",
                    "net_cash": 1_950_000_000.0,
                    "monthly_cash_burn": 60_000_000.0,
                    "runway_months": 32.5,
                    "method": "operating_cash_flow_ttm",
                },
                "financial_warnings": [],
            },
            "macro_context": _macro_context_fact(),
        }

        pipeline_payload = {
            "coverage_confidence": 0.95,
            "summary": "One milestone anomaly.",
            "assets": [
                {
                    "name": "DB-1312",
                    "severity": "high",
                    "issues": ["next_milestone predates report year"],
                }
            ],
        }
        financial_payload = {
            "runway_sanity": "consistent",
            "summary": "Runway numbers are internally coherent.",
            "findings": [],
        }
        macro_payload = _happy_payload()
        skeptic_payload = {
            "summary": (
                "Macro is in transition and the pipeline has a dating "
                "anomaly; skeptic flags combine."
            ),
            "bear_case": [
                "Milestone dates inconsistent with report year",
                "Macro stub too thin for a directional regime read",
            ],
            "risks": [
                {
                    "description": (
                        "Milestone text 'in 2017' cannot be reconciled "
                        "with 2025 report"
                    ),
                    "severity": "high",
                },
                {
                    "description": (
                        "Macro headwinds are partially unobservable from "
                        "the provided stub"
                    ),
                    "severity": "medium",
                },
            ],
            "confidence": 0.65,
        }

        triage_client = FakeLLMClient()
        triage_client.queue(json.dumps(pipeline_payload))
        financial_client = FakeLLMClient()
        financial_client.queue(json.dumps(financial_payload))
        macro_client = FakeLLMClient()
        macro_client.queue(json.dumps(macro_payload))
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
            MacroContextLLMAgent(
                llm_client=macro_client, depends_on=("publish",)
            )
        )
        graph.add(
            ScientificSkepticLLMAgent(
                llm_client=skeptic_client,
                depends_on=(
                    "publish",
                    "pipeline_triage_llm_agent",
                    "financial_triage_llm_agent",
                    "macro_context_llm_agent",
                ),
            )
        )

        result = graph.run(_ctx())

        names = [s.agent_name for s in result.steps]
        self.assertEqual(names[0], "publish")
        for expected in (
            "pipeline_triage_llm_agent",
            "financial_triage_llm_agent",
            "macro_context_llm_agent",
        ):
            self.assertIn(expected, names)
        self.assertEqual(names[-1], "scientific_skeptic_llm_agent")
        self.assertEqual(len(result.findings), 4)
        self.assertIn("macro_context_payload", result.facts)
        self.assertIn("scientific_skeptic_llm_finding", result.facts)


@unittest.skipUnless(
    os.getenv("BIOTECH_ALPHA_ONLINE_LLM_TESTS") == "1",
    "online LLM tests disabled; set BIOTECH_ALPHA_ONLINE_LLM_TESTS=1 to enable",
)
class MacroContextOnlineTest(unittest.TestCase):
    def test_live_macro_context_call_matches_schema(self) -> None:
        from biotech_alpha.llm import (
            LLMConfig,
            LLMTraceRecorder,
            OpenAICompatibleLLMClient,
        )

        config = LLMConfig.from_env()
        recorder = LLMTraceRecorder()
        client = OpenAICompatibleLLMClient(config, trace_recorder=recorder)
        agent = MacroContextLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertGreaterEqual(len(recorder.entries), 1)


@unittest.skipUnless(
    os.getenv("BIOTECH_ALPHA_ONLINE_ANTHROPIC_TESTS") == "1"
    and bool(os.getenv("ANTHROPIC_API_KEY")),
    "anthropic online tests disabled; set "
    "BIOTECH_ALPHA_ONLINE_ANTHROPIC_TESTS=1 and ANTHROPIC_API_KEY",
)
class MacroContextAnthropicOnlineTest(unittest.TestCase):
    def test_live_macro_context_call_matches_schema(self) -> None:
        from biotech_alpha.llm import (
            AnthropicLLMClient,
            LLMConfig,
            LLMTraceRecorder,
        )

        env = dict(os.environ)
        env["BIOTECH_ALPHA_LLM_PROVIDER"] = "anthropic"
        config = LLMConfig.from_env(env)
        recorder = LLMTraceRecorder()
        client = AnthropicLLMClient(config, trace_recorder=recorder)
        agent = MacroContextLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertGreaterEqual(len(recorder.entries), 1)


if __name__ == "__main__":
    unittest.main()
