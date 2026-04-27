from __future__ import annotations

import json
import unittest

from biotech_alpha.agent_runtime import AgentGraph, DeterministicAgent, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    MARKET_REGIME_TIMING_PROMPT,
    MacroContextLLMAgent,
    MarketRegimeTimingLLMAgent,
)
from biotech_alpha.llm import FakeLLMClient


def _ctx() -> AgentContext:
    return AgentContext(
        company="DualityBio",
        ticker="09606.HK",
        market="HK",
        as_of_date="2026-04-27",
    )


def _macro_context() -> dict:
    return {
        "market": "HK",
        "sector": "biotech",
        "ticker": "09606.HK",
        "company": "DualityBio",
        "live_signals": {
            "hsi": {"trend_30d_pct": 2.1},
            "hsbio": {"trend_30d_pct": 4.2},
        },
        "known_unknowns": ["recent sector-relevant news titles"],
    }


def _technical_payload() -> dict:
    return {
        "symbol": "9606.HK",
        "provider": "unit-test",
        "window": {"row_count": 260},
        "returns": {"1m_pct": 8.1, "3m_pct": 14.0, "6m_pct": 5.5},
        "drawdown_from_52w_high_pct": -8.0,
        "moving_average_state": {"state": "uptrend"},
        "volatility_state": {"state": "normal"},
        "relative_strength": {
            "benchmark_symbol": "^HSI",
            "state": "outperforming",
            "3m_spread_pct": 7.0,
        },
        "technical_state": "constructive",
        "warnings": (),
        "guidance_type": "research_only",
    }


def _happy_payload() -> dict:
    return {
        "timing_view": "favorable",
        "horizon": "3-6 months",
        "macro_regime": "transition",
        "technical_state": "constructive",
        "sentiment_state": "unknown",
        "key_triggers": [
            "3m return and relative strength remain positive",
            "HSBIO trend stays constructive",
        ],
        "invalidation_signals": [
            "moving_average_state flips to downtrend",
        ],
        "confidence": 0.62,
        "needs_human_review": True,
    }


class MarketRegimeTimingAgentTest(unittest.TestCase):
    def test_produces_research_only_timing_payload(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=400,
            completion_tokens=120,
        )
        agent = MarketRegimeTimingLLMAgent(llm_client=client)

        step = agent.run(
            _ctx(),
            FactStore(
                {
                    "macro_context": _macro_context(),
                    "technical_feature_payload": _technical_payload(),
                }
            ),
        )

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertEqual(
            step.outputs["market_regime_timing_payload"], _happy_payload()
        )
        self.assertEqual(
            step.finding.agent_name, "market_regime_timing_llm_agent"
        )
        self.assertIn("Timing view: favorable", step.finding.summary)
        self.assertAlmostEqual(step.finding.confidence, 0.62)
        self.assertEqual(step.finding.needs_human_review, True)
        self.assertFalse(
            any(r.startswith("[timing_view]") for r in step.finding.risks)
        )

    def test_fragile_timing_view_surfaces_risk_tags(self) -> None:
        payload = {
            **_happy_payload(),
            "timing_view": "fragile",
            "technical_state": "weak",
            "confidence": 0.4,
        }
        client = FakeLLMClient()
        client.queue(json.dumps(payload))
        agent = MarketRegimeTimingLLMAgent(llm_client=client)

        step = agent.run(
            _ctx(),
            FactStore({"technical_feature_payload": _technical_payload()}),
        )

        self.assertIsNone(step.error)
        self.assertIn("[timing_view] fragile", step.finding.risks)
        self.assertTrue(
            any(r.startswith("[invalidation]") for r in step.finding.risks)
        )

    def test_missing_technical_payload_warns_but_runs(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps({**_happy_payload(), "technical_state": "unknown"}))
        agent = MarketRegimeTimingLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({"macro_context": _macro_context()}))

        self.assertIsNone(step.error)
        self.assertIn("fallback_context:technical_feature_payload", step.warnings)

    def test_schema_violation_records_error(self) -> None:
        client = FakeLLMClient()
        client.queue('{"timing_view": "favorable"}')
        agent = MarketRegimeTimingLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({}))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")

    def test_prompt_schema_rejects_trading_labels(self) -> None:
        from biotech_alpha.llm.schema import validate_json_schema

        bad = {**_happy_payload(), "timing_view": "buy_now"}
        with self.assertRaises(Exception):
            validate_json_schema(bad, MARKET_REGIME_TIMING_PROMPT.schema)


class MarketRegimeTimingGraphTest(unittest.TestCase):
    def test_runs_after_macro_context_when_requested(self) -> None:
        client = FakeLLMClient()
        client.queue(
            json.dumps(
                {
                    "macro_regime": "transition",
                    "summary": "HK biotech macro is mixed but improving.",
                    "sector_drivers": ["HSBIO trend is positive"],
                    "sector_headwinds": ["news feed missing"],
                    "confidence": 0.5,
                }
            )
        )
        client.queue(json.dumps(_happy_payload()))
        graph = AgentGraph()

        def publish(_ctx, store):  # noqa: ANN001
            store.put("macro_context", _macro_context())
            store.put("technical_feature_payload", _technical_payload())

        graph.add(DeterministicAgent("publish_research_facts", publish))
        graph.add(
            MacroContextLLMAgent(
                llm_client=client,
                depends_on=("publish_research_facts",),
            )
        )
        graph.add(
            MarketRegimeTimingLLMAgent(
                llm_client=client,
                depends_on=("macro_context_llm_agent",),
            )
        )

        result = graph.run(_ctx())

        self.assertIsNotNone(result.step("macro_context_llm_agent"))
        timing_step = result.step("market_regime_timing_llm_agent")
        self.assertIsNotNone(timing_step)
        assert timing_step is not None
        self.assertIsNone(timing_step.error)
        self.assertIn("market_regime_timing_payload", result.facts)


if __name__ == "__main__":
    unittest.main()
