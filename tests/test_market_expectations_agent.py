from __future__ import annotations

import json
import unittest

from biotech_alpha.agent_runtime import AgentGraph, DeterministicAgent, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    MARKET_EXPECTATIONS_PROMPT,
    MarketExpectationsLLMAgent,
)
from biotech_alpha.llm import FakeLLMClient


def _ctx() -> AgentContext:
    return AgentContext(
        company="DualityBio",
        ticker="09606.HK",
        market="HK",
        as_of_date="2026-04-27",
    )


def _valuation_snapshot() -> dict:
    return {
        "market_cap": 54000000000,
        "share_price": 54.0,
        "shares_outstanding": 1000000000,
        "cash": 2500000000,
        "debt": 100000000,
        "currency": "HKD",
    }


def _committee_payload() -> dict:
    return {
        "summary": "Committee separates conservative floor from market value.",
        "method": "sotp_committee",
        "currency": "HKD",
        "valuation_range": {"bear": 8000000000, "base": 16000000000, "bull": 32000000000},
        "conservative_rnpv_floor": {
            "bear": 6000000000,
            "base": 14000000000,
            "bull": 28000000000,
        },
        "market_implied_value": {
            "market_cap": 54000000000,
            "premium_to_conservative_floor": 2.8571,
        },
        "scenario_repricing_range": {
            "bear": 8000000000,
            "base": 16000000000,
            "bull": 32000000000,
        },
        "needs_human_review": True,
    }


def _happy_payload() -> dict:
    return {
        "market_implied_assumptions": [
            "Market value appears to require BD economics or platform reuse beyond conservative rNPV."
        ],
        "valuation_band_context": "extended_band",
        "rnpv_gap_explanation": (
            "The gap versus conservative rNPV may reflect strategic optionality, "
            "but the current inputs do not prove those economics."
        ),
        "expectation_risk_flags": [
            "If partner economics disappoint, the premium to conservative floor can compress."
        ],
        "evidence_gaps": [
            "Need disclosed BD economics and evidence for platform repeatability."
        ],
        "confidence": 0.58,
        "needs_human_review": True,
    }


class MarketExpectationsAgentTest(unittest.TestCase):
    def test_produces_market_expectations_payload(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=500,
            completion_tokens=130,
        )
        agent = MarketExpectationsLLMAgent(llm_client=client)

        step = agent.run(
            _ctx(),
            FactStore(
                {
                    "valuation_snapshot": _valuation_snapshot(),
                    "valuation_committee_payload": _committee_payload(),
                    "technical_feature_payload": {
                        "technical_state": "constructive"
                    },
                    "market_regime_timing_payload": {
                        "timing_view": "neutral"
                    },
                }
            ),
        )

        self.assertIsNone(step.error)
        self.assertEqual(
            step.outputs["market_expectations_payload"], _happy_payload()
        )
        self.assertEqual(
            step.finding.agent_name, "market_expectations_llm_agent"
        )
        self.assertIn("Market expectations: extended_band", step.finding.summary)
        self.assertAlmostEqual(step.finding.confidence, 0.58)
        self.assertIn(
            "[valuation_band_context] extended_band",
            step.finding.risks,
        )
        self.assertTrue(
            any(r.startswith("[evidence_gap]") for r in step.finding.risks)
        )

    def test_missing_valuation_inputs_warns_but_runs(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps({**_happy_payload(), "valuation_band_context": "unknown"}))
        agent = MarketExpectationsLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({}))

        self.assertIsNone(step.error)
        self.assertIn("fallback_context:valuation_snapshot", step.warnings)
        self.assertIn("fallback_context:valuation_committee_payload", step.warnings)

    def test_schema_violation_records_error(self) -> None:
        client = FakeLLMClient()
        client.queue('{"market_expectations": {"valuation_band_context": "mid_band"}}')
        agent = MarketExpectationsLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({}))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")

    def test_prompt_schema_rejects_trading_or_unknown_band_label(self) -> None:
        from biotech_alpha.llm.schema import validate_json_schema

        bad = {**_happy_payload(), "valuation_band_context": "buy_zone"}
        with self.assertRaises(Exception):
            validate_json_schema(bad, MARKET_EXPECTATIONS_PROMPT.schema)


class MarketExpectationsGraphTest(unittest.TestCase):
    def test_runs_after_valuation_committee_and_timing_payloads(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps(_happy_payload()))
        graph = AgentGraph()

        def publish(_ctx, store):  # noqa: ANN001
            store.put("valuation_snapshot", _valuation_snapshot())

        def publish_committee(_ctx, store):  # noqa: ANN001
            store.put("valuation_committee_payload", _committee_payload())

        def publish_timing(_ctx, store):  # noqa: ANN001
            store.put(
                "market_regime_timing_payload",
                {"timing_view": "neutral", "technical_state": "constructive"},
            )

        graph.add(DeterministicAgent("publish_research_facts", publish))
        graph.add(
            DeterministicAgent(
                "valuation_committee_llm_agent",
                publish_committee,
                depends_on=("publish_research_facts",),
            )
        )
        graph.add(
            DeterministicAgent(
                "market_regime_timing_llm_agent",
                publish_timing,
                depends_on=("publish_research_facts",),
            )
        )
        graph.add(
            MarketExpectationsLLMAgent(
                llm_client=client,
                depends_on=(
                    "valuation_committee_llm_agent",
                    "market_regime_timing_llm_agent",
                ),
            )
        )

        result = graph.run(_ctx())

        step = result.step("market_expectations_llm_agent")
        self.assertIsNotNone(step)
        assert step is not None
        self.assertIsNone(step.error)
        self.assertIn("market_expectations_payload", result.facts)


if __name__ == "__main__":
    unittest.main()
