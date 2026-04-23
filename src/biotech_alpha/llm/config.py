"""Environment-driven configuration for the LLM adapter layer."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast


DEFAULT_PROVIDER: Literal["openai-compatible", "anthropic"] = (
    "openai-compatible"
)
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.5-plus"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_MODEL = "claude-3-5-sonnet-latest"
DEFAULT_TRACE_DIR = Path("data/traces")
DEFAULT_REQUEST_TIMEOUT_SECONDS = 60.0


class LLMConfigError(RuntimeError):
    """Raised when LLM configuration is missing or invalid."""


@dataclass(frozen=True)
class LLMConfig:
    """Resolved configuration for a single LLM client.

    Callers typically build this via :meth:`LLMConfig.from_env` so secrets
    stay in ``.env`` / shell exports and never touch the repository.
    """

    api_key: str
    provider: Literal["openai-compatible", "anthropic"] = DEFAULT_PROVIDER
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    call_budget: int | None = None
    per_agent_call_budget: int | None = None
    trace_dir: Path = field(default_factory=lambda: DEFAULT_TRACE_DIR)
    enable_thinking: bool = False

    @classmethod
    def from_env(
        cls,
        environ: dict[str, str] | None = None,
        *,
        require_api_key: bool = True,
    ) -> "LLMConfig":
        """Build configuration from environment variables.

        Environment variables consumed:

        * ``BIOTECH_ALPHA_LLM_PROVIDER`` -- optional, one of
          ``openai-compatible`` (default) or ``anthropic``.
        * ``BIOTECH_ALPHA_LLM_API_KEY`` -- primary. Falls back to
          ``DASHSCOPE_API_KEY`` so the same shell export works for both
          this project and the upstream Bailian SDK examples when
          ``provider=openai-compatible``.
        * ``ANTHROPIC_API_KEY`` -- required when
          ``provider=anthropic``.
        * ``BIOTECH_ALPHA_LLM_BASE_URL`` -- optional, defaults to the
          Aliyun Bailian OpenAI-compatible endpoint for
          ``provider=openai-compatible`` and to ``https://api.anthropic.com``
          for ``provider=anthropic``.
        * ``BIOTECH_ALPHA_LLM_MODEL`` -- optional, defaults to
          ``qwen3.5-plus`` for ``provider=openai-compatible`` and
          ``claude-3-5-sonnet-latest`` for ``provider=anthropic``.
        * ``BIOTECH_ALPHA_LLM_REQUEST_TIMEOUT`` -- optional float seconds.
        * ``BIOTECH_ALPHA_LLM_CALL_BUDGET`` -- optional positive integer.
          Hard ceiling on total LLM calls for one client lifetime.
        * ``BIOTECH_ALPHA_LLM_PER_AGENT_CALL_BUDGET`` -- optional positive
          integer. Hard ceiling on calls any single agent is allowed to
          make. Useful to keep a misbehaving agent from draining budget
          reserved for other agents in the same run.
        * ``BIOTECH_ALPHA_LLM_TRACE_DIR`` -- optional path; defaults to
          ``data/traces``.
        * ``BIOTECH_ALPHA_LLM_ENABLE_THINKING`` -- optional boolean
          (``1``/``true``/``yes``). When enabled, the client asks
          Bailian to return reasoning_content alongside the final
          answer. Costs more tokens; reasoning_content is stored in the
          trace ``extra`` field, not in ``response_text``.
        """

        env = environ if environ is not None else os.environ
        provider = _parse_provider(
            env.get("BIOTECH_ALPHA_LLM_PROVIDER"),
            fallback=DEFAULT_PROVIDER,
        )
        if provider == "anthropic":
            api_key = _clean(env.get("ANTHROPIC_API_KEY"))
        else:
            api_key = (
                _clean(env.get("BIOTECH_ALPHA_LLM_API_KEY"))
                or _clean(env.get("DASHSCOPE_API_KEY"))
            )
        if require_api_key and not api_key:
            if provider == "anthropic":
                raise LLMConfigError(
                    "ANTHROPIC_API_KEY is not set while "
                    "BIOTECH_ALPHA_LLM_PROVIDER=anthropic. Put the key "
                    "in .env or export it in your shell; never commit "
                    "the real value."
                )
            raise LLMConfigError(
                "Neither BIOTECH_ALPHA_LLM_API_KEY nor DASHSCOPE_API_KEY "
                "is set. Put the key in .env or export it in your shell; "
                "never commit the real value."
            )

        default_base_url = (
            DEFAULT_ANTHROPIC_BASE_URL
            if provider == "anthropic"
            else DEFAULT_BASE_URL
        )
        default_model = (
            DEFAULT_ANTHROPIC_MODEL
            if provider == "anthropic"
            else DEFAULT_MODEL
        )
        base_url = _clean(env.get("BIOTECH_ALPHA_LLM_BASE_URL")) or default_base_url
        model = _clean(env.get("BIOTECH_ALPHA_LLM_MODEL")) or default_model
        timeout = _parse_float(
            env.get("BIOTECH_ALPHA_LLM_REQUEST_TIMEOUT"),
            fallback=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            name="BIOTECH_ALPHA_LLM_REQUEST_TIMEOUT",
        )
        call_budget = _parse_optional_positive_int(
            env.get("BIOTECH_ALPHA_LLM_CALL_BUDGET"),
            name="BIOTECH_ALPHA_LLM_CALL_BUDGET",
        )
        per_agent_call_budget = _parse_optional_positive_int(
            env.get("BIOTECH_ALPHA_LLM_PER_AGENT_CALL_BUDGET"),
            name="BIOTECH_ALPHA_LLM_PER_AGENT_CALL_BUDGET",
        )
        trace_dir_text = _clean(env.get("BIOTECH_ALPHA_LLM_TRACE_DIR"))
        trace_dir = Path(trace_dir_text) if trace_dir_text else DEFAULT_TRACE_DIR
        enable_thinking = _parse_bool(
            env.get("BIOTECH_ALPHA_LLM_ENABLE_THINKING"),
            fallback=False,
        )

        return cls(
            provider=provider,
            api_key=api_key or "",
            base_url=base_url,
            model=model,
            request_timeout_seconds=timeout,
            call_budget=call_budget,
            per_agent_call_budget=per_agent_call_budget,
            trace_dir=trace_dir,
            enable_thinking=enable_thinking,
        )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_float(value: str | None, *, fallback: float, name: str) -> float:
    text = _clean(value)
    if text is None:
        return fallback
    try:
        parsed = float(text)
    except ValueError as exc:
        raise LLMConfigError(f"{name} must be a number, got {value!r}") from exc
    if parsed <= 0:
        raise LLMConfigError(f"{name} must be positive, got {parsed}")
    return parsed


def _parse_optional_positive_int(value: str | None, *, name: str) -> int | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        parsed = int(text)
    except ValueError as exc:
        raise LLMConfigError(f"{name} must be an integer, got {value!r}") from exc
    if parsed <= 0:
        raise LLMConfigError(f"{name} must be positive, got {parsed}")
    return parsed


_TRUTHY = {"1", "true", "yes", "y", "on"}
_FALSY = {"0", "false", "no", "n", "off"}


def _parse_bool(value: str | None, *, fallback: bool) -> bool:
    text = _clean(value)
    if text is None:
        return fallback
    lowered = text.lower()
    if lowered in _TRUTHY:
        return True
    if lowered in _FALSY:
        return False
    return fallback


def _parse_provider(
    value: str | None, *, fallback: Literal["openai-compatible", "anthropic"]
) -> Literal["openai-compatible", "anthropic"]:
    text = _clean(value)
    if text is None:
        return fallback
    lowered = text.lower()
    allowed = {"openai-compatible", "anthropic"}
    if lowered not in allowed:
        raise LLMConfigError(
            "BIOTECH_ALPHA_LLM_PROVIDER must be one of "
            "'openai-compatible' or 'anthropic', got "
            f"{value!r}"
        )
    return cast(Literal["openai-compatible", "anthropic"], lowered)
