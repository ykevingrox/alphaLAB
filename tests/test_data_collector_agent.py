from __future__ import annotations

import json
import unittest

from biotech_alpha.agent_runtime import AgentGraph, DeterministicAgent, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    DATA_COLLECTOR_PROMPT,
    DataCollectorLLMAgent,
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
        "input_validation_payload": {
            "pipeline_assets": {"errors": [], "warnings": [], "asset_count": 3},
            "financials": {"errors": [], "warnings": ["cash source stale"]},
        },
        "input_warnings": ["cash source stale"],
        "pipeline_snapshot": {"assets": [{"name": "DB-1303", "phase": "Phase 3"}]},
        "financials_snapshot": {
            "financial_snapshot": {
                "as_of_date": "2025-12-31",
                "source": "annual_results",
            }
        },
        "valuation_snapshot": {"market_cap": 54000000000, "currency": "HKD"},
        "competition_snapshot": {"competitor_assets": [{"company": "AstraZeneca"}]},
        "catalyst_calendar_payload": {"count": 1, "catalysts": []},
        "target_price_snapshot": {"base_target_price": 42.0, "currency": "HKD"},
        "macro_context": {"source_publication_dates": ["2026-03-25"]},
        "source_text_excerpt": {
            "title": "Annual results",
            "url": "https://example.test/annual",
            "publication_date": "2026-03-25",
            "excerpt": "Pipeline and BD discussion.",
        },
        "fallback_context": {"source_documents": [{"title": "Annual results"}]},
    }


def _happy_payload() -> dict:
    return {
        "run_verdict": "needs_more_evidence",
        "domain_verdicts": [
            {
                "domain": "pipeline",
                "verdict": "publish_ready",
                "evidence_quality": "medium",
                "stale_sources": [],
                "missing_evidence": [],
                "rationale": "Pipeline assets have source-backed rows.",
            },
            {
                "domain": "financials",
                "verdict": "needs_more_evidence",
                "evidence_quality": "low",
                "stale_sources": ["cash source stale"],
                "missing_evidence": ["Need latest interim cash balance."],
                "rationale": "Financial warning indicates stale cash source.",
            },
        ],
        "priority_gaps": ["Need latest interim cash balance."],
        "confidence": 0.63,
        "needs_human_review": True,
    }


class DataCollectorAgentTest(unittest.TestCase):
    def test_produces_domain_verdict_payload(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=480,
            completion_tokens=140,
        )
        agent = DataCollectorLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNone(step.error)
        self.assertEqual(step.outputs["data_collector_payload"], _happy_payload())
        self.assertEqual(step.finding.agent_name, "data_collector_llm_agent")
        self.assertIn("needs_more_evidence", step.finding.summary)
        self.assertAlmostEqual(step.finding.confidence, 0.63)
        self.assertIn("[run_verdict] needs_more_evidence", step.finding.risks)
        self.assertTrue(
            any(r.startswith("[missing_evidence]") for r in step.finding.risks)
        )

    def test_missing_inputs_warns_but_runs(self) -> None:
        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    **_happy_payload(),
                    "run_verdict": "insufficient_data",
                    "domain_verdicts": [
                        {
                            **_happy_payload()["domain_verdicts"][0],
                            "verdict": "insufficient_data",
                            "evidence_quality": "insufficient_data",
                        }
                    ],
                    "confidence": 0.2,
                }
            )
        )
        agent = DataCollectorLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({}))

        self.assertIsNone(step.error)
        self.assertIn("fallback_context:input_validation_payload", step.warnings)
        self.assertIn("fallback_context:source_text_excerpt", step.warnings)

    def test_schema_violation_records_error(self) -> None:
        client = FakeLLMClient()
        client.queue('{"data_collector": {"run_verdict": "publish_ready"}}')
        agent = DataCollectorLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")

    def test_prompt_schema_rejects_unapproved_verdict(self) -> None:
        from biotech_alpha.llm.schema import validate_json_schema

        bad = {**_happy_payload(), "run_verdict": "approved"}
        with self.assertRaises(Exception):
            validate_json_schema(bad, DATA_COLLECTOR_PROMPT.schema)


class DataCollectorGraphTest(unittest.TestCase):
    def test_runs_after_research_facts(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps(_happy_payload()))
        graph = AgentGraph()

        def publish(_ctx, store):  # noqa: ANN001
            for key, value in _facts().items():
                store.put(key, value)

        graph.add(DeterministicAgent("publish_research_facts", publish))
        graph.add(
            DataCollectorLLMAgent(
                llm_client=client,
                depends_on=("publish_research_facts",),
            )
        )

        result = graph.run(_ctx())

        step = result.step("data_collector_llm_agent")
        self.assertIsNotNone(step)
        assert step is not None
        self.assertIsNone(step.error)
        self.assertIn("data_collector_payload", result.facts)


if __name__ == "__main__":
    unittest.main()
