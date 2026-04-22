"""Prompt templates and response parsing helpers.

The design priority is *deterministic, auditable structure*, not clever
prompt engineering. Every LLM agent builds a :class:`StructuredPrompt`
that pairs a system instruction, a user prompt template, and an expected
JSON schema. The same object is used to validate the model's response, so
prompt drift and schema drift are checked in one place.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from string import Template
from typing import Any

from biotech_alpha.llm.schema import SchemaError, validate_json_schema


@dataclass(frozen=True)
class StructuredPrompt:
    """A single prompt template paired with an expected JSON schema."""

    name: str
    system: str
    user_template: str
    schema: dict[str, Any]
    required_json: bool = True
    extra_instructions: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def render(self, variables: dict[str, Any]) -> tuple[str, str]:
        """Return ``(system_prompt, user_prompt)`` with variables substituted.

        ``$var`` / ``${var}`` placeholders in ``user_template`` are
        replaced from ``variables``. Missing variables raise ``KeyError``
        rather than silently producing "$var" in the request.
        """

        body = Template(self.user_template).substitute(variables)
        tail = ""
        if self.required_json:
            tail += (
                "\n\nReturn a single JSON object that conforms to the schema "
                "above. Do not include any text outside the JSON."
            )
        if self.extra_instructions:
            tail += "\n\n" + self.extra_instructions
        return self.system, body + tail

    def parse_response(self, text: str) -> dict[str, Any]:
        """Parse a JSON response from ``text`` and validate against schema."""

        payload = _extract_json_object(text)
        if not isinstance(payload, dict):
            raise SchemaError(
                f"prompt {self.name!r} expected a JSON object at the top level"
            )
        validate_json_schema(payload, self.schema)
        return payload


_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_json_object(text: str) -> Any:
    """Best-effort extraction of a JSON object from ``text``.

    We try, in order:

    1. Pure ``json.loads`` on the stripped text.
    2. The first fenced ``json`` code block.
    3. The substring from the first ``{`` to the matching last ``}``.
    """

    trimmed = text.strip()
    if not trimmed:
        raise SchemaError("empty response body")

    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        pass

    fence = _CODE_FENCE_RE.search(trimmed)
    if fence is not None:
        inner = fence.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass

    first = trimmed.find("{")
    last = trimmed.rfind("}")
    if first != -1 and last != -1 and last > first:
        candidate = trimmed[first : last + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise SchemaError(
                "failed to decode JSON object from model response"
            ) from exc

    raise SchemaError("no JSON object found in model response")
