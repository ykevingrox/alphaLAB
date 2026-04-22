"""Tests for the multi-agent runtime DAG, parallelism, and error isolation."""

from __future__ import annotations

import threading
import time
import unittest

from biotech_alpha.agent_runtime import (
    Agent,
    AgentGraph,
    AgentRuntimeError,
    AgentStepResult,
    DeterministicAgent,
    FactStore,
)
from biotech_alpha.agents import AgentContext
from biotech_alpha.models import AgentFinding


def _ctx() -> AgentContext:
    return AgentContext(company="Example Bio", ticker="00000.HK")


class SimpleAgent(Agent):
    def __init__(
        self,
        name: str,
        *,
        depends_on: tuple[str, ...] = (),
        outputs: dict | None = None,
        sleep: float = 0.0,
        raise_: Exception | None = None,
    ) -> None:
        self.name = name
        self.depends_on = depends_on
        self._outputs = outputs or {}
        self._sleep = sleep
        self._raise = raise_

    def run(self, context, store) -> AgentStepResult:
        if self._sleep:
            time.sleep(self._sleep)
        if self._raise is not None:
            raise self._raise
        return AgentStepResult(
            agent_name=self.name,
            outputs=dict(self._outputs),
        )


class FactStoreTest(unittest.TestCase):
    def test_concurrent_writes_do_not_lose_values(self) -> None:
        store = FactStore()

        def worker(index: int) -> None:
            for i in range(100):
                store.put(f"k{index}_{i}", i)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for index in range(4):
            for i in range(100):
                self.assertEqual(store.get(f"k{index}_{i}"), i)


class AgentGraphHappyPathTest(unittest.TestCase):
    def test_topological_order_respects_deps(self) -> None:
        graph = AgentGraph()
        graph.add(SimpleAgent("a", outputs={"a": 1}))
        graph.add(SimpleAgent("b", depends_on=("a",), outputs={"b": 2}))
        graph.add(
            SimpleAgent("c", depends_on=("a", "b"), outputs={"c": 3})
        )

        result = graph.run(_ctx())

        order = [s.agent_name for s in result.steps]
        self.assertEqual(order, ["a", "b", "c"])
        self.assertEqual(result.facts["a"], 1)
        self.assertEqual(result.facts["b"], 2)
        self.assertEqual(result.facts["c"], 3)
        self.assertEqual(result.warnings, ())

    def test_independent_agents_run_in_parallel(self) -> None:
        graph = AgentGraph(max_workers=3)
        graph.add(SimpleAgent("x", sleep=0.05))
        graph.add(SimpleAgent("y", sleep=0.05))
        graph.add(SimpleAgent("z", sleep=0.05))

        start = time.monotonic()
        graph.run(_ctx())
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 0.12)

    def test_deterministic_agent_adapter_accepts_finding(self) -> None:
        graph = AgentGraph()
        graph.add(
            DeterministicAgent(
                "f",
                lambda ctx, store: AgentFinding(
                    agent_name="f",
                    summary="ok",
                    confidence=0.4,
                ),
            )
        )

        result = graph.run(_ctx())

        self.assertEqual(len(result.findings), 1)
        self.assertEqual(result.findings[0].summary, "ok")


class AgentGraphErrorIsolationTest(unittest.TestCase):
    def test_failure_isolates_dependents_only(self) -> None:
        graph = AgentGraph()
        graph.add(SimpleAgent("parent", raise_=RuntimeError("boom")))
        graph.add(SimpleAgent("child", depends_on=("parent",)))
        graph.add(
            SimpleAgent("unrelated", outputs={"unrelated": "ran"})
        )

        result = graph.run(_ctx())

        steps = {s.agent_name: s for s in result.steps}
        self.assertIn("RuntimeError: boom", steps["parent"].error or "")
        self.assertTrue(steps["child"].skipped)
        self.assertIn("upstream 'parent' failed", steps["child"].error or "")
        self.assertTrue(steps["unrelated"].ok)
        self.assertEqual(result.facts["unrelated"], "ran")

    def test_cycle_detection_raises(self) -> None:
        graph = AgentGraph()
        graph.add(SimpleAgent("a", depends_on=("b",)))
        graph.add(SimpleAgent("b", depends_on=("a",)))

        with self.assertRaises(AgentRuntimeError):
            graph.run(_ctx())

    def test_duplicate_agent_name_raises(self) -> None:
        graph = AgentGraph()
        graph.add(SimpleAgent("x"))
        with self.assertRaises(AgentRuntimeError):
            graph.add(SimpleAgent("x"))

    def test_unknown_dependency_raises(self) -> None:
        graph = AgentGraph()
        graph.add(SimpleAgent("child", depends_on=("ghost",)))
        with self.assertRaises(AgentRuntimeError):
            graph.run(_ctx())


if __name__ == "__main__":
    unittest.main()
