"""LLM client protocol, OpenAI-compatible adapter, and fake client for tests.

The OpenAI adapter targets any OpenAI-Chat-Completions-compatible endpoint.
It was specifically smoke-tested against Aliyun Bailian (DashScope) at
``https://dashscope.aliyuncs.com/compatible-mode/v1`` with Qwen models, but
nothing in this module is vendor-locked.

The client returns a :class:`LLMCall` with structured fields + raw trace,
instead of just a string. All downstream code is expected to consume the
call object so tests and agents can co-assert on token counts, finish
reasons, retries, and errors without re-parsing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from biotech_alpha.llm.config import LLMConfig
from biotech_alpha.llm.trace import (
    LLMTraceRecorder,
    TraceEntry,
    hash_prompt,
    utc_now_isoformat,
)


class LLMError(RuntimeError):
    """Wraps any error the client could not recover from."""


@dataclass(frozen=True)
class LLMCall:
    """Outcome of a single LLM completion call."""

    model: str
    prompt: str
    system: str
    response_text: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    latency_ms: float
    finish_reason: str | None
    retries: int
    ok: bool
    error: str | None = None
    raw: dict[str, Any] | None = field(default=None, repr=False)


class LLMClient(Protocol):
    """Narrow surface every LLM provider implementation exposes."""

    model: str

    def complete(
        self,
        *,
        system: str,
        user: str,
        agent_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format_json: bool = True,
        extra_metadata: dict[str, Any] | None = None,
    ) -> LLMCall:
        ...


class OpenAICompatibleLLMClient:
    """OpenAI-API-shaped client. Works for OpenAI, Bailian/Qwen, etc."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        trace_recorder: LLMTraceRecorder | None = None,
        max_retries: int = 2,
        retry_initial_delay_seconds: float = 1.0,
        _openai_module: Any = None,
        _clock: Any = None,
    ) -> None:
        if not config.api_key:
            raise LLMError(
                "LLMConfig has no api_key; refusing to construct client"
            )
        self._config = config
        self._trace = trace_recorder or LLMTraceRecorder()
        self._max_retries = max_retries
        self._retry_initial_delay = retry_initial_delay_seconds
        self._clock = _clock or time
        self._calls_used = 0
        openai_module = _openai_module or _load_openai_module()
        self._client = openai_module.OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.request_timeout_seconds,
        )

    @property
    def model(self) -> str:
        return self._config.model

    @property
    def trace(self) -> LLMTraceRecorder:
        return self._trace

    def complete(
        self,
        *,
        system: str,
        user: str,
        agent_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format_json: bool = True,
        extra_metadata: dict[str, Any] | None = None,
    ) -> LLMCall:
        self._enforce_call_budget()

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        kwargs: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format_json:
            # OpenAI-style JSON mode; providers that ignore this key simply
            # fall back to free-form text, which our parser handles.
            kwargs["response_format"] = {"type": "json_object"}
        if _is_bailian_endpoint(self._config.base_url):
            # Qwen3 models default to "thinking on" on Bailian's compatible
            # endpoint, which inflates latency + completion tokens even when
            # the caller wants a terse JSON answer. Always send the explicit
            # flag so our config actually controls the behaviour.
            kwargs["extra_body"] = {
                "enable_thinking": bool(self._config.enable_thinking),
            }

        start = self._clock.monotonic()
        last_error: Exception | None = None
        retries = 0
        response: Any = None
        while True:
            try:
                response = self._client.chat.completions.create(**kwargs)
                break
            except Exception as exc:  # noqa: BLE001 - provider SDKs vary
                last_error = exc
                if retries >= self._max_retries:
                    break
                delay = self._retry_initial_delay * (2 ** retries)
                retries += 1
                self._clock.sleep(delay)

        latency_ms = (self._clock.monotonic() - start) * 1000.0
        self._calls_used += 1

        if response is None:
            self._record_failure(
                agent_name=agent_name,
                system=system,
                user=user,
                retries=retries,
                latency_ms=latency_ms,
                error=last_error,
                extra_metadata=extra_metadata,
            )
            raise LLMError(
                f"LLM call failed after {retries} retries: {last_error}"
            ) from last_error

        choice = response.choices[0]
        text = (choice.message.content or "").strip()
        reasoning = getattr(choice.message, "reasoning_content", None)
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = (
            getattr(usage, "completion_tokens", None) if usage else None
        )
        total_tokens = getattr(usage, "total_tokens", None) if usage else None
        finish_reason = getattr(choice, "finish_reason", None)

        call = LLMCall(
            model=self._config.model,
            prompt=user,
            system=system,
            response_text=text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
            retries=retries,
            ok=True,
            raw=_safe_dump(response),
        )
        success_extras = dict(extra_metadata or {})
        if reasoning:
            success_extras["reasoning_chars"] = len(reasoning)
            success_extras["reasoning_preview"] = reasoning[:500]
        self._record_success(
            call, agent_name=agent_name, extra_metadata=success_extras
        )
        return call

    def _record_success(
        self,
        call: LLMCall,
        *,
        agent_name: str,
        extra_metadata: dict[str, Any] | None,
    ) -> None:
        self._trace.record(
            TraceEntry(
                timestamp=utc_now_isoformat(),
                agent_name=agent_name,
                model=call.model,
                prompt_hash=hash_prompt(call.prompt),
                prompt_chars=len(call.prompt),
                response_chars=len(call.response_text),
                latency_ms=call.latency_ms,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                total_tokens=call.total_tokens,
                finish_reason=call.finish_reason,
                retries=call.retries,
                ok=True,
                error=None,
                extra=dict(extra_metadata or {}),
            )
        )

    def _record_failure(
        self,
        *,
        agent_name: str,
        system: str,
        user: str,
        retries: int,
        latency_ms: float,
        error: Exception | None,
        extra_metadata: dict[str, Any] | None,
    ) -> None:
        self._trace.record(
            TraceEntry(
                timestamp=utc_now_isoformat(),
                agent_name=agent_name,
                model=self._config.model,
                prompt_hash=hash_prompt(user),
                prompt_chars=len(user),
                response_chars=0,
                latency_ms=latency_ms,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                finish_reason=None,
                retries=retries,
                ok=False,
                error=str(error) if error is not None else "unknown error",
                extra=dict(extra_metadata or {}),
            )
        )

    def _enforce_call_budget(self) -> None:
        budget = self._config.call_budget
        if budget is None:
            return
        if self._calls_used >= budget:
            raise LLMError(
                f"LLM call budget exhausted: {budget} calls already used in this run"
            )


_BAILIAN_HOST_HINTS = ("dashscope.aliyuncs.com", "aliyuncs.com/compatible")


def _is_bailian_endpoint(base_url: str) -> bool:
    lowered = (base_url or "").lower()
    return any(hint in lowered for hint in _BAILIAN_HOST_HINTS)


def _load_openai_module() -> Any:
    try:
        import openai  # type: ignore
    except ImportError as exc:  # pragma: no cover - install-time concern
        raise LLMError(
            "openai package is required; run `pip install openai`"
        ) from exc
    return openai


def _safe_dump(response: Any) -> dict[str, Any] | None:
    """Produce a best-effort dict from an OpenAI SDK response object."""

    for attr in ("model_dump", "to_dict"):
        fn = getattr(response, attr, None)
        if callable(fn):
            try:
                return dict(fn())
            except Exception:  # noqa: BLE001
                continue
    return None


# ---------------------------------------------------------------------------
# FakeLLMClient: deterministic fixture double for offline tests.
# ---------------------------------------------------------------------------


@dataclass
class _CannedResponse:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = "stop"
    raise_error: Exception | None = None


class FakeLLMClient:
    """Canned-response client for unit tests.

    Use :meth:`queue` to enqueue responses in order, or pass
    ``default_response`` to reuse one fixed reply.
    """

    def __init__(
        self,
        *,
        model: str = "fake-model",
        default_response: str | None = None,
        trace_recorder: LLMTraceRecorder | None = None,
    ) -> None:
        self.model = model
        self._queue: list[_CannedResponse] = []
        self._default = (
            _CannedResponse(text=default_response)
            if default_response is not None
            else None
        )
        self._trace = trace_recorder or LLMTraceRecorder()
        self.calls: list[LLMCall] = []

    @property
    def trace(self) -> LLMTraceRecorder:
        return self._trace

    def queue(
        self,
        text: str | None = None,
        *,
        prompt_tokens: int | None = 100,
        completion_tokens: int | None = 50,
        total_tokens: int | None = 150,
        finish_reason: str | None = "stop",
        raise_error: Exception | None = None,
    ) -> None:
        self._queue.append(
            _CannedResponse(
                text=text or "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                finish_reason=finish_reason,
                raise_error=raise_error,
            )
        )

    def queue_many(self, texts: Iterable[str]) -> None:
        for text in texts:
            self.queue(text)

    def complete(
        self,
        *,
        system: str,
        user: str,
        agent_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format_json: bool = True,
        extra_metadata: dict[str, Any] | None = None,
    ) -> LLMCall:
        if self._queue:
            canned = self._queue.pop(0)
        elif self._default is not None:
            canned = self._default
        else:
            raise LLMError(
                "FakeLLMClient has no responses queued and no default response"
            )

        if canned.raise_error is not None:
            self._trace.record(
                TraceEntry(
                    timestamp=utc_now_isoformat(),
                    agent_name=agent_name,
                    model=self.model,
                    prompt_hash=hash_prompt(user),
                    prompt_chars=len(user),
                    response_chars=0,
                    latency_ms=0.0,
                    prompt_tokens=None,
                    completion_tokens=None,
                    total_tokens=None,
                    finish_reason=None,
                    retries=0,
                    ok=False,
                    error=str(canned.raise_error),
                    extra=dict(extra_metadata or {}),
                )
            )
            raise canned.raise_error

        call = LLMCall(
            model=self.model,
            prompt=user,
            system=system,
            response_text=canned.text,
            prompt_tokens=canned.prompt_tokens,
            completion_tokens=canned.completion_tokens,
            total_tokens=canned.total_tokens,
            latency_ms=0.0,
            finish_reason=canned.finish_reason,
            retries=0,
            ok=True,
            raw=None,
        )
        self.calls.append(call)
        self._trace.record(
            TraceEntry(
                timestamp=utc_now_isoformat(),
                agent_name=agent_name,
                model=self.model,
                prompt_hash=hash_prompt(user),
                prompt_chars=len(user),
                response_chars=len(call.response_text),
                latency_ms=call.latency_ms,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
                total_tokens=call.total_tokens,
                finish_reason=call.finish_reason,
                retries=call.retries,
                ok=True,
                error=None,
                extra=dict(extra_metadata or {}),
            )
        )
        return call
