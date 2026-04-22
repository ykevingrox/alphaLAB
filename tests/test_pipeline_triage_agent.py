"""Tests for the PipelineTriageLLMAgent."""

from __future__ import annotations

import json
import os
import unittest

from biotech_alpha.agent_runtime import AgentGraph, DeterministicAgent, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    PIPELINE_TRIAGE_PROMPT,
    PipelineTriageLLMAgent,
    ScientificSkepticLLMAgent,
)
from biotech_alpha.llm import FakeLLMClient


def _initial_facts() -> dict:
    return {
        "pipeline_snapshot": {
            "assets": [
                {
                    "name": "DB-1303",
                    "target": "HER2",
                    "phase": "Phase 3",
                    "next_milestone": "in 2026",
                },
                {
                    "name": "DB-1312",
                    "target": "B7-H4",
                    "phase": "Phase 1",
                    "next_milestone": "in 2017",
                },
            ]
        },
        "trial_summary": {"total": 8, "late_stage": 1, "active": 4},
        "input_warnings": [
            "DB-1312 next_milestone 'in 2017' predates the reporting window",
        ],
        "source_text_excerpt": {
            "source_type": "hkex_annual_results",
            "title": "Annual Results",
            "url": "https://example.com/results.pdf",
            "publication_date": "2026-03-23",
            "anchor_assets": ["DB-1303", "DB-1312"],
            "missing_assets": [],
            "total_chars": 120000,
            "excerpt_chars": 240,
            "truncated": False,
            "excerpt": (
                "[... source ~offset 1200 ...]\n"
                "DB-1303 HER2 ADC Phase 3 topline readout in 2026.\n"
                "---\n"
                "[... source ~offset 8800 ...]\n"
                "DB-1312 B7-H4 Phase 1 dose-escalation; next milestone "
                "listed as 'in 2017' (likely a typo).\n"
            ),
        },
    }


def _ctx() -> AgentContext:
    return AgentContext(
        company="DualityBio", ticker="09606.HK", market="HK",
    )


def _happy_payload() -> dict:
    return {
        "coverage_confidence": 0.8,
        "summary": (
            "Pipeline is largely consistent with the source text; one "
            "milestone date looks stale for DB-1312."
        ),
        "global_warnings": [
            "Source text only partially covers early-stage assets.",
        ],
        "assets": [
            {
                "name": "DB-1303",
                "severity": "none",
                "issues": [],
                "confidence": 0.9,
            },
            {
                "name": "DB-1312",
                "severity": "high",
                "issues": [
                    "next_milestone 'in 2017' is before the reporting year",
                ],
                "suggested_fixes": [
                    "Re-extract milestone from annual results table",
                ],
                "confidence": 0.85,
            },
        ],
    }


class PipelineTriageHappyPathTest(unittest.TestCase):
    def test_produces_finding_with_per_asset_risks(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=900,
            completion_tokens=300,
        )
        agent = PipelineTriageLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertAlmostEqual(step.finding.confidence, 0.8)
        self.assertTrue(
            any("[high][DB-1312]" in risk for risk in step.finding.risks),
            msg=str(step.finding.risks),
        )
        self.assertTrue(
            any("[global]" in risk for risk in step.finding.risks),
        )
        self.assertNotIn("DB-1303", "\n".join(step.finding.risks))
        self.assertIn("pipeline_triage_llm_finding", step.outputs)
        self.assertIn("pipeline_triage_payload", step.outputs)

    def test_skips_when_pipeline_is_empty(self) -> None:
        client = FakeLLMClient()
        agent = PipelineTriageLLMAgent(llm_client=client)

        step = agent.run(
            _ctx(),
            FactStore({"pipeline_snapshot": {"assets": []}}),
        )

        self.assertTrue(step.skipped)
        self.assertIn("no pipeline assets", step.error or "")
        self.assertEqual(client.calls, [])

    def test_schema_violation_records_error(self) -> None:
        client = FakeLLMClient()
        client.queue('{"coverage_confidence": 0.8}')
        agent = PipelineTriageLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")
        self.assertTrue(
            any("raw response" in w for w in step.warnings)
        )


class PipelineTriageInGraphTest(unittest.TestCase):
    def test_runs_in_graph_and_feeds_skeptic(self) -> None:
        triage_client = FakeLLMClient()
        triage_client.queue(json.dumps(_happy_payload()))
        skeptic_payload = {
            "summary": (
                "Thin near-term catalysts and one flagged milestone "
                "create data-quality risk."
            ),
            "bear_case": ["Milestone dates need re-verification"],
            "risks": [
                {
                    "description": "Milestone for DB-1312 predates reporting",
                    "severity": "high",
                    "related_asset": "DB-1312",
                }
            ],
            "confidence": 0.6,
        }
        skeptic_client = FakeLLMClient()
        skeptic_client.queue(json.dumps(skeptic_payload))

        def publish(ctx, store):
            for key, value in _initial_facts().items():
                store.put(key, value)
            return None

        graph = AgentGraph()
        graph.add(DeterministicAgent("publish", publish))
        graph.add(
            PipelineTriageLLMAgent(
                llm_client=triage_client,
                depends_on=("publish",),
            )
        )
        graph.add(
            ScientificSkepticLLMAgent(
                llm_client=skeptic_client,
                depends_on=("publish", "pipeline_triage_llm_agent"),
            )
        )

        result = graph.run(_ctx())

        names = [s.agent_name for s in result.steps]
        self.assertEqual(
            names,
            [
                "publish",
                "pipeline_triage_llm_agent",
                "scientific_skeptic_llm_agent",
            ],
        )
        self.assertEqual(len(result.findings), 2)
        self.assertIn("pipeline_triage_payload", result.facts)
        self.assertIn("scientific_skeptic_llm_finding", result.facts)

    def test_skeptic_is_skipped_when_triage_fails(self) -> None:
        failing_triage = FakeLLMClient()
        failing_triage.queue('{"coverage_confidence": 0.8}')
        skeptic_client = FakeLLMClient()
        skeptic_client.queue('{"summary": "should not be called"}')

        def publish(ctx, store):
            for key, value in _initial_facts().items():
                store.put(key, value)
            return None

        graph = AgentGraph()
        graph.add(DeterministicAgent("publish", publish))
        graph.add(
            PipelineTriageLLMAgent(
                llm_client=failing_triage,
                depends_on=("publish",),
            )
        )
        graph.add(
            ScientificSkepticLLMAgent(
                llm_client=skeptic_client,
                depends_on=("publish", "pipeline_triage_llm_agent"),
            )
        )

        result = graph.run(_ctx())

        steps = {s.agent_name: s for s in result.steps}
        self.assertIsNotNone(steps["pipeline_triage_llm_agent"].error)
        self.assertTrue(steps["scientific_skeptic_llm_agent"].skipped)
        self.assertEqual(skeptic_client.calls, [])


@unittest.skipUnless(
    os.getenv("BIOTECH_ALPHA_ONLINE_LLM_TESTS") == "1",
    "online LLM tests disabled; set BIOTECH_ALPHA_ONLINE_LLM_TESTS=1 to enable",
)
class PipelineTriageOnlineTest(unittest.TestCase):
    def test_live_triage_call_matches_schema(self) -> None:
        from biotech_alpha.llm import (
            LLMConfig,
            LLMTraceRecorder,
            OpenAICompatibleLLMClient,
        )

        config = LLMConfig.from_env()
        recorder = LLMTraceRecorder()
        client = OpenAICompatibleLLMClient(config, trace_recorder=recorder)
        agent = PipelineTriageLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_initial_facts()))

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertGreaterEqual(len(recorder.entries), 1)


if __name__ == "__main__":
    unittest.main()
