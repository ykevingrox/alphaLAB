"""Structured tracing for LLM calls.

One JSONL file per agent run lives under ``data/traces/`` by default. Each
line records: timestamp, agent name, model, prompt hash, latency, token
usage, and any warnings/errors. We never write the raw API key or the raw
``Authorization`` header. Prompt + response content are stored for audit,
which is fine for a private research tool; strip them here if that ever
changes.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TraceEntry:
    """Serializable record for a single LLM call."""

    timestamp: str
    agent_name: str
    model: str
    prompt_hash: str
    prompt_chars: int
    response_chars: int
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    finish_reason: str | None
    retries: int
    ok: bool
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "agent_name": self.agent_name,
            "model": self.model,
            "prompt_hash": self.prompt_hash,
            "prompt_chars": self.prompt_chars,
            "response_chars": self.response_chars,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "finish_reason": self.finish_reason,
            "retries": self.retries,
            "ok": self.ok,
            "error": self.error,
            "extra": dict(self.extra),
        }


class LLMTraceRecorder:
    """Append-only JSONL recorder for LLM calls.

    The recorder is in-memory-first: entries are kept in ``self.entries``
    and only flushed to disk when :meth:`flush` is called (or when created
    with ``flush_each=True``). This makes tests hermetic and also lets a
    single CLI run write one trace file with a stable name.
    """

    def __init__(
        self,
        *,
        path: Path | None = None,
        flush_each: bool = False,
    ) -> None:
        self.path = path
        self.flush_each = flush_each
        self.entries: list[TraceEntry] = []
        self._lock = threading.Lock()

    def record(self, entry: TraceEntry) -> None:
        with self._lock:
            self.entries.append(entry)
            if self.flush_each and self.path is not None:
                self._write(entry)

    def flush(self) -> Path | None:
        if self.path is None:
            return None
        with self._lock:
            if not self.entries:
                return self.path
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                for entry in self.entries:
                    stream.write(json.dumps(entry.as_dict(), ensure_ascii=False))
                    stream.write("\n")
            return self.path

    def cost_summary(self) -> dict[str, Any]:
        """Return a light aggregate across recorded entries."""

        total = len(self.entries)
        ok = sum(1 for e in self.entries if e.ok)
        prompt_tokens = sum(e.prompt_tokens or 0 for e in self.entries)
        completion_tokens = sum(e.completion_tokens or 0 for e in self.entries)
        total_tokens = sum(e.total_tokens or 0 for e in self.entries)
        latency_ms = sum(e.latency_ms for e in self.entries)
        return {
            "calls": total,
            "ok": ok,
            "failed": total - ok,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "total_latency_ms": latency_ms,
        }

    def _write(self, entry: TraceEntry) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry.as_dict(), ensure_ascii=False))
            stream.write("\n")


def hash_prompt(text: str) -> str:
    """Return a short stable hash used to deduplicate identical prompts."""

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest[:16]


def utc_now_isoformat() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
