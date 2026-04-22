"""LLM adapter layer for biotech-alpha-lab.

This subpackage keeps every LLM call behind a narrow, testable seam:

* :class:`LLMConfig` -- resolves endpoint, model, api key from environment.
* :class:`LLMClient` -- minimal protocol every provider must satisfy; the
  default :class:`OpenAICompatibleLLMClient` targets the Aliyun Bailian
  (DashScope) OpenAI-compatible endpoint but works for any OpenAI-API-shaped
  provider.
* :class:`FakeLLMClient` -- canned responses for network-free unit tests.
* :class:`LLMCall` / :class:`LLMTraceRecorder` -- structured trace with
  token and cost accounting, written as JSONL under ``data/traces/``.
* :class:`StructuredPrompt` -- renders templated prompts and validates the
  model's JSON response against a simple schema.

All source-backed claims produced by downstream LLM agents must still be
persisted with :class:`biotech_alpha.models.Evidence`, so this layer only
handles transport, accounting, and JSON structure, not domain semantics.
"""

from __future__ import annotations

from biotech_alpha.llm.anthropic import AnthropicLLMClient
from biotech_alpha.llm.client import (
    BudgetEnforcingLLMClient,
    FakeLLMClient,
    LLMBudgetError,
    LLMCall,
    LLMClient,
    LLMError,
    OpenAICompatibleLLMClient,
)
from biotech_alpha.llm.config import LLMConfig, LLMConfigError
from biotech_alpha.llm.prompts import StructuredPrompt
from biotech_alpha.llm.schema import SchemaError, validate_json_schema
from biotech_alpha.llm.trace import LLMTraceRecorder

__all__ = [
    "AnthropicLLMClient",
    "BudgetEnforcingLLMClient",
    "FakeLLMClient",
    "LLMBudgetError",
    "LLMCall",
    "LLMClient",
    "LLMConfig",
    "LLMConfigError",
    "LLMError",
    "LLMTraceRecorder",
    "OpenAICompatibleLLMClient",
    "SchemaError",
    "StructuredPrompt",
    "validate_json_schema",
]
