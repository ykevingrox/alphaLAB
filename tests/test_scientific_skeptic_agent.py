"""Tests for the first LLM-backed agent: ScientificSkepticLLMAgent."""

from __future__ import annotations

import json
import os
import unittest

from biotech_alpha.agent_runtime import AgentGraph, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    SCIENTIFIC_SKEPTIC_PROMPT,
    ScientificSkepticLLMAgent,
)
from biotech_alpha.llm import FakeLLMClient


def _initial_facts() -> dict:
    return {
        "skeptic_risks": [
            "Cash runway may not cover next pivotal readout",
            "Heavy pipeline dependence on a single target (HER2)",
        ],
        "pipeline_snapshot": {
            "assets": [
                {"name": "DB-1303", "phase": "Phase 3", "target": "HER2"},
                {"name": "DB-1310", "phase": "Phase 2", "target": "HER3"},
            ]
        },
        "trial_summary": {"total": 8, "late_stage": 2},
        "valuation_snapshot": {
            "market_cap_usd": 2_100_000_000,
            "net_cash_usd": 300_000_000,
        },
        "input_warnings": ["indication missing for DB-1312"],
    }


def _ctx() -> AgentContext:
    return AgentContext(
        company="DualityBio", ticker="09606.HK", market="HK",
    )


class ScientificSkepticLLMAgentHappyPathTest(unittest.TestCase):
    def test_produces_finding_from_well_formed_json(self) -> None:
        payload = {
            "summary": (
                "Pivotal HER2 readout risk dominates the thesis; "
                "cash runway is thin."
            ),
            "bull_case": ["Phase 3 readout on DB-1303 within 12 months"],
            "bear_case": [
                "Single-asset concentration on HER2",
                "Competitor HER2 ADCs (ENHERTU) already approved",
            ],
            "risks": [
                {
                    "description": "DB-1303 pivotal readout could miss endpoint",
                    "severity": "high",
                    "related_asset": "DB-1303",
                    "evidence_key": "pipeline.DB-1303",
                },
                {
                    "description": "Cash runway may be exhausted before approval",
                    "severity": "medium",
                    "related_asset": None,
                    "evidence_key": None,
                },
            ],
            "needs_more_evidence": [
                "Exact OS/PFS hazard ratios vs comparator"
            ],
            "confidence": 0.55,
        }
        client = FakeLLMClient(model="fake-qwen")
        client.queue(json.dumps(payload), prompt_tokens=500, completion_tokens=250)
        agent = ScientificSkepticLLMAgent(llm_client=client)

        store = FactStore(_initial_facts())
        step = agent.run(_ctx(), store)

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertIn("HER2", step.finding.summary)
        self.assertTrue(
            any("DB-1303" in risk for risk in step.finding.risks)
        )
        self.assertTrue(
            any("[bear]" in risk for risk in step.finding.risks)
        )
        self.assertAlmostEqual(step.finding.confidence, 0.55)
        self.assertTrue(step.finding.needs_human_review)
        self.assertIn(
            "scientific_skeptic_llm_finding", step.outputs
        )

    def test_schema_violation_records_error_and_preserves_raw(self) -> None:
        client = FakeLLMClient()
        client.queue('{"summary": "ok"}')  # missing required bear_case/risks
        agent = ScientificSkepticLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")
        self.assertTrue(
            any("raw response" in w for w in step.warnings)
        )

    def test_llm_error_is_captured_without_raising(self) -> None:
        from biotech_alpha.llm.client import LLMError

        client = FakeLLMClient()
        client.queue(raise_error=LLMError("429 rate limit"))
        agent = ScientificSkepticLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("LLM call failed", step.error or "")


class ScientificSkepticLLMAgentInGraphTest(unittest.TestCase):
    def test_agent_runs_inside_graph_with_deterministic_peers(self) -> None:
        from biotech_alpha.agent_runtime import DeterministicAgent

        def publish_facts(ctx, store):
            for key, value in _initial_facts().items():
                store.put(key, value)
            return None

        payload = {
            "summary": "Thin cash; single-asset risk; HER2 crowded.",
            "bear_case": ["HER2 ADC competition is intense"],
            "risks": [
                {
                    "description": "Dependence on a single HER2 asset",
                    "severity": "high",
                }
            ],
            "confidence": 0.5,
        }
        client = FakeLLMClient()
        client.queue(json.dumps(payload))

        graph = AgentGraph()
        graph.add(DeterministicAgent("publish", publish_facts))
        graph.add(
            ScientificSkepticLLMAgent(
                llm_client=client,
                depends_on=("publish",),
            )
        )

        result = graph.run(_ctx())

        names = [s.agent_name for s in result.steps]
        self.assertEqual(
            names,
            ["publish", "scientific_skeptic_llm_agent"],
        )
        self.assertEqual(len(result.findings), 1)
        self.assertIn(
            "scientific_skeptic_llm_finding", result.facts
        )


@unittest.skipUnless(
    os.getenv("BIOTECH_ALPHA_ONLINE_LLM_TESTS") == "1",
    "online LLM tests disabled; set BIOTECH_ALPHA_ONLINE_LLM_TESTS=1 to enable",
)
class ScientificSkepticLLMAgentOnlineTest(unittest.TestCase):
    """Smoke test against the real Qwen endpoint.

    Opt in with ``BIOTECH_ALPHA_ONLINE_LLM_TESTS=1`` plus
    ``BIOTECH_ALPHA_LLM_API_KEY`` (and optionally
    ``BIOTECH_ALPHA_LLM_MODEL``) in the environment. Never commits a key.
    """

    def test_live_call_returns_valid_structure(self) -> None:
        from biotech_alpha.llm import (
            LLMConfig,
            LLMTraceRecorder,
            OpenAICompatibleLLMClient,
        )

        config = LLMConfig.from_env()
        recorder = LLMTraceRecorder()
        client = OpenAICompatibleLLMClient(config, trace_recorder=recorder)
        agent = ScientificSkepticLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertTrue(step.finding.risks)
        self.assertGreaterEqual(len(recorder.entries), 1)


if __name__ == "__main__":
    unittest.main()
