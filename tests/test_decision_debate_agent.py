from __future__ import annotations

import json
import unittest

from biotech_alpha.agent_runtime import AgentGraph, DeterministicAgent, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    DECISION_DEBATE_PROMPT,
    DecisionDebateLLMAgent,
)
from biotech_alpha.llm import FakeLLMClient


def _ctx() -> AgentContext:
    return AgentContext(
        company="DualityBio",
        ticker="09606.HK",
        market="HK",
        as_of_date="2026-04-28",
    )


def _facts() -> dict:
    return {
        "memo_scaffold_payload": {
            "company": "DualityBio",
            "ticker": "09606.HK",
            "decision": "watchlist",
            "deterministic_summary": "Pipeline breadth with evidence gaps.",
        },
        "data_collector_payload": {"run_verdict": "needs_more_evidence"},
        "strategic_economics_payload": {
            "commercialization_path": "region_split",
            "value_capture_score": 62,
        },
        "catalyst_payload": {
            "priority_events": ["DB-1303 registrational update"]
        },
        "market_expectations_payload": {
            "valuation_band_context": "mid_band",
            "market_implied_assumptions": ["BD economics remain credible"],
        },
        "market_regime_timing_payload": {"timing_view": "neutral"},
        "valuation_committee_payload": {
            "market_implied_value": {"market_cap": 54000000000}
        },
        "scorecard_summary": {"watchlist_score": 68},
    }


def _happy_payload() -> dict:
    return {
        "bull_case": [
            {
                "claim": "BD economics and late-stage catalysts can explain part of the market value.",
                "evidence_key": "strategic_economics_payload",
                "confidence": 0.62,
            }
        ],
        "bear_case": [
            {
                "claim": "Data quality is not yet strong enough to promote beyond watchlist.",
                "evidence_key": "data_collector_payload",
                "confidence": 0.7,
            }
        ],
        "debate_resolution": (
            "Keep the deterministic watchlist stance while monitoring "
            "catalyst evidence and BD economics."
        ),
        "fundamental_view": "watchlist",
        "timing_view": "neutral",
        "decision_log": {
            "current_decision": "watchlist",
            "key_assumptions": ["BD economics remain credible"],
            "reasons_to_revisit": ["New registrational data are disclosed"],
            "invalidation_triggers": ["Catalyst evidence weakens"],
            "evidence_gaps": ["Need fuller BD economics"],
            "next_review_triggers": ["Next clinical update"],
        },
        "confidence": 0.63,
        "needs_human_review": True,
    }


class DecisionDebateAgentTest(unittest.TestCase):
    def test_produces_decision_debate_payload(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=600,
            completion_tokens=180,
        )
        agent = DecisionDebateLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNone(step.error)
        self.assertEqual(step.outputs["decision_debate_payload"], _happy_payload())
        self.assertEqual(step.finding.agent_name, "decision_debate_llm_agent")
        self.assertIn("watchlist / neutral", step.finding.summary)
        self.assertAlmostEqual(step.finding.confidence, 0.63)
        self.assertTrue(
            any(r.startswith("[bear_case]") for r in step.finding.risks)
        )
        self.assertTrue(
            any(
                r.startswith("[invalidation_trigger]")
                for r in step.finding.risks
            )
        )

    def test_missing_inputs_warns_but_runs(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps(_happy_payload()))
        agent = DecisionDebateLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({}))

        self.assertIsNone(step.error)
        self.assertIn("fallback_context:memo_scaffold_payload", step.warnings)
        self.assertIn(
            "fallback_context:market_expectations_payload", step.warnings
        )

    def test_schema_violation_falls_back_without_blocking_downstream(self) -> None:
        client = FakeLLMClient()
        client.queue('{"decision_debate": {"fundamental_view": "watchlist"}}')
        agent = DecisionDebateLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNone(step.error)
        payload = step.outputs["decision_debate_payload"]
        self.assertEqual(payload["fundamental_view"], "insufficient_data")
        self.assertEqual(payload["confidence"], 0.0)
        self.assertTrue(step.warnings)

    def test_prompt_schema_rejects_trading_label(self) -> None:
        from biotech_alpha.llm.schema import validate_json_schema

        bad = {**_happy_payload(), "fundamental_view": "buy"}
        with self.assertRaises(Exception):
            validate_json_schema(bad, DECISION_DEBATE_PROMPT.schema)


class DecisionDebateGraphTest(unittest.TestCase):
    def test_runs_after_market_expectations_payload(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps(_happy_payload()))
        graph = AgentGraph()

        def publish(_ctx, store):  # noqa: ANN001
            for key, value in _facts().items():
                store.put(key, value)

        def publish_expectations(_ctx, store):  # noqa: ANN001
            store.put("market_expectations_payload", {"valuation_band_context": "mid_band"})

        graph.add(DeterministicAgent("publish_research_facts", publish))
        graph.add(
            DeterministicAgent(
                "market_expectations_llm_agent",
                publish_expectations,
                depends_on=("publish_research_facts",),
            )
        )
        graph.add(
            DecisionDebateLLMAgent(
                llm_client=client,
                depends_on=("market_expectations_llm_agent",),
            )
        )

        result = graph.run(_ctx())

        step = result.step("decision_debate_llm_agent")
        self.assertIsNotNone(step)
        assert step is not None
        self.assertIsNone(step.error)
        self.assertIn("decision_debate_payload", result.facts)


if __name__ == "__main__":
    unittest.main()
