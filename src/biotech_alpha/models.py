"""Domain models for biotech investment research."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


ResearchDecision = Literal[
    "core_candidate",
    "watchlist",
    "avoid",
    "insufficient_data",
]


@dataclass(frozen=True)
class Evidence:
    """A source-backed fact or inference."""

    claim: str
    source: str
    source_date: str | None = None
    retrieved_at: str | None = None
    confidence: float = 0.0
    is_inferred: bool = False


@dataclass(frozen=True)
class TrialSummary:
    """Normalized subset of a clinical trial record."""

    registry: str
    registry_id: str
    title: str
    sponsor: str | None = None
    status: str | None = None
    phase: str | None = None
    conditions: tuple[str, ...] = ()
    interventions: tuple[str, ...] = ()
    enrollment: int | None = None
    start_date: str | None = None
    primary_completion_date: str | None = None
    completion_date: str | None = None
    last_update_posted: str | None = None


@dataclass(frozen=True)
class PipelineAsset:
    """A drug or product candidate disclosed by a company."""

    name: str
    aliases: tuple[str, ...] = ()
    target: str | None = None
    modality: str | None = None
    mechanism: str | None = None
    indication: str | None = None
    phase: str | None = None
    geography: str | None = None
    rights: str | None = None
    partner: str | None = None
    next_milestone: str | None = None
    clinical_data: tuple["ClinicalDataPoint", ...] = ()
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class ClinicalDataPoint:
    """Structured clinical-highlight datapoint for deep-dive rendering."""

    metric: str
    value: str | None = None
    unit: str | None = None
    sample_size: int | None = None
    context: str | None = None


@dataclass(frozen=True)
class TrialAssetMatch:
    """Deterministic link between a disclosed asset and registry trial."""

    asset_name: str
    registry_id: str
    match_reason: str
    matched_text: str
    confidence: float


@dataclass(frozen=True)
class CompetitorAsset:
    """A competing asset in the same target or indication space."""

    company: str
    asset_name: str
    aliases: tuple[str, ...] = ()
    target: str | None = None
    mechanism: str | None = None
    indication: str | None = None
    phase: str | None = None
    geography: str | None = None
    differentiation: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class CompetitiveMatch:
    """Deterministic link between a company asset and a competitor asset."""

    asset_name: str
    competitor_company: str
    competitor_asset: str
    match_scope: str
    confidence: float


@dataclass(frozen=True)
class Catalyst:
    """A future event that can materially change the investment thesis."""

    title: str
    category: Literal[
        "clinical",
        "regulatory",
        "commercial",
        "financial",
        "conference",
        "corporate",
        "unknown",
    ]
    expected_date: date | None = None
    expected_window: str | None = None
    related_asset: str | None = None
    confidence: float = 0.0
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class AgentFinding:
    """A finding produced by a research agent."""

    agent_name: str
    summary: str
    score: float | None = None
    risks: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    confidence: float = 0.0
    needs_human_review: bool = False


@dataclass(frozen=True)
class InvestmentMemo:
    """Committee-level decision support output."""

    company: str
    ticker: str | None
    market: str
    decision: ResearchDecision
    summary: str
    bull_case: tuple[str, ...] = ()
    bear_case: tuple[str, ...] = ()
    key_assets: tuple[PipelineAsset, ...] = ()
    catalysts: tuple[Catalyst, ...] = ()
    findings: tuple[AgentFinding, ...] = ()
    follow_up_questions: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = field(default_factory=tuple)
