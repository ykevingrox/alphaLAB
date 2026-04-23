"""Agent interface sketches for the research system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from biotech_alpha.models import AgentFinding, TrialSummary


@dataclass(frozen=True)
class AgentContext:
    """Shared context passed into research agents."""

    company: str
    ticker: str | None = None
    market: str = "HK"
    as_of_date: str | None = None


class ResearchAgent(Protocol):
    """Protocol every research agent should implement."""

    name: str

    def run(self, context: AgentContext) -> AgentFinding:
        """Run the agent and return a structured finding."""


class ClinicalTrialAgent:
    """Summarizes trial coverage for a company or asset."""

    name = "clinical_trial_agent"

    def summarize_trials(
        self,
        context: AgentContext,
        trials: list[TrialSummary],
    ) -> AgentFinding:
        active = [
            trial
            for trial in trials
            if trial.status
            in {"RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING"}
        ]
        late_stage = [
            trial
            for trial in trials
            if trial.phase and ("PHASE3" in trial.phase or "PHASE2" in trial.phase)
        ]

        return AgentFinding(
            agent_name=self.name,
            summary=(
                f"{context.company} 在当前输入下匹配到 {len(trials)} 项试验，"
                f"其中活跃/即将启动 {len(active)} 项，二/三期 {len(late_stage)} 项。"
            ),
            score=None,
            risks=(),
            confidence=0.5 if trials else 0.1,
            needs_human_review=not trials,
        )
