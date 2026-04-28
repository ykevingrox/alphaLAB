from __future__ import annotations

import json
import unittest

from biotech_alpha.agent_runtime import AgentGraph, DeterministicAgent, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.agents_llm import (
    REPORT_SYNTHESIZER_PROMPT,
    ReportSynthesizerLLMAgent,
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
            "deterministic_summary": "确定性摘要保持不变。",
            "bull_case": ["pipeline breadth"],
            "bear_case": ["execution risk"],
        },
        "data_collector_payload": {"run_verdict": "needs_more_evidence"},
        "market_expectations_payload": {"valuation_band_context": "unknown"},
        "valuation_committee_payload": {
            "market_implied_value": {"market_cap": 54000000000}
        },
        "scorecard_summary": {"watchlist_score": 68},
    }


def _happy_payload() -> dict:
    return {
        "executive_verdict_paragraph": (
            "综合现有证据，公司仍适合放在观察名单；当前结论依赖后续数据和"
            "估值口径复核，不应被解读为交易指令。"
        ),
        "section_transitions": {
            "investment_thesis": "投资主线先看管线质量，再看证据缺口。",
            "core_assets": "核心资产部分只承接已披露事实。",
            "catalysts": "催化剂部分强调事件质量而非新增估值数字。",
            "competition": "竞争格局用于校验差异化假设。",
            "financials": "财务部分聚焦现金与融资弹性。",
            "valuation": "估值部分保留确定性口径，不新增价格判断。",
            "risks": "风险部分列出可以证伪当前观察名单判断的因素。",
        },
        "synthesis_warnings": ["上游估值与市场预期仍需校准。"],
        "evidence_gaps": ["缺少完整BD经济条款。"],
        "confidence": 0.59,
        "needs_human_review": True,
    }


class ReportSynthesizerAgentTest(unittest.TestCase):
    def test_produces_report_synthesis_payload(self) -> None:
        client = FakeLLMClient(model="fake-qwen")
        client.queue(
            json.dumps(_happy_payload()),
            prompt_tokens=520,
            completion_tokens=180,
        )
        agent = ReportSynthesizerLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNone(step.error)
        self.assertEqual(
            step.outputs["report_synthesizer_payload"], _happy_payload()
        )
        self.assertEqual(
            step.finding.agent_name, "report_synthesizer_llm_agent"
        )
        self.assertIn("观察名单", step.finding.summary)
        self.assertAlmostEqual(step.finding.confidence, 0.59)
        self.assertTrue(
            any(r.startswith("[synthesis_warning]") for r in step.finding.risks)
        )

    def test_missing_scaffold_warns_but_runs(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps(_happy_payload()))
        agent = ReportSynthesizerLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore({}))

        self.assertIsNone(step.error)
        self.assertIn("fallback_context:memo_scaffold_payload", step.warnings)

    def test_schema_violation_records_error(self) -> None:
        client = FakeLLMClient()
        client.queue('{"report_synthesizer": {"confidence": 0.2}}')
        agent = ReportSynthesizerLLMAgent(llm_client=client)

        step = agent.run(_ctx(), FactStore(_facts()))

        self.assertIsNotNone(step.error)
        self.assertIn("schema", step.error or "")

    def test_prompt_schema_rejects_missing_required_output(self) -> None:
        from biotech_alpha.llm.schema import validate_json_schema

        bad = {**_happy_payload()}
        bad.pop("executive_verdict_paragraph")
        with self.assertRaises(Exception):
            validate_json_schema(bad, REPORT_SYNTHESIZER_PROMPT.schema)


class ReportSynthesizerGraphTest(unittest.TestCase):
    def test_runs_after_data_collector_payload(self) -> None:
        client = FakeLLMClient()
        client.queue(json.dumps(_happy_payload()))
        graph = AgentGraph()

        def publish(_ctx, store):  # noqa: ANN001
            for key, value in _facts().items():
                store.put(key, value)

        def publish_data_collector(_ctx, store):  # noqa: ANN001
            store.put("data_collector_payload", {"run_verdict": "publish_ready"})

        graph.add(DeterministicAgent("publish_research_facts", publish))
        graph.add(
            DeterministicAgent(
                "data_collector_llm_agent",
                publish_data_collector,
                depends_on=("publish_research_facts",),
            )
        )
        graph.add(
            ReportSynthesizerLLMAgent(
                llm_client=client,
                depends_on=("data_collector_llm_agent",),
            )
        )

        result = graph.run(_ctx())

        step = result.step("report_synthesizer_llm_agent")
        self.assertIsNotNone(step)
        assert step is not None
        self.assertIsNone(step.error)
        self.assertIn("report_synthesizer_payload", result.facts)


if __name__ == "__main__":
    unittest.main()
