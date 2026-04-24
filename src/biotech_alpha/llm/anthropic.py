"""Anthropic Messages API adapter implementing the shared LLM protocol."""

from __future__ import annotations

import time
from typing import Any

from biotech_alpha.llm.client import LLMCall, LLMError
from biotech_alpha.llm.config import LLMConfig
from biotech_alpha.llm.trace import (
    LLMTraceRecorder,
    TraceEntry,
    hash_prompt,
    utc_now_isoformat,
)


class AnthropicLLMClient:
    """Anthropic client adapter with the same shape as other providers."""

    def __init__(
        self,
        config: LLMConfig,
        *,
        trace_recorder: LLMTraceRecorder | None = None,
        max_retries: int = 2,
        retry_initial_delay_seconds: float = 1.0,
        _anthropic_module: Any = None,
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
        anthropic_module = _anthropic_module or _load_anthropic_module()
        self._client = anthropic_module.Anthropic(
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
        resolved_model = self._config.model_for_agent(agent_name)
        kwargs: dict[str, Any] = {
            "model": resolved_model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": temperature,
            "max_tokens": max_tokens or 1024,
        }
        if response_format_json:
            kwargs["metadata"] = {"response_format_json": True}

        start = self._clock.monotonic()
        last_error: Exception | None = None
        retries = 0
        response: Any = None
        while True:
            try:
                response = self._client.messages.create(**kwargs)
                break
            except Exception as exc:  # noqa: BLE001 - provider SDK varies
                last_error = exc
                if retries >= self._max_retries:
                    break
                delay = self._retry_initial_delay * (2**retries)
                retries += 1
                self._clock.sleep(delay)

        latency_ms = (self._clock.monotonic() - start) * 1000.0
        if response is None:
            self._record_failure(
                agent_name=agent_name,
                user=user,
                retries=retries,
                latency_ms=latency_ms,
                error=last_error,
                model=resolved_model,
                extra_metadata=extra_metadata,
            )
            raise LLMError(
                f"Anthropic call failed after {retries} retries: {last_error}"
            ) from last_error

        text = _message_text(response)
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "input_tokens", None) if usage else None
        completion_tokens = (
            getattr(usage, "output_tokens", None) if usage else None
        )
        total_tokens: int | None = None
        if prompt_tokens is not None or completion_tokens is not None:
            total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)
        finish_reason = getattr(response, "stop_reason", None)
        call = LLMCall(
            model=resolved_model,
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
        self._record_success(
            call=call,
            agent_name=agent_name,
            extra_metadata=extra_metadata,
        )
        return call

    def _record_success(
        self,
        *,
        call: LLMCall,
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
        user: str,
        retries: int,
        latency_ms: float,
        error: Exception | None,
        model: str,
        extra_metadata: dict[str, Any] | None,
    ) -> None:
        self._trace.record(
            TraceEntry(
                timestamp=utc_now_isoformat(),
                agent_name=agent_name,
                model=model,
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


def _load_anthropic_module() -> Any:
    try:
        import anthropic  # type: ignore
    except ImportError as exc:  # pragma: no cover - install-time concern
        raise LLMError(
            "anthropic package is required; run `pip install anthropic`"
        ) from exc
    return anthropic


def _message_text(response: Any) -> str:
    blocks = getattr(response, "content", None)
    if not isinstance(blocks, list):
        return ""
    parts: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    return "".join(parts).strip()


def _safe_dump(response: Any) -> dict[str, Any] | None:
    for attr in ("model_dump", "to_dict"):
        fn = getattr(response, attr, None)
        if callable(fn):
            try:
                return dict(fn())
            except Exception:  # noqa: BLE001
                continue
    return None

