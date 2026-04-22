"""Lightweight multi-agent runtime.

Design goals:

* Declarative DAG: each :class:`Agent` declares ``depends_on`` (agent names)
  and ``produces`` (fact-store keys). :class:`AgentGraph` computes a
  topological layering and runs each layer in parallel via a thread pool.
* Error isolation: if one agent fails, every descendant is marked skipped
  but unrelated agents still run. The whole graph never breaks the CLI.
* Deterministic + LLM agents share the same surface. Deterministic work
  (pipeline extraction, skeptic review, valuation) is wrapped in
  :class:`DeterministicAgent`; real LLM agents (see
  :mod:`biotech_alpha.agents_llm`) use the same base class.
* Audit-first: every run produces an :class:`AgentRunResult` with the full
  step log, warnings, findings, and an aggregate cost summary from the
  :class:`biotech_alpha.llm.LLMTraceRecorder`.

The runtime is intentionally thin; nothing here knows about biotech. All
domain knowledge lives in the agent implementations.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from biotech_alpha.agents import AgentContext
from biotech_alpha.llm.trace import LLMTraceRecorder
from biotech_alpha.models import AgentFinding


class AgentRuntimeError(RuntimeError):
    """Raised when the graph is ill-formed (missing deps, cycles, duplicates)."""


# ---------------------------------------------------------------------------
# Fact store
# ---------------------------------------------------------------------------


class FactStore:
    """Thread-safe shared key/value store for inter-agent data hand-off.

    Agents read upstream outputs via :meth:`get` and publish their own via
    :meth:`put`. Values are intentionally untyped so the store can hold
    dataclasses, dicts, or primitives without serialization overhead.
    """

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._facts: dict[str, Any] = dict(initial or {})
        self._lock = threading.Lock()

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._facts[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._facts.get(key, default)

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._facts

    def keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._facts.keys())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._facts)


# ---------------------------------------------------------------------------
# Agent base class and step result
# ---------------------------------------------------------------------------


@dataclass
class AgentStepResult:
    """Outcome of a single agent execution in the graph."""

    agent_name: str
    finding: AgentFinding | None = None
    outputs: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    error: str | None = None
    skipped: bool = False
    latency_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None and not self.skipped


class Agent(ABC):
    """Base class for all agents scheduled by :class:`AgentGraph`.

    Subclasses must set :attr:`name` (unique within a graph) and may declare
    :attr:`depends_on` (names of agents that must run first) and
    :attr:`produces` (fact-store keys they publish). Returning
    ``outputs={"key": value}`` from :meth:`run` is equivalent to calling
    ``store.put("key", value)`` for each key.
    """

    name: str = ""
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    @abstractmethod
    def run(
        self, context: AgentContext, store: FactStore
    ) -> AgentStepResult:
        ...


class DeterministicAgent(Agent):
    """Adapter that wraps a plain callable as an :class:`Agent`.

    The callable receives ``(context, store)`` and returns either:

    * an :class:`AgentFinding`,
    * a ``dict`` that becomes ``outputs`` on the step result,
    * an :class:`AgentStepResult` (full control), or
    * ``None`` for side-effect-only steps.
    """

    def __init__(
        self,
        name: str,
        fn: Callable[[AgentContext, FactStore], Any],
        *,
        depends_on: tuple[str, ...] = (),
        produces: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self._fn = fn
        self.depends_on = depends_on
        self.produces = produces

    def run(
        self, context: AgentContext, store: FactStore
    ) -> AgentStepResult:
        raw = self._fn(context, store)
        if isinstance(raw, AgentStepResult):
            return raw
        if isinstance(raw, AgentFinding):
            return AgentStepResult(agent_name=self.name, finding=raw)
        if isinstance(raw, dict):
            return AgentStepResult(agent_name=self.name, outputs=dict(raw))
        if raw is None:
            return AgentStepResult(agent_name=self.name)
        raise AgentRuntimeError(
            f"DeterministicAgent {self.name!r} returned unsupported type "
            f"{type(raw).__name__}"
        )


# ---------------------------------------------------------------------------
# AgentGraph + AgentRunResult
# ---------------------------------------------------------------------------


@dataclass
class AgentRunResult:
    """Aggregate result of one graph execution."""

    findings: tuple[AgentFinding, ...]
    steps: tuple[AgentStepResult, ...]
    warnings: tuple[str, ...]
    facts: dict[str, Any]
    cost_summary: dict[str, Any]

    def step(self, agent_name: str) -> AgentStepResult | None:
        for s in self.steps:
            if s.agent_name == agent_name:
                return s
        return None


class AgentGraph:
    """Declarative DAG of :class:`Agent` nodes.

    Use :meth:`add` to register agents, then :meth:`run` to execute them in
    dependency order. Agents inside the same layer run in parallel via a
    thread pool (since they are almost always IO-bound). Raised exceptions
    never propagate to the caller; they are recorded on the step result.
    """

    def __init__(
        self,
        *,
        max_workers: int = 4,
        trace_recorder: LLMTraceRecorder | None = None,
    ) -> None:
        if max_workers < 1:
            raise AgentRuntimeError("max_workers must be >= 1")
        self._agents: dict[str, Agent] = {}
        self._max_workers = max_workers
        self._trace_recorder = trace_recorder

    def add(self, agent: Agent) -> "AgentGraph":
        if not agent.name:
            raise AgentRuntimeError("agent must have a non-empty name")
        if agent.name in self._agents:
            raise AgentRuntimeError(
                f"duplicate agent name in graph: {agent.name!r}"
            )
        self._agents[agent.name] = agent
        return self

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(self._agents.keys())

    def run(
        self,
        context: AgentContext,
        *,
        initial_facts: dict[str, Any] | None = None,
        clock: Any = None,
    ) -> AgentRunResult:
        layers = self._topological_layers()
        store = FactStore(initial_facts)
        results_by_name: dict[str, AgentStepResult] = {}
        warnings: list[str] = []
        steps_order: list[AgentStepResult] = []
        monotonic = (clock or _DEFAULT_CLOCK).monotonic

        for layer in layers:
            runnable: list[Agent] = []
            for name in layer:
                agent = self._agents[name]
                skip_reason = self._resolve_skip_reason(
                    agent, results_by_name
                )
                if skip_reason is not None:
                    step = AgentStepResult(
                        agent_name=name,
                        skipped=True,
                        error=skip_reason,
                    )
                    results_by_name[name] = step
                    steps_order.append(step)
                    warnings.append(
                        f"agent {name!r} skipped: {skip_reason}"
                    )
                    continue
                runnable.append(agent)

            if not runnable:
                continue

            results = self._run_layer(runnable, context, store, monotonic)
            for step in results:
                results_by_name[step.agent_name] = step
                steps_order.append(step)
                for key, value in step.outputs.items():
                    store.put(key, value)
                for warning in step.warnings:
                    warnings.append(f"{step.agent_name}: {warning}")
                if step.error is not None and not step.skipped:
                    warnings.append(
                        f"agent {step.agent_name!r} failed: {step.error}"
                    )

        findings: list[AgentFinding] = []
        for step in steps_order:
            if step.finding is not None:
                findings.append(step.finding)

        cost_summary = (
            self._trace_recorder.cost_summary()
            if self._trace_recorder is not None
            else {}
        )

        return AgentRunResult(
            findings=tuple(findings),
            steps=tuple(steps_order),
            warnings=tuple(warnings),
            facts=store.snapshot(),
            cost_summary=cost_summary,
        )

    def _run_layer(
        self,
        agents: list[Agent],
        context: AgentContext,
        store: FactStore,
        monotonic: Callable[[], float],
    ) -> list[AgentStepResult]:
        if len(agents) == 1:
            return [self._run_one(agents[0], context, store, monotonic)]

        with ThreadPoolExecutor(
            max_workers=min(self._max_workers, len(agents))
        ) as pool:
            futures = {
                pool.submit(self._run_one, agent, context, store, monotonic): agent
                for agent in agents
            }
            results: list[AgentStepResult] = []
            for fut in futures:
                results.append(fut.result())
        return results

    @staticmethod
    def _run_one(
        agent: Agent,
        context: AgentContext,
        store: FactStore,
        monotonic: Callable[[], float],
    ) -> AgentStepResult:
        started = monotonic()
        try:
            step = agent.run(context, store)
        except Exception as exc:  # noqa: BLE001 - isolate any agent failure
            return AgentStepResult(
                agent_name=agent.name,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=(monotonic() - started) * 1000.0,
            )
        if step.latency_ms == 0.0:
            step.latency_ms = (monotonic() - started) * 1000.0
        if step.agent_name == "":
            step.agent_name = agent.name
        return step

    def _resolve_skip_reason(
        self,
        agent: Agent,
        results: dict[str, AgentStepResult],
    ) -> str | None:
        for dep in agent.depends_on:
            if dep not in self._agents:
                return f"missing upstream agent {dep!r}"
            prior = results.get(dep)
            if prior is None:
                return f"upstream {dep!r} did not run"
            if prior.error is not None or prior.skipped:
                return f"upstream {dep!r} failed or skipped"
        return None

    def _topological_layers(self) -> list[list[str]]:
        unresolved = {
            name: set(agent.depends_on) for name, agent in self._agents.items()
        }
        for name, deps in unresolved.items():
            missing = [d for d in deps if d not in self._agents]
            if missing:
                raise AgentRuntimeError(
                    f"agent {name!r} depends on unknown agent(s): {missing}"
                )

        layers: list[list[str]] = []
        remaining = dict(unresolved)
        while remaining:
            ready = sorted(
                name for name, deps in remaining.items() if not deps
            )
            if not ready:
                raise AgentRuntimeError(
                    f"cycle detected in agent graph; remaining: {list(remaining)}"
                )
            layers.append(ready)
            for name in ready:
                remaining.pop(name, None)
            for deps in remaining.values():
                for name in ready:
                    deps.discard(name)
        return layers


class _SystemClock:
    @staticmethod
    def monotonic() -> float:
        import time

        return time.monotonic()


_DEFAULT_CLOCK = _SystemClock()
