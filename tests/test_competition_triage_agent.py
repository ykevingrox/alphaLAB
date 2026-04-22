"""Tests for the CompetitionTriageLLMAgent."""

from __future__ import annotations

import json
import unittest

from biotech_alpha.agent_runtime import FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    COMPETITION_TRIAGE_PROMPT,
    CompetitionTriageLLMAgent,
)
from biotech_alpha.llm import FakeLLMClient


def _ctx() -> AgentContext:
    return AgentContext(
        company="DualityBio",
        ticker="09606.HK",
        market="HK",
        as_of_date="2026-04-22",
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
                }
            ]
        },
        "input_warnings": [],
        "competition_snapshot": {
            "competitor_assets": [
                {
                    "company": "AstraZeneca",
                    "asset_name": "Trastuzumab deruxtecan",
                    "target": "HER2",
                    "indication": "breast cancer",
                    "phase": "Approved",
                }
            ],
            "competitive_matches": [
                {
                    "asset_name": "DB-1303",
                    "competitor_company": "AstraZeneca",
                    "competitor_asset": "Trastuzumab deruxtecan",
                    "match_scope": "target+indication",
                    "confidence": 0.85,
                }
            ],
        },
    }


class CompetitionTriageHappyPathTest(unittest.TestCase):
    def test_produces_structured_finding(self) -> None:
        payload = {
            "crowding_signal": "crowded",
            "summary": "HER2 breast-cancer space appears crowded.",
            "confidence": 0.62,
            "findings": [
                {
                    "severity": "high",
                    "description": "Multiple late-stage comparators map to DB-1303.",
                    "asset_name": "DB-1303",
                    "match_scope": "target+indication",
                }
            ],
        }
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(payload),
            prompt_tokens=350,
            completion_tokens=120,
        )
        agent = CompetitionTriageLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNone(step.error)
        self.assertIsNotNone(step.finding)
        self.assertAlmostEqual(step.finding.confidence, 0.62)
        self.assertTrue(
            any(
                risk == "[crowding_signal] crowded"
                for risk in step.finding.risks
            ),
            msg=str(step.finding.risks),
        )
        self.assertIn("competition_triage_payload", step.outputs)

    def test_skips_when_competitor_assets_missing(self) -> None:
        client = FakeLLMClient()
        agent = CompetitionTriageLLMAgent(llm_client=client)
        store = FactStore(
            {
                "competition_snapshot": {
                    "competitor_assets": [],
                    "competitive_matches": [],
                }
            }
        )

        step = agent.run(_ctx(), store)

        self.assertTrue(step.skipped)
        self.assertIn("no competitor_assets", step.error or "")
        self.assertEqual(client.calls, [])

    def test_schema_violation_records_error(self) -> None:
        client = FakeLLMClient()
        client.queue('{"crowding_signal": "crowded"}')
        agent = CompetitionTriageLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")


class CompetitionTriagePromptShapeTest(unittest.TestCase):
    def test_prompt_blocks_unsupported_ownership_claims(self) -> None:
        agent = CompetitionTriageLLMAgent(llm_client=FakeLLMClient())
        system, user = COMPETITION_TRIAGE_PROMPT.render(
            agent._collect_variables(_ctx(), FactStore(_facts()))
        )

        self.assertEqual(agent.max_tokens, 1800)
        self.assertIn("ownership corrections", system)
        self.assertIn("requires verification", system)
        self.assertIn("unless the provided facts say so", system)
        self.assertIn("Treat `to_verify` competitor fields", user)

    def test_prompt_rejects_bad_crowding_enum(self) -> None:
        from biotech_alpha.llm.schema import validate_json_schema

        bad = {
            "crowding_signal": "bullish",
            "summary": "looks fine",
            "findings": [],
        }
        with self.assertRaises(Exception):
            validate_json_schema(bad, COMPETITION_TRIAGE_PROMPT.schema)


if __name__ == "__main__":
    unittest.main()
