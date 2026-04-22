"""Unit tests for the LLM adapter layer."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from biotech_alpha.llm import (
    BudgetEnforcingLLMClient,
    FakeLLMClient,
    LLMBudgetError,
    LLMConfig,
    LLMConfigError,
    LLMTraceRecorder,
    SchemaError,
    StructuredPrompt,
    validate_json_schema,
)
from biotech_alpha.llm.trace import TraceEntry, hash_prompt


class LLMConfigFromEnvTest(unittest.TestCase):
    def test_uses_explicit_environ_values(self) -> None:
        env = {
            "BIOTECH_ALPHA_LLM_API_KEY": "k",
            "BIOTECH_ALPHA_LLM_BASE_URL": "https://example.com/v1",
            "BIOTECH_ALPHA_LLM_MODEL": "my-model",
            "BIOTECH_ALPHA_LLM_REQUEST_TIMEOUT": "15",
            "BIOTECH_ALPHA_LLM_CALL_BUDGET": "3",
            "BIOTECH_ALPHA_LLM_TRACE_DIR": "tmp/traces",
        }

        config = LLMConfig.from_env(env)

        self.assertEqual(config.api_key, "k")
        self.assertEqual(config.base_url, "https://example.com/v1")
        self.assertEqual(config.model, "my-model")
        self.assertEqual(config.request_timeout_seconds, 15.0)
        self.assertEqual(config.call_budget, 3)
        self.assertIsNone(config.per_agent_call_budget)
        self.assertEqual(config.trace_dir, Path("tmp/traces"))

    def test_parses_per_agent_call_budget(self) -> None:
        env = {
            "BIOTECH_ALPHA_LLM_API_KEY": "k",
            "BIOTECH_ALPHA_LLM_CALL_BUDGET": "10",
            "BIOTECH_ALPHA_LLM_PER_AGENT_CALL_BUDGET": "2",
        }

        config = LLMConfig.from_env(env)

        self.assertEqual(config.call_budget, 10)
        self.assertEqual(config.per_agent_call_budget, 2)

    def test_rejects_non_positive_per_agent_budget(self) -> None:
        for bad in ("0", "-3", "abc"):
            with self.assertRaises(LLMConfigError):
                LLMConfig.from_env(
                    {
                        "BIOTECH_ALPHA_LLM_API_KEY": "k",
                        "BIOTECH_ALPHA_LLM_PER_AGENT_CALL_BUDGET": bad,
                    }
                )

    def test_missing_api_key_is_fatal_by_default(self) -> None:
        with self.assertRaises(LLMConfigError):
            LLMConfig.from_env({})

    def test_missing_api_key_allowed_when_not_required(self) -> None:
        config = LLMConfig.from_env({}, require_api_key=False)
        self.assertEqual(config.api_key, "")
        self.assertEqual(
            config.base_url,
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.assertEqual(config.model, "qwen3.6-plus")
        self.assertFalse(config.enable_thinking)

    def test_falls_back_to_dashscope_api_key(self) -> None:
        env = {"DASHSCOPE_API_KEY": "sk-from-dashscope-env"}
        config = LLMConfig.from_env(env)
        self.assertEqual(config.api_key, "sk-from-dashscope-env")

    def test_biotech_alpha_key_wins_over_dashscope_key(self) -> None:
        env = {
            "BIOTECH_ALPHA_LLM_API_KEY": "primary",
            "DASHSCOPE_API_KEY": "secondary",
        }
        config = LLMConfig.from_env(env)
        self.assertEqual(config.api_key, "primary")

    def test_enable_thinking_parses_truthy_values(self) -> None:
        for value in ("1", "true", "YES", "on"):
            config = LLMConfig.from_env(
                {
                    "BIOTECH_ALPHA_LLM_API_KEY": "k",
                    "BIOTECH_ALPHA_LLM_ENABLE_THINKING": value,
                }
            )
            self.assertTrue(
                config.enable_thinking,
                f"expected truthy for {value!r}",
            )
        for value in ("0", "false", "no", "off"):
            config = LLMConfig.from_env(
                {
                    "BIOTECH_ALPHA_LLM_API_KEY": "k",
                    "BIOTECH_ALPHA_LLM_ENABLE_THINKING": value,
                }
            )
            self.assertFalse(
                config.enable_thinking,
                f"expected falsy for {value!r}",
            )


class JSONSchemaValidatorTest(unittest.TestCase):
    def test_happy_path_passes(self) -> None:
        schema = {
            "type": "object",
            "required": ["summary", "risks"],
            "properties": {
                "summary": {"type": "string", "min_length": 3},
                "risks": {
                    "type": "array",
                    "min_items": 1,
                    "items": {
                        "type": "object",
                        "required": ["description", "severity"],
                        "properties": {
                            "description": {"type": "string"},
                            "severity": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                        },
                    },
                },
            },
        }
        payload = {
            "summary": "okay",
            "risks": [{"description": "d", "severity": "high"}],
        }
        validate_json_schema(payload, schema)

    def test_missing_required_key_raises(self) -> None:
        schema = {"type": "object", "required": ["x"]}
        with self.assertRaises(SchemaError):
            validate_json_schema({}, schema)

    def test_enum_violation_raises(self) -> None:
        schema = {"type": "string", "enum": ["a", "b"]}
        with self.assertRaises(SchemaError):
            validate_json_schema("c", schema)

    def test_type_mismatch_raises(self) -> None:
        schema = {"type": "array"}
        with self.assertRaises(SchemaError):
            validate_json_schema({"not": "a list"}, schema)


class StructuredPromptTest(unittest.TestCase):
    def _prompt(self) -> StructuredPrompt:
        return StructuredPrompt(
            name="demo",
            system="you are a test",
            user_template="Hello, ${name}! Tell me about $topic.",
            schema={
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
            },
        )

    def test_render_substitutes_variables(self) -> None:
        system, user = self._prompt().render(
            {"name": "Jia", "topic": "biotech"}
        )
        self.assertEqual(system, "you are a test")
        self.assertIn("Hello, Jia!", user)
        self.assertIn("biotech", user)
        self.assertIn("single JSON object", user)

    def test_parse_accepts_plain_json(self) -> None:
        parsed = self._prompt().parse_response('{"summary": "ok"}')
        self.assertEqual(parsed["summary"], "ok")

    def test_parse_accepts_fenced_json(self) -> None:
        response = "Here is my answer:\n```json\n{\"summary\": \"ok\"}\n```"
        parsed = self._prompt().parse_response(response)
        self.assertEqual(parsed["summary"], "ok")

    def test_parse_rejects_missing_required(self) -> None:
        with self.assertRaises(SchemaError):
            self._prompt().parse_response('{"wrong": "key"}')


class LLMTraceRecorderTest(unittest.TestCase):
    def test_flush_writes_jsonl(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "trace.jsonl"
            recorder = LLMTraceRecorder(path=path)
            recorder.record(
                TraceEntry(
                    timestamp="2026-04-22T00:00:00Z",
                    agent_name="a",
                    model="m",
                    prompt_hash=hash_prompt("p"),
                    prompt_chars=1,
                    response_chars=2,
                    latency_ms=1.5,
                    prompt_tokens=3,
                    completion_tokens=4,
                    total_tokens=7,
                    finish_reason="stop",
                    retries=0,
                    ok=True,
                )
            )
            written = recorder.flush()

            self.assertEqual(written, path)
            self.assertTrue(path.exists())
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["agent_name"], "a")
            self.assertEqual(record["total_tokens"], 7)

    def test_cost_summary_aggregates_entries(self) -> None:
        recorder = LLMTraceRecorder()
        for tokens in (10, 20):
            recorder.record(
                TraceEntry(
                    timestamp="t",
                    agent_name="a",
                    model="m",
                    prompt_hash="h",
                    prompt_chars=1,
                    response_chars=1,
                    latency_ms=2.0,
                    prompt_tokens=tokens,
                    completion_tokens=tokens,
                    total_tokens=tokens * 2,
                    finish_reason="stop",
                    retries=0,
                    ok=True,
                )
            )
        summary = recorder.cost_summary()

        self.assertEqual(summary["calls"], 2)
        self.assertEqual(summary["prompt_tokens"], 30)
        self.assertEqual(summary["completion_tokens"], 30)
        self.assertEqual(summary["total_tokens"], 60)
        self.assertAlmostEqual(summary["total_latency_ms"], 4.0)


class FakeLLMClientTest(unittest.TestCase):
    def test_returns_queued_responses_in_order(self) -> None:
        client = FakeLLMClient()
        client.queue('{"summary": "a"}', prompt_tokens=5, completion_tokens=3)
        client.queue('{"summary": "b"}', prompt_tokens=7, completion_tokens=2)

        first = client.complete(system="s", user="u", agent_name="t")
        second = client.complete(system="s", user="u", agent_name="t")

        self.assertEqual(json.loads(first.response_text)["summary"], "a")
        self.assertEqual(json.loads(second.response_text)["summary"], "b")
        self.assertEqual(first.prompt_tokens, 5)
        self.assertEqual(second.prompt_tokens, 7)
        self.assertEqual(len(client.trace.entries), 2)

    def test_default_response_reused(self) -> None:
        client = FakeLLMClient(default_response='{"summary": "x"}')
        for _ in range(3):
            call = client.complete(system="s", user="u", agent_name="t")
            self.assertIn("summary", call.response_text)

    def test_queue_error_raises_and_records_failure(self) -> None:
        client = FakeLLMClient()
        client.queue(raise_error=RuntimeError("boom"))

        with self.assertRaises(RuntimeError):
            client.complete(system="s", user="u", agent_name="t")

        self.assertEqual(len(client.trace.entries), 1)
        self.assertFalse(client.trace.entries[0].ok)


class BudgetEnforcingLLMClientTest(unittest.TestCase):
    """Unit tests for the provider-agnostic budget enforcement wrapper."""

    def _wrap(
        self,
        inner: FakeLLMClient,
        *,
        total_budget: int | None = None,
        per_agent_budget: int | None = None,
    ) -> BudgetEnforcingLLMClient:
        return BudgetEnforcingLLMClient(
            inner,
            total_budget=total_budget,
            per_agent_budget=per_agent_budget,
        )

    def test_passthrough_without_budget(self) -> None:
        inner = FakeLLMClient(default_response='{"ok": true}')
        client = self._wrap(inner)

        for _ in range(5):
            client.complete(system="s", user="u", agent_name="a")

        self.assertEqual(client.calls_used, 5)
        self.assertEqual(client.calls_used_for("a"), 5)
        self.assertEqual(len(inner.calls), 5)

    def test_total_budget_blocks_extra_calls(self) -> None:
        inner = FakeLLMClient(default_response='{"ok": true}')
        client = self._wrap(inner, total_budget=2)

        client.complete(system="s", user="u", agent_name="a")
        client.complete(system="s", user="u", agent_name="b")

        with self.assertRaises(LLMBudgetError):
            client.complete(system="s", user="u", agent_name="c")
        self.assertEqual(client.calls_used, 2)
        self.assertEqual(len(inner.calls), 2)

    def test_per_agent_budget_isolates_agents(self) -> None:
        inner = FakeLLMClient(default_response='{"ok": true}')
        client = self._wrap(inner, per_agent_budget=1)

        client.complete(system="s", user="u", agent_name="triage")
        client.complete(system="s", user="u", agent_name="skeptic")

        with self.assertRaises(LLMBudgetError) as ctx:
            client.complete(system="s", user="u", agent_name="triage")
        self.assertIn("triage", str(ctx.exception))
        self.assertEqual(client.calls_used_for("triage"), 1)
        self.assertEqual(client.calls_used_for("skeptic"), 1)

    def test_refusal_does_not_consume_inner_call(self) -> None:
        inner = FakeLLMClient()
        inner.queue('{"ok": true}')
        client = self._wrap(inner, per_agent_budget=1)

        client.complete(system="s", user="u", agent_name="skeptic")
        with self.assertRaises(LLMBudgetError):
            client.complete(system="s", user="u", agent_name="skeptic")

        self.assertEqual(len(inner.calls), 1)

    def test_rejects_non_positive_budgets(self) -> None:
        inner = FakeLLMClient(default_response='{"ok": true}')
        with self.assertRaises(ValueError):
            BudgetEnforcingLLMClient(inner, total_budget=0)
        with self.assertRaises(ValueError):
            BudgetEnforcingLLMClient(inner, per_agent_budget=-1)

    def test_llm_budget_error_is_a_llm_error(self) -> None:
        from biotech_alpha.llm import LLMError

        self.assertTrue(issubclass(LLMBudgetError, LLMError))


if __name__ == "__main__":
    unittest.main()
