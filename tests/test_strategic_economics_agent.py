from __future__ import annotations

import json
import unittest

from biotech_alpha.agent_runtime import AgentGraph, DeterministicAgent, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    STRATEGIC_ECONOMICS_PROMPT,
    StrategicEconomicsLLMAgent,
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
        "pipeline_snapshot": {
            "assets": [
                {
                    "name": "DB-1303",
                    "target": "HER2",
                    "indication": "breast cancer",
                    "phase": "Phase 3",
                    "partner": "BioNTech",
                }
            ]
        },
        "pipeline_triage_payload": {
            "priority_assets": ["DB-1303"],
            "risks": ["late-stage execution risk"],
        },
        "competition_triage_payload": {
            "crowding_signal": "crowded",
            "findings": ["HER2 ADC space has late-stage competitors"],
        },
        "financials_snapshot": {
            "market_snapshot": {"cash": 2500000000, "debt": 100000000}
        },
        "source_text_excerpt": {
            "title": "Annual results",
            "url": "https://example.test/annual",
            "publication_date": "2026-03-25",
            "excerpt": (
                "DB-1303 is partnered with BioNTech outside selected regions; "
                "milestones and royalties are conditional."
            ),
            "excerpt_chars": 120,
            "total_chars": 120,
            "truncated": False,
        },
        "fallback_context": {"source_documents": [{"title": "Annual results"}]},
    }


def _happy_payload() -> dict:
    return {
        "retained_economics_map": [
            {
                "asset": "DB-1303",
                "region": "selected retained regions",
                "partner": "BioNTech",
                "economics_share": "region-split; exact share not disclosed",
                "evidence": "source_text_excerpt",
            }
        ],
        "bd_validation_events": [
            "Partnering with BioNTech validates science but leaves economics conditional."
        ],
        "partner_quality_assessment": (
            "BioNTech is a credible global development partner; retained "
            "economics still require disclosure."
        ),
        "commercialization_path": "region_split",
        "value_capture_score": 64.0,
        "strategic_premium_discount": [
            "Strategic premium may be justified by partner validation.",
            "Discount remains for undisclosed economics share.",
        ],
        "evidence_gaps": ["Need disclosed royalty and regional economics."],
        "confidence": 0.57,
        "needs_human_review": True,
    }


class StrategicEconomicsAgentTest(unittest.TestCase):
    def test_produces_value_capture_payload(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=520,
            completion_tokens=150,
        )
        agent = StrategicEconomicsLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNone(step.error)
        self.assertEqual(
            step.outputs["strategic_economics_payload"], _happy_payload()
        )
        self.assertEqual(
            step.finding.agent_name, "strategic_economics_llm_agent"
        )
        self.assertEqual(step.finding.score, 64.0)
        self.assertIn("Strategic economics: region_split", step.finding.summary)
        self.assertTrue(
            any(r.startswith("[retained_economics]") for r in step.finding.risks)
        )
        self.assertTrue(
            any(r.startswith("[evidence_gap]") for r in step.finding.risks)
        )

    def test_missing_inputs_warns_but_runs(self) -> None:
        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    **_happy_payload(),
                    "commercialization_path": "unclear",
                    "value_capture_score": 20.0,
                }
            )
        )
        agent = StrategicEconomicsLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({}))

        self.assertIsNone(step.error)
        self.assertIn("fallback_context:pipeline_snapshot", step.warnings)
        self.assertIn("fallback_context:source_text_excerpt", step.warnings)
        self.assertIn("[value_capture_risk] unclear", step.finding.risks)

    def test_schema_violation_records_error(self) -> None:
        client = FakeLLMClient()
        client.queue('{"strategic_economics": {"commercialization_path": "unclear"}}')
        agent = StrategicEconomicsLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")

    def test_prompt_schema_rejects_platform_overclaim_path(self) -> None:
        from biotech_alpha.llm.schema import validate_json_schema

        bad = {**_happy_payload(), "commercialization_path": "platform_premium"}
        with self.assertRaises(Exception):
            validate_json_schema(bad, STRATEGIC_ECONOMICS_PROMPT.schema)


class StrategicEconomicsGraphTest(unittest.TestCase):
    def test_runs_after_pipeline_and_competition_payloads(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps(_happy_payload()))
        graph = AgentGraph()

        def publish(_ctx, store):  # noqa: ANN001
            for key, value in _facts().items():
                store.put(key, value)

        def publish_pipeline(_ctx, store):  # noqa: ANN001
            store.put("pipeline_triage_payload", {"priority_assets": ["DB-1303"]})

        def publish_competition(_ctx, store):  # noqa: ANN001
            store.put("competition_triage_payload", {"crowding_signal": "crowded"})

        graph.add(DeterministicAgent("publish_research_facts", publish))
        graph.add(
            DeterministicAgent(
                "pipeline_triage_llm_agent",
                publish_pipeline,
                depends_on=("publish_research_facts",),
            )
        )
        graph.add(
            DeterministicAgent(
                "competition_triage_llm_agent",
                publish_competition,
                depends_on=("publish_research_facts",),
            )
        )
        graph.add(
            StrategicEconomicsLLMAgent(
                llm_client=client,
                depends_on=(
                    "pipeline_triage_llm_agent",
                    "competition_triage_llm_agent",
                ),
            )
        )

        result = graph.run(_ctx())

        step = result.step("strategic_economics_llm_agent")
        self.assertIsNotNone(step)
        assert step is not None
        self.assertIsNone(step.error)
        self.assertIn("strategic_economics_payload", result.facts)


if __name__ == "__main__":
    unittest.main()
