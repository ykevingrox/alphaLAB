"""Unit tests for the LLM adapter layer."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from biotech_alpha.llm import (
    AnthropicLLMClient,
    BudgetEnforcingLLMClient,
    FakeLLMClient,
    LLMBudgetError,
    LLMConfig,
    LLMConfigError,
    LLMTraceRecorder,
    OpenAICompatibleLLMClient,
    SchemaError,
    StructuredPrompt,
    validate_json_schema,
)
from biotech_alpha.llm.client import LLMError
from biotech_alpha.llm.trace import TraceEntry, hash_prompt


class LLMConfigFromEnvTest(unittest.TestCase):
    def test_loads_project_dotenv_when_environ_omitted(self) -> None:
        old_cwd = os.getcwd()
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {
                "BIOTECH_ALPHA_LLM_API_KEY": "shell-project-key",
                "DASHSCOPE_API_KEY": "shell-fallback-key",
            },
            clear=True,
        ):
            os.chdir(tmp)
            try:
                Path(".env").write_text(
                    "\n".join(
                        [
                            "BIOTECH_ALPHA_LLM_API_KEY=project-key",
                            "BIOTECH_ALPHA_LLM_BASE_URL=https://example.com/v1",
                            "BIOTECH_ALPHA_LLM_MODEL=qwen-test",
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

                config = LLMConfig.from_env()
            finally:
                os.chdir(old_cwd)

        self.assertEqual(config.api_key, "project-key")
        self.assertEqual(config.base_url, "https://example.com/v1")
        self.assertEqual(config.model, "qwen-test")

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

    def test_parses_per_agent_model_overrides(self) -> None:
        env = {
            "BIOTECH_ALPHA_LLM_API_KEY": "k",
            "BIOTECH_ALPHA_LLM_MODEL": "qwen3.5-plus",
            "BIOTECH_ALPHA_LLM_MODEL_REPORT_QUALITY": "qwen-max",
            "BIOTECH_ALPHA_LLM_MODEL_VALUATION_COMMITTEE": "qwen-plus",
        }

        config = LLMConfig.from_env(env)

        self.assertEqual(
            config.model_for_agent("report_quality"),
            "qwen-max",
        )
        self.assertEqual(
            config.model_for_agent("valuation-committee"),
            "qwen-plus",
        )
        self.assertEqual(
            config.model_for_agent("macro_context_llm_agent"),
            "qwen3.5-plus",
        )

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
        self.assertEqual(config.model, "qwen3.5-plus")
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

    def test_anthropic_provider_reads_anthropic_key(self) -> None:
        config = LLMConfig.from_env(
            {
                "BIOTECH_ALPHA_LLM_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "sk-ant",
            }
        )
        self.assertEqual(config.provider, "anthropic")
        self.assertEqual(config.api_key, "sk-ant")
        self.assertEqual(config.base_url, "https://api.anthropic.com")
        self.assertEqual(config.model, "claude-3-5-sonnet-latest")

    def test_anthropic_provider_requires_anthropic_key(self) -> None:
        with self.assertRaises(LLMConfigError):
            LLMConfig.from_env({"BIOTECH_ALPHA_LLM_PROVIDER": "anthropic"})

    def test_rejects_unknown_provider(self) -> None:
        with self.assertRaises(LLMConfigError):
            LLMConfig.from_env(
                {
                    "BIOTECH_ALPHA_LLM_PROVIDER": "foo",
                    "BIOTECH_ALPHA_LLM_API_KEY": "k",
                }
            )

    def test_require_api_key_false_allows_empty_anthropic_key(self) -> None:
        config = LLMConfig.from_env(
            {"BIOTECH_ALPHA_LLM_PROVIDER": "anthropic"},
            require_api_key=False,
        )
        self.assertEqual(config.provider, "anthropic")
        self.assertEqual(config.api_key, "")
        self.assertEqual(config.base_url, "https://api.anthropic.com")


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
        self.assertIn("you are a test", system)
        self.assertIn("请使用简体中文思考与输出", system)
        self.assertIn("Hello, Jia!", user)
        self.assertIn("biotech", user)
        self.assertIn("请用简体中文填写", user)
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


class _FakeOpenAIChoiceMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeOpenAIChoice:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = _FakeOpenAIChoiceMessage(content)
        self.finish_reason = finish_reason


class _FakeOpenAIUsage:
    def __init__(
        self,
        prompt_tokens: int = 11,
        completion_tokens: int = 7,
        total_tokens: int = 18,
    ) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.total_tokens = total_tokens


class _FakeOpenAIResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeOpenAIChoice(content)]
        self.usage = _FakeOpenAIUsage()

    def model_dump(self) -> dict:
        return {
            "choices": [{"message": {"content": self.choices[0].message.content}}],
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
            },
        }


class _FakeOpenAICompletions:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN003 - sdk-like signature
        self.calls.append(kwargs)
        return _FakeOpenAIResponse('{"ok": true}')


class _FakeOpenAIChat:
    def __init__(self) -> None:
        self.completions = _FakeOpenAICompletions()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.chat = _FakeOpenAIChat()


class _FakeOpenAIModule:
    class OpenAI:  # noqa: D106 - test-only fake
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            _ = kwargs
            self.chat = _FakeOpenAIChat()


class OpenAICompatibleLLMClientTest(unittest.TestCase):
    def test_complete_uses_per_agent_model_override(self) -> None:
        config = LLMConfig.from_env(
            {
                "BIOTECH_ALPHA_LLM_API_KEY": "k",
                "BIOTECH_ALPHA_LLM_MODEL": "qwen-default",
                "BIOTECH_ALPHA_LLM_MODEL_REPORT_QUALITY_AGENT": "qwen-max",
            }
        )
        client = OpenAICompatibleLLMClient(
            config,
            _openai_module=_FakeOpenAIModule(),
        )

        call = client.complete(
            system="s",
            user="u",
            agent_name="report_quality_agent",
        )

        self.assertEqual(call.model, "qwen-max")
        self.assertEqual(
            client._client.chat.completions.calls[0]["model"],  # type: ignore[attr-defined]
            "qwen-max",
        )


class _FakeAnthropicContentBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAnthropicUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeAnthropicResponse:
    def __init__(
        self,
        *,
        text: str,
        input_tokens: int = 111,
        output_tokens: int = 37,
        stop_reason: str = "end_turn",
    ) -> None:
        self.content = [_FakeAnthropicContentBlock(text)]
        self.usage = _FakeAnthropicUsage(input_tokens, output_tokens)
        self.stop_reason = stop_reason

    def model_dump(self) -> dict:
        return {
            "content": [{"text": self.content[0].text}],
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
            },
            "stop_reason": self.stop_reason,
        }


class _FakeAnthropicMessagesAPI:
    def __init__(self, queue: list[object]) -> None:
        self._queue = list(queue)
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN003 - sdk-like surface
        self.calls.append(kwargs)
        if not self._queue:
            raise RuntimeError("empty queue")
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeAnthropicClient:
    def __init__(self, queue: list[object]) -> None:
        self.messages = _FakeAnthropicMessagesAPI(queue)


class _FakeAnthropicModule:
    def __init__(self, queue: list[object]) -> None:
        self._queue = queue

    def Anthropic(self, **kwargs):  # noqa: ANN003 - sdk-like constructor
        _ = kwargs
        return _FakeAnthropicClient(self._queue)


class AnthropicLLMClientTest(unittest.TestCase):
    def _config(self) -> LLMConfig:
        return LLMConfig.from_env(
            {
                "BIOTECH_ALPHA_LLM_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "sk-ant",
                "BIOTECH_ALPHA_LLM_MODEL": "claude-test",
            }
        )

    def test_complete_success_with_usage_and_trace(self) -> None:
        queue = [_FakeAnthropicResponse(text='{"summary":"ok"}')]
        client = AnthropicLLMClient(
            self._config(),
            _anthropic_module=_FakeAnthropicModule(queue),
        )
        call = client.complete(
            system="s",
            user="u",
            agent_name="macro_context_llm_agent",
            response_format_json=True,
        )
        self.assertTrue(call.ok)
        self.assertEqual(call.model, "claude-test")
        self.assertIn('"summary"', call.response_text)
        self.assertEqual(call.prompt_tokens, 111)
        self.assertEqual(call.completion_tokens, 37)
        self.assertEqual(call.total_tokens, 148)
        self.assertEqual(len(client.trace.entries), 1)
        self.assertTrue(client.trace.entries[0].ok)

    def test_complete_failure_records_trace_and_raises(self) -> None:
        queue: list[object] = [RuntimeError("boom")]
        client = AnthropicLLMClient(
            self._config(),
            _anthropic_module=_FakeAnthropicModule(queue),
            max_retries=0,
        )
        with self.assertRaises(LLMError):
            client.complete(system="s", user="u", agent_name="a")
        self.assertEqual(len(client.trace.entries), 1)
        self.assertFalse(client.trace.entries[0].ok)
        self.assertIn("boom", client.trace.entries[0].error or "")

    def test_constructor_rejects_empty_key(self) -> None:
        bad = LLMConfig.from_env(
            {"BIOTECH_ALPHA_LLM_PROVIDER": "anthropic"},
            require_api_key=False,
        )
        with self.assertRaises(LLMError):
            AnthropicLLMClient(
                bad, _anthropic_module=_FakeAnthropicModule([])
            )

    def test_complete_uses_per_agent_model_override(self) -> None:
        config = LLMConfig.from_env(
            {
                "BIOTECH_ALPHA_LLM_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "sk-ant",
                "BIOTECH_ALPHA_LLM_MODEL": "claude-default",
                "BIOTECH_ALPHA_LLM_MODEL_MACRO_CONTEXT_LLM_AGENT": (
                    "claude-override"
                ),
            }
        )
        fake_queue = [_FakeAnthropicResponse(text='{"summary":"ok"}')]
        fake_module = _FakeAnthropicModule(fake_queue)
        client = AnthropicLLMClient(config, _anthropic_module=fake_module)

        call = client.complete(
            system="s",
            user="u",
            agent_name="macro_context_llm_agent",
        )

        self.assertEqual(call.model, "claude-override")
        fake_client = client._client  # type: ignore[attr-defined]
        self.assertEqual(
            fake_client.messages.calls[0]["model"],
            "claude-override",
        )


class BuildLLMClientRoutingTest(unittest.TestCase):
    def test_build_llm_client_selects_anthropic(self) -> None:
        from biotech_alpha import cli

        with unittest.mock.patch.dict(
            os.environ,
            {
                "BIOTECH_ALPHA_LLM_PROVIDER": "anthropic",
                "ANTHROPIC_API_KEY": "sk-ant",
            },
            clear=False,
        ), unittest.mock.patch(
            "biotech_alpha.llm.anthropic._load_anthropic_module",
            return_value=_FakeAnthropicModule(
                [_FakeAnthropicResponse(text='{"summary":"ok"}')]
            ),
        ):
            client = cli._build_llm_client(("macro-context",))
            self.assertIsInstance(client, AnthropicLLMClient)


if __name__ == "__main__":
    unittest.main()
