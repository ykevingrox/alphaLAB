"""Minimal one-shot smoke test for the LLM adapter.

Loads .env, constructs an OpenAICompatibleLLMClient, asks the model a
trivial prompt that must return a strict JSON object, and prints:

* model identity returned by the provider (via response)
* token usage
* whether the response parsed as JSON
* any error message

Run with: PYTHONPATH=src python scripts/llm_smoke.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader; does not override already-set env vars."""

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    _load_dotenv(root / ".env")

    from biotech_alpha.llm import (
        LLMConfig,
        LLMTraceRecorder,
        OpenAICompatibleLLMClient,
        StructuredPrompt,
    )

    config = LLMConfig.from_env()
    print(f"base_url = {config.base_url}")
    print(f"model    = {config.model}")
    print(f"thinking = {config.enable_thinking}")
    print(f"api_key  = present (len={len(config.api_key)})")
    print()

    recorder = LLMTraceRecorder()
    client = OpenAICompatibleLLMClient(config, trace_recorder=recorder)

    prompt = StructuredPrompt(
        name="smoke_ping",
        system=(
            "You are a terse JSON-only response bot used for smoke testing. "
            "Reply with exactly one JSON object, no prose."
        ),
        user_template=(
            "Return a JSON object with keys: ok (true), model (the model "
            "id you believe you are), greeting (a short string)."
        ),
        schema={
            "type": "object",
            "required": ["ok", "greeting"],
            "properties": {
                "ok": {"type": "boolean"},
                "model": {"type": ["string", "null"]},
                "greeting": {"type": "string", "min_length": 1},
            },
        },
    )

    system, user = prompt.render({})
    try:
        call = client.complete(
            system=system,
            user=user,
            agent_name="smoke_ping",
            temperature=0.0,
            max_tokens=200,
            response_format_json=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"LLM call raised: {type(exc).__name__}: {exc}")
        return 2

    print(f"latency_ms       = {call.latency_ms:.1f}")
    print(f"finish_reason    = {call.finish_reason}")
    print(f"prompt_tokens    = {call.prompt_tokens}")
    print(f"completion_tokens= {call.completion_tokens}")
    print(f"total_tokens     = {call.total_tokens}")
    print()
    print("--- raw response (first 400 chars) ---")
    print(call.response_text[:400])
    print()

    try:
        payload = prompt.parse_response(call.response_text)
    except Exception as exc:  # noqa: BLE001
        print(f"schema parse failed: {exc}")
        return 3

    print("--- parsed ---")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print()
    print("--- cost_summary ---")
    print(json.dumps(recorder.cost_summary(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
