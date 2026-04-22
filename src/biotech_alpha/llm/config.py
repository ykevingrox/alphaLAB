"""Environment-driven configuration for the LLM adapter layer."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.6-plus"
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
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    call_budget: int | None = None
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

        * ``BIOTECH_ALPHA_LLM_API_KEY`` -- primary. Falls back to
          ``DASHSCOPE_API_KEY`` so the same shell export works for both
          this project and the upstream Bailian SDK examples.
        * ``BIOTECH_ALPHA_LLM_BASE_URL`` -- optional, defaults to the
          Aliyun Bailian OpenAI-compatible endpoint.
        * ``BIOTECH_ALPHA_LLM_MODEL`` -- optional, defaults to
          ``qwen3.6-plus`` (Bailian's current primary Qwen3 model).
        * ``BIOTECH_ALPHA_LLM_REQUEST_TIMEOUT`` -- optional float seconds.
        * ``BIOTECH_ALPHA_LLM_CALL_BUDGET`` -- optional positive integer.
        * ``BIOTECH_ALPHA_LLM_TRACE_DIR`` -- optional path; defaults to
          ``data/traces``.
        * ``BIOTECH_ALPHA_LLM_ENABLE_THINKING`` -- optional boolean
          (``1``/``true``/``yes``). When enabled, the client asks
          Bailian to return reasoning_content alongside the final
          answer. Costs more tokens; reasoning_content is stored in the
          trace ``extra`` field, not in ``response_text``.
        """

        env = environ if environ is not None else os.environ
        api_key = (
            _clean(env.get("BIOTECH_ALPHA_LLM_API_KEY"))
            or _clean(env.get("DASHSCOPE_API_KEY"))
        )
        if require_api_key and not api_key:
            raise LLMConfigError(
                "Neither BIOTECH_ALPHA_LLM_API_KEY nor DASHSCOPE_API_KEY "
                "is set. Put the key in .env or export it in your shell; "
                "never commit the real value."
            )

        base_url = _clean(env.get("BIOTECH_ALPHA_LLM_BASE_URL")) or DEFAULT_BASE_URL
        model = _clean(env.get("BIOTECH_ALPHA_LLM_MODEL")) or DEFAULT_MODEL
        timeout = _parse_float(
            env.get("BIOTECH_ALPHA_LLM_REQUEST_TIMEOUT"),
            fallback=DEFAULT_REQUEST_TIMEOUT_SECONDS,
            name="BIOTECH_ALPHA_LLM_REQUEST_TIMEOUT",
        )
        call_budget = _parse_optional_positive_int(
            env.get("BIOTECH_ALPHA_LLM_CALL_BUDGET"),
            name="BIOTECH_ALPHA_LLM_CALL_BUDGET",
        )
        trace_dir_text = _clean(env.get("BIOTECH_ALPHA_LLM_TRACE_DIR"))
        trace_dir = Path(trace_dir_text) if trace_dir_text else DEFAULT_TRACE_DIR
        enable_thinking = _parse_bool(
            env.get("BIOTECH_ALPHA_LLM_ENABLE_THINKING"),
            fallback=False,
        )

        return cls(
            api_key=api_key or "",
            base_url=base_url,
            model=model,
            request_timeout_seconds=timeout,
            call_budget=call_budget,
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
