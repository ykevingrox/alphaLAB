from __future__ import annotations

import json
import unittest

from biotech_alpha.agent_runtime import AgentGraph, DeterministicAgent, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import CATALYST_PROMPT, CatalystLLMAgent
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
        "catalyst_calendar_payload": {
            "count": 1,
            "catalysts": [
                {
                    "title": "DB-1303 Phase 3 readout",
                    "category": "clinical",
                    "expected_window": "2H 2026",
                    "related_asset": "DB-1303",
                    "confidence": 0.7,
                    "evidence": [
                        {
                            "claim": "company disclosed expected readout window",
                            "source": "annual_results",
                            "confidence": 0.7,
                        }
                    ],
                }
            ],
        },
        "event_impact_payload": {
            "event_impacts": [
                {
                    "event_type": "positive_readout",
                    "asset_name": "DB-1303",
                    "probability_of_success_delta": 0.15,
                    "peak_sales_delta_pct": 0.1,
                    "rationale": "source-backed catalyst review",
                }
            ],
            "event_value_delta": 1200000000,
            "asset_value_delta": 900000000,
            "currency": "HKD",
            "needs_human_review": True,
        },
        "target_price_snapshot": {
            "event_value_delta": 1200000000,
            "probability_weighted_target_price": 42.0,
            "currency": "HKD",
        },
        "pipeline_snapshot": {
            "assets": [{"name": "DB-1303", "phase": "Phase 3"}],
        },
        "strategic_economics_payload": {
            "commercialization_path": "region_split",
        },
        "source_text_excerpt": {
            "title": "Annual results",
            "url": "https://example.test/annual",
            "excerpt": "DB-1303 Phase 3 readout expected in 2H 2026.",
        },
    }


def _happy_payload() -> dict:
    return {
        "catalyst_events": [
            {
                "event": "DB-1303 Phase 3 readout",
                "category": "clinical",
                "asset": "DB-1303",
                "window": "2H 2026",
                "evidence_quality": "medium",
                "binary_risk": "high",
                "expectation_risk": "Readout may already be partly priced in.",
                "repricing_path": (
                    "Use provided positive_readout event impact; no new "
                    "delta invented."
                ),
            }
        ],
        "priority_events": ["DB-1303 Phase 3 readout"],
        "market_priced_in_flags": [
            "High market expectation around the readout could amplify downside."
        ],
        "evidence_gaps": ["Need exact data presentation date."],
        "confidence": 0.61,
        "needs_human_review": True,
    }


class CatalystAgentTest(unittest.TestCase):
    def test_produces_catalyst_payload(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=500,
            completion_tokens=160,
        )
        agent = CatalystLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNone(step.error)
        self.assertEqual(step.outputs["catalyst_payload"], _happy_payload())
        self.assertEqual(step.finding.agent_name, "catalyst_llm_agent")
        self.assertIn("Catalyst review covered 1 event", step.finding.summary)
        self.assertAlmostEqual(step.finding.confidence, 0.61)
        self.assertTrue(
            any(r.startswith("[catalyst_event]") for r in step.finding.risks)
        )
        self.assertTrue(
            any(r.startswith("[expectation_risk]") for r in step.finding.risks)
        )

    def test_missing_inputs_warns_but_runs(self) -> None:
        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    **_happy_payload(),
                    "catalyst_events": [
                        {
                            **_happy_payload()["catalyst_events"][0],
                            "evidence_quality": "insufficient_data",
                        }
                    ],
                    "confidence": 0.25,
                }
            )
        )
        agent = CatalystLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({}))

        self.assertIsNone(step.error)
        self.assertIn("fallback_context:catalyst_calendar_payload", step.warnings)
        self.assertIn("fallback_context:event_impact_payload", step.warnings)

    def test_schema_violation_falls_back_without_blocking_downstream(self) -> None:
        client = FakeLLMClient()
        client.queue('{"catalyst": {"priority_events": []}}')
        agent = CatalystLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNone(step.error)
        payload = step.outputs["catalyst_payload"]
        self.assertEqual(payload["catalyst_events"], [])
        self.assertEqual(payload["confidence"], 0.0)
        self.assertTrue(step.warnings)

    def test_prompt_schema_rejects_buy_signal_labels(self) -> None:
        from biotech_alpha.llm.schema import validate_json_schema

        bad = {
            **_happy_payload(),
            "catalyst_events": [
                {
                    **_happy_payload()["catalyst_events"][0],
                    "binary_risk": "buy_signal",
                }
            ],
        }
        with self.assertRaises(Exception):
            validate_json_schema(bad, CATALYST_PROMPT.schema)


class CatalystGraphTest(unittest.TestCase):
    def test_runs_after_strategic_payload(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps(_happy_payload()))
        graph = AgentGraph()

        def publish(_ctx, store):  # noqa: ANN001
            for key, value in _facts().items():
                store.put(key, value)

        def publish_strategic(_ctx, store):  # noqa: ANN001
            store.put("strategic_economics_payload", {"value_capture_score": 64})

        graph.add(DeterministicAgent("publish_research_facts", publish))
        graph.add(
            DeterministicAgent(
                "strategic_economics_llm_agent",
                publish_strategic,
                depends_on=("publish_research_facts",),
            )
        )
        graph.add(
            CatalystLLMAgent(
                llm_client=client,
                depends_on=("strategic_economics_llm_agent",),
            )
        )

        result = graph.run(_ctx())

        step = result.step("catalyst_llm_agent")
        self.assertIsNotNone(step)
        assert step is not None
        self.assertIsNone(step.error)
        self.assertIn("catalyst_payload", result.facts)


if __name__ == "__main__":
    unittest.main()
