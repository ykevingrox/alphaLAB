"""One-command company report orchestration."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from biotech_alpha.research import (
    ClinicalTrialsSource,
    SingleCompanyResearchResult,
    result_summary,
    run_single_company_research,
)


@dataclass(frozen=True)
class CompanyIdentity:
    """Resolved company identity for a report run."""

    company: str
    ticker: str | None = None
    market: str = "HK"
    sector: str = "biotech"
    search_term: str | None = None
    aliases: tuple[str, ...] = ()
    registry_match: str | None = None


@dataclass(frozen=True)
class CompanyReportInputPaths:
    """Curated input files discovered for a company report."""

    pipeline_assets: Path | None = None
    financials: Path | None = None
    competitors: Path | None = None
    valuation: Path | None = None
    conference_catalysts: Path | None = None
    target_price_assumptions: Path | None = None


@dataclass(frozen=True)
class MissingInput:
    """One missing input needed to improve a company report."""

    key: str
    severity: str
    reason: str
    suggested_path: Path
    next_action: str
    template_command: str | None = None


@dataclass(frozen=True)
class CompanyReportResult:
    """Result returned by the one-command company report entry point."""

    identity: CompanyIdentity
    input_paths: CompanyReportInputPaths
    missing_inputs: tuple[MissingInput, ...]
    missing_inputs_report: Path | None
    research_result: SingleCompanyResearchResult
    auto_input_artifacts: Any | None = None
    llm_agent_result: Any | None = None
    llm_trace_path: Path | None = None


INPUT_SUFFIXES = {
    "pipeline_assets": ("pipeline_assets", "pipeline"),
    "financials": ("financials", "financial"),
    "competitors": ("competitors", "competitor"),
    "valuation": ("valuation",),
    "conference_catalysts": ("conference_catalysts", "conference"),
    "target_price_assumptions": ("target_price_assumptions", "target_price"),
}

MISSING_INPUT_SPECS = {
    "pipeline_assets": {
        "severity": "high",
        "reason": "Pipeline assets are needed for asset-level trial matching.",
        "next_action": (
            "Create the pipeline template, then fill the company's disclosed "
            "core assets, aliases, targets, indications, phases, milestones, "
            "and evidence sources."
        ),
        "template_command": "pipeline-template",
    },
    "financials": {
        "severity": "high",
        "reason": "Financial snapshot is needed for cash runway and dilution risk.",
        "next_action": (
            "Create the financial template, then fill cash, debt, burn or "
            "operating cash flow, source, and source date from the latest "
            "annual or interim report."
        ),
        "template_command": "financial-template",
    },
    "competitors": {
        "severity": "medium",
        "reason": "Competitor assets improve differentiation and crowding checks.",
        "next_action": (
            "Create the competitor template, then add major assets with matching "
            "targets or indications for the company's key programs."
        ),
        "template_command": "competitor-template",
    },
    "valuation": {
        "severity": "medium",
        "reason": "Valuation snapshot is needed for market context.",
        "next_action": (
            "Auto-draft with `company-report --auto-inputs --market-data "
            "hk-public` when a live HK quote is available, or create the "
            "valuation template manually and fill market cap or share price, "
            "shares outstanding, cash, debt, revenue if available, and source."
        ),
        "template_command": "valuation-template",
    },
    "target_price_assumptions": {
        "severity": "optional",
        "reason": "Target-price assumptions are needed for rNPV scenario ranges.",
        "next_action": (
            "Create the target-price template only after the core pipeline and "
            "financial inputs are credible; fill explicit rNPV assumptions and "
            "event-impact deltas."
        ),
        "template_command": "target-price-template",
    },
    "conference_catalysts": {
        "severity": "optional",
        "reason": "Conference catalysts improve event-calendar completeness.",
        "next_action": (
            "Create the conference catalyst template, then add conference events "
            "with source links, dates, confidence, and related assets."
        ),
        "template_command": "conference-template",
    },
}


def run_company_report(
    *,
    company: str | None = None,
    ticker: str | None = None,
    market: str | None = None,
    sector: str = "biotech",
    search_term: str | None = None,
    input_dir: str | Path = "data/input",
    output_dir: str | Path = "data",
    registry_path: str | Path | None = "data/input/company_registry.json",
    auto_inputs: bool = False,
    generated_input_dir: str | Path = "data/input/generated",
    overwrite_auto_inputs: bool = False,
    market_data_provider: Callable[[CompanyIdentity], dict[str, Any] | None]
    | None = None,
    include_asset_queries: bool = True,
    max_asset_query_terms: int = 20,
    limit: int = 20,
    save: bool = True,
    client: ClinicalTrialsSource | None = None,
    now: datetime | None = None,
    llm_agents: tuple[str, ...] = (),
    llm_client: Any | None = None,
    llm_trace_path: str | Path | None = None,
    macro_signals_provider: Callable[[str], dict[str, Any] | None] | None = None,
) -> CompanyReportResult:
    """Run a company report from a company name or ticker.

    The command-level workflow keeps curated JSON inputs optional. It auto-runs
    the available research path, attaches any discovered inputs, and writes a
    missing-input report so the next pass can be upgraded without changing the
    lower-level research contract.
    """

    identity = resolve_company_identity(
        company=company,
        ticker=ticker,
        market=market,
        sector=sector,
        search_term=search_term,
        registry_path=registry_path,
    )
    auto_input_artifacts = None
    if auto_inputs:
        from biotech_alpha.auto_inputs import generate_auto_inputs
        from biotech_alpha.auto_inputs import AutoInputArtifacts

        try:
            auto_input_artifacts = generate_auto_inputs(
                identity=identity,
                input_dir=generated_input_dir,
                output_dir=output_dir,
                overwrite=overwrite_auto_inputs,
                market_data_provider=market_data_provider,
            )
        except Exception as exc:  # noqa: BLE001 - keep one-command flow resilient.
            auto_input_artifacts = AutoInputArtifacts(
                warnings=(
                    "auto input generation failed; falling back to discovered "
                    f"inputs only: {exc}",
                )
            )
        identity = enrich_identity_from_auto_input_artifacts(
            identity=identity,
            auto_input_artifacts=auto_input_artifacts,
        )
    input_paths = discover_company_inputs(identity, input_dir=input_dir)
    if auto_inputs:
        generated_paths = discover_company_inputs(
            identity,
            input_dir=generated_input_dir,
        )
        input_paths = _merge_input_paths(primary=input_paths, fallback=generated_paths)
    research_result = run_single_company_research(
        company=identity.company,
        ticker=identity.ticker,
        market=identity.market,
        search_term=identity.search_term,
        pipeline_assets_path=input_paths.pipeline_assets,
        competitors_path=input_paths.competitors,
        financials_path=input_paths.financials,
        valuation_path=input_paths.valuation,
        conference_catalysts_path=input_paths.conference_catalysts,
        target_price_assumptions_path=input_paths.target_price_assumptions,
        include_asset_queries=include_asset_queries,
        max_asset_query_terms=max_asset_query_terms,
        limit=limit,
        output_dir=output_dir,
        save=save,
        client=client,
        now=now,
    )
    missing_inputs = build_missing_inputs(
        identity=identity,
        input_paths=input_paths,
        input_dir=input_dir,
    )
    missing_report_path = None
    if save:
        missing_report_path = write_missing_inputs_report(
            output_dir=output_dir,
            result=research_result,
            identity=identity,
            input_paths=input_paths,
            missing_inputs=missing_inputs,
            auto_inputs=auto_inputs,
        )

    llm_agent_result = None
    resolved_llm_trace_path: Path | None = None
    if llm_agents:
        if llm_client is None:
            raise ValueError(
                "llm_agents was requested but no llm_client was provided; the "
                "CLI layer is responsible for constructing an LLMClient from "
                "environment configuration."
            )
        llm_agent_result, resolved_llm_trace_path = _run_llm_agent_pipeline(
            research_result=research_result,
            identity=identity,
            llm_agents=llm_agents,
            llm_client=llm_client,
            output_dir=output_dir,
            save=save,
            llm_trace_path=llm_trace_path,
            auto_input_artifacts=auto_input_artifacts,
            macro_signals_provider=macro_signals_provider,
        )

    return CompanyReportResult(
        identity=identity,
        input_paths=input_paths,
        missing_inputs=missing_inputs,
        missing_inputs_report=missing_report_path,
        research_result=research_result,
        auto_input_artifacts=auto_input_artifacts,
        llm_agent_result=llm_agent_result,
        llm_trace_path=resolved_llm_trace_path,
    )


SUPPORTED_LLM_AGENTS = (
    "scientific-skeptic",
    "pipeline-triage",
    "financial-triage",
    "macro-context",
)


def _run_llm_agent_pipeline(
    *,
    research_result: SingleCompanyResearchResult,
    identity: CompanyIdentity,
    llm_agents: tuple[str, ...],
    llm_client: Any,
    output_dir: str | Path,
    save: bool,
    llm_trace_path: str | Path | None,
    auto_input_artifacts: Any | None = None,
    macro_signals_provider: Callable[[str], dict[str, Any] | None] | None = None,
) -> tuple[Any, Path | None]:
    """Run the opt-in LLM agent graph over a finished research result."""

    from biotech_alpha.agent_runtime import (
        AgentGraph,
        DeterministicAgent,
    )
    from biotech_alpha.agents import AgentContext
    from biotech_alpha.agents_llm import (
        FinancialTriageLLMAgent,
        MacroContextLLMAgent,
        PipelineTriageLLMAgent,
        ScientificSkepticLLMAgent,
    )

    unknown = [name for name in llm_agents if name not in SUPPORTED_LLM_AGENTS]
    if unknown:
        raise ValueError(
            f"unknown llm_agents: {unknown}. "
            f"supported: {list(SUPPORTED_LLM_AGENTS)}"
        )

    macro_signals: dict[str, Any] | None = None
    if macro_signals_provider is not None and "macro-context" in llm_agents:
        market_label = identity.market or "HK"
        try:
            macro_signals = macro_signals_provider(market_label)
        except Exception:  # noqa: BLE001 - never fail the run on a live feed
            macro_signals = None

    facts = build_llm_agent_facts(
        research_result=research_result,
        auto_input_artifacts=auto_input_artifacts,
        macro_signals=macro_signals,
    )
    context = AgentContext(
        company=identity.company,
        ticker=identity.ticker,
        market=identity.market,
    )

    trace_recorder = getattr(llm_client, "trace", None)
    graph = AgentGraph(trace_recorder=trace_recorder)
    debug_prompt = os.getenv("BIOTECH_ALPHA_LLM_DEBUG_PROMPT", "").strip().lower()
    debug_prompt_enabled = debug_prompt in {"1", "true", "yes", "on"}
    prompt_debug_dir = Path(output_dir) / "traces"
    if debug_prompt_enabled and save:
        prompt_debug_dir.mkdir(parents=True, exist_ok=True)

    def _publish(ctx, store):  # noqa: ANN001 - runtime adapter
        for key, value in facts.items():
            store.put(key, value)
        if debug_prompt_enabled and save:
            store.put(
                "_llm_prompt_debug_dir",
                prompt_debug_dir,
            )
            store.put(
                "_llm_prompt_debug_run_id",
                research_result.run_id,
            )
        return None

    graph.add(DeterministicAgent("publish_research_facts", _publish))
    if "pipeline-triage" in llm_agents:
        graph.add(
            PipelineTriageLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "financial-triage" in llm_agents:
        graph.add(
            FinancialTriageLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "macro-context" in llm_agents:
        graph.add(
            MacroContextLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "scientific-skeptic" in llm_agents:
        # When upstream triage agents are requested, chain the skeptic so
        # the skeptic's FactStore view already contains their payloads.
        # This is a hard dependency in the current runtime: if any declared
        # upstream fails the skeptic is skipped. Callers who want the
        # skeptic to survive a triage failure should run only
        # `--llm-agents scientific-skeptic`.
        skeptic_deps: tuple[str, ...] = ("publish_research_facts",)
        if "pipeline-triage" in llm_agents:
            skeptic_deps = skeptic_deps + ("pipeline_triage_llm_agent",)
        if "financial-triage" in llm_agents:
            skeptic_deps = skeptic_deps + ("financial_triage_llm_agent",)
        if "macro-context" in llm_agents:
            skeptic_deps = skeptic_deps + ("macro_context_llm_agent",)
        graph.add(
            ScientificSkepticLLMAgent(
                llm_client=llm_client,
                depends_on=skeptic_deps,
            )
        )

    result = graph.run(context)

    resolved_trace_path: Path | None = None
    if save and trace_recorder is not None:
        if llm_trace_path is not None:
            resolved_trace_path = Path(llm_trace_path)
        else:
            resolved_trace_path = (
                Path(output_dir) / "traces" / f"{research_result.run_id}.jsonl"
            )
        trace_recorder.path = resolved_trace_path
        trace_recorder.flush()

    if save:
        findings_path = (
            Path(output_dir)
            / "memos"
            / f"{research_result.run_id}_llm_findings.json"
        )
        findings_path.parent.mkdir(parents=True, exist_ok=True)
        findings_path.write_text(
            json.dumps(
                _llm_agent_result_payload(result),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return result, resolved_trace_path


def build_llm_agent_facts(
    *,
    research_result: SingleCompanyResearchResult,
    auto_input_artifacts: Any | None = None,
    macro_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize a research result into the fact-store shape LLM agents expect.

    The LLM adapter layer deliberately accepts only plain dicts/lists/strings
    (and numbers). This keeps prompts reproducible: the same research result
    always renders to the same prompt body regardless of dataclass identity.

    When ``auto_input_artifacts`` is provided, a ``source_text_excerpt`` fact
    is added that carries a short window of the HKEX annual-results text near
    the pipeline area. Downstream agents (e.g. PipelineTriage) use this to
    ground their reasoning in the real source instead of only the parsed
    structured pipeline.
    """

    memo = research_result.memo
    skeptic_risks: list[str] = []
    for finding in memo.findings:
        if finding.agent_name == "scientific_skeptic_agent":
            skeptic_risks.extend(finding.risks)

    pipeline_snapshot = {
        "assets": [
            {
                "name": asset.name,
                "target": asset.target,
                "modality": asset.modality,
                "indication": asset.indication,
                "phase": asset.phase,
                "partner": asset.partner,
                "next_milestone": asset.next_milestone,
            }
            for asset in research_result.pipeline_assets
        ],
    }
    trial_summary = {
        "total": len(research_result.trials),
        "late_stage": sum(
            1
            for trial in research_result.trials
            if trial.phase and ("PHASE3" in trial.phase or "PHASE2" in trial.phase)
        ),
        "active": sum(
            1
            for trial in research_result.trials
            if trial.status
            in {"RECRUITING", "ACTIVE_NOT_RECRUITING", "NOT_YET_RECRUITING"}
        ),
        "asset_trial_matches": len(research_result.asset_trial_matches),
    }
    valuation_snapshot: dict[str, Any] = {}
    if research_result.valuation_snapshot is not None:
        snap = research_result.valuation_snapshot
        valuation_snapshot.update(
            {
                "market_cap": getattr(snap, "market_cap", None),
                "share_price": getattr(snap, "share_price", None),
                "shares_outstanding": getattr(snap, "shares_outstanding", None),
                "cash": getattr(snap, "cash", None),
                "debt": getattr(snap, "debt", None),
                "revenue_ttm": getattr(snap, "revenue_ttm", None),
                "currency": getattr(snap, "currency", None),
            }
        )
    if research_result.valuation_metrics is not None:
        metrics = research_result.valuation_metrics
        valuation_snapshot["enterprise_value"] = getattr(
            metrics, "enterprise_value", None
        )
        valuation_snapshot["ev_to_revenue"] = getattr(
            metrics, "ev_to_revenue", None
        )
    if research_result.cash_runway_estimate is not None:
        runway = research_result.cash_runway_estimate
        valuation_snapshot["cash_runway_months"] = getattr(
            runway, "runway_months", None
        )

    input_warnings: list[str] = []
    for report in research_result.input_validation.values():
        if isinstance(report, dict):
            for warning in report.get("warnings", []) or []:
                input_warnings.append(str(warning))
    financial_warnings: list[str] = []
    financial_report = (
        research_result.input_validation.get("financials")
        if isinstance(research_result.input_validation, dict)
        else None
    )
    if isinstance(financial_report, dict):
        for warning in financial_report.get("warnings", []) or []:
            financial_warnings.append(str(warning))

    source_text_excerpt = _build_source_text_excerpt(
        auto_input_artifacts=auto_input_artifacts,
        pipeline_snapshot=pipeline_snapshot,
    )
    financials_snapshot = _build_financials_snapshot(
        research_result=research_result,
        financial_warnings=financial_warnings,
    )
    macro_context = _build_macro_context(
        research_result=research_result,
        auto_input_artifacts=auto_input_artifacts,
        live_signals=macro_signals,
    )

    return {
        "skeptic_risks": skeptic_risks,
        "pipeline_snapshot": pipeline_snapshot,
        "trial_summary": trial_summary,
        "valuation_snapshot": valuation_snapshot or None,
        "input_warnings": input_warnings,
        "source_text_excerpt": source_text_excerpt,
        "financials_snapshot": financials_snapshot,
        "macro_context": macro_context,
    }


def _build_financials_snapshot(
    *,
    research_result: SingleCompanyResearchResult,
    financial_warnings: list[str],
) -> dict[str, Any] | None:
    """Serialize the financial + runway dataclasses into a plain-dict fact.

    The FinancialTriage LLM agent needs to reason about cash, debt, burn
    rate, and the deterministic runway estimate together, so we pre-compute
    one consolidated dict rather than letting the agent stitch fields from
    two separate facts (``valuation_snapshot`` already exists but skips
    cash-burn / runway method / warning metadata).
    """

    financial = research_result.financial_snapshot
    runway = research_result.cash_runway_estimate
    valuation = research_result.valuation_snapshot
    valuation_metrics = research_result.valuation_metrics

    if financial is None and runway is None and valuation is None:
        return None

    snapshot: dict[str, Any] = {}
    if financial is not None:
        snapshot["financial_snapshot"] = {
            "as_of_date": getattr(financial, "as_of_date", None),
            "currency": getattr(financial, "currency", None),
            "cash_and_equivalents": getattr(
                financial, "cash_and_equivalents", None
            ),
            "short_term_debt": getattr(financial, "short_term_debt", None),
            "quarterly_cash_burn": getattr(
                financial, "quarterly_cash_burn", None
            ),
            "operating_cash_flow_ttm": getattr(
                financial, "operating_cash_flow_ttm", None
            ),
            "source": getattr(financial, "source", None),
            "source_date": getattr(financial, "source_date", None),
        }
    if runway is not None:
        snapshot["runway_estimate"] = {
            "currency": getattr(runway, "currency", None),
            "net_cash": getattr(runway, "net_cash", None),
            "monthly_cash_burn": getattr(runway, "monthly_cash_burn", None),
            "runway_months": getattr(runway, "runway_months", None),
            "method": getattr(runway, "method", None),
            "needs_human_review": getattr(
                runway, "needs_human_review", None
            ),
            "warnings": list(getattr(runway, "warnings", ()) or ()),
        }
    if valuation is not None:
        snapshot["market_snapshot"] = {
            "currency": getattr(valuation, "currency", None),
            "market_cap": getattr(valuation, "market_cap", None),
            "share_price": getattr(valuation, "share_price", None),
            "shares_outstanding": getattr(
                valuation, "shares_outstanding", None
            ),
            "cash": getattr(valuation, "cash", None),
            "debt": getattr(valuation, "debt", None),
            "revenue_ttm": getattr(valuation, "revenue_ttm", None),
        }
    if valuation_metrics is not None:
        snapshot["valuation_metrics"] = {
            "enterprise_value": getattr(
                valuation_metrics, "enterprise_value", None
            ),
            "ev_to_revenue": getattr(
                valuation_metrics, "ev_to_revenue", None
            ),
        }
    snapshot["financial_warnings"] = financial_warnings
    return snapshot


def _build_macro_context(
    *,
    research_result: SingleCompanyResearchResult,
    auto_input_artifacts: Any | None,
    live_signals: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a minimal macro-context fact for the MacroContextLLMAgent.

    When ``live_signals`` is ``None`` the fact is intentionally thin:
    it advertises what the deterministic layer knows (market, sector,
    as-of dates, source publication dates, source types) and exposes a
    ``known_unknowns`` list naming the macro signals the agent would
    benefit from. Agents are expected to return
    ``macro_regime = "insufficient_data"`` when the stub is too thin
    to form a view, rather than hallucinate macro themes.

    When ``live_signals`` is provided (e.g. by a CLI-selected
    ``MacroSignalsProvider`` such as ``hk_macro_signals_yahoo``) the
    dict is attached under a ``live_signals`` key and any
    ``known_unknowns`` entry that the live feed already covers is
    pruned. Fields the live feed still cannot supply (news titles,
    HIBOR, regulatory posture, etc.) remain on ``known_unknowns`` so
    the agent knows what it is still missing.
    """

    context = research_result.context
    market = getattr(context, "market", None) or "HK"
    as_of_date = getattr(context, "as_of_date", None)

    source_publication_dates: list[str] = []
    source_titles: list[str] = []
    source_types: list[str] = []
    if auto_input_artifacts is not None:
        for doc in getattr(auto_input_artifacts, "source_documents", ()) or ():
            if getattr(doc, "publication_date", None):
                source_publication_dates.append(str(doc.publication_date))
            if getattr(doc, "title", None):
                source_titles.append(str(doc.title))
            if getattr(doc, "source_type", None):
                source_types.append(str(doc.source_type))

    financial = research_result.financial_snapshot
    financial_as_of = (
        getattr(financial, "as_of_date", None)
        if financial is not None
        else None
    )

    known_unknowns = [
        "live HSI / HSBIO index trend",
        "Hong Kong IPO sentiment for biotech",
        "US rate environment and USD/HKD peg status",
        "recent sector-relevant news titles",
        "FDA / NMPA regulatory posture this quarter",
    ]
    live_block: dict[str, Any] | None = None
    if live_signals:
        live_block = dict(live_signals)
        if live_block.get("hsi"):
            known_unknowns = [
                item
                for item in known_unknowns
                if "HSI" not in item and "HSBIO" not in item
            ]
        if live_block.get("hkd_usd"):
            known_unknowns = [
                item
                for item in known_unknowns
                if "USD/HKD" not in item and "peg" not in item
            ]

    return {
        "market": market,
        "sector": "biotech",
        "ticker": getattr(context, "ticker", None) or None,
        "company": getattr(context, "company", None) or None,
        "report_run_date": as_of_date,
        "financial_as_of_date": financial_as_of,
        "source_publication_dates": source_publication_dates,
        "source_titles": source_titles,
        "source_types": source_types,
        "live_signals": live_block,
        "known_unknowns": known_unknowns,
    }


def _build_source_text_excerpt(
    *,
    auto_input_artifacts: Any | None,
    pipeline_snapshot: dict[str, Any],
    max_chars: int = 8000,
    per_anchor_window: int = 1600,
) -> dict[str, Any] | None:
    """Return a concatenated multi-anchor excerpt of the source document.

    Earlier versions of this helper anchored only on the first asset that
    appeared in the source text, which left later-listed assets without
    evidence and caused the pipeline-triage agent to mark them
    ``medium [not in excerpt]``. This version now:

    1. walks every asset name from ``pipeline_snapshot`` and records the
       first index at which each name appears in the source text;
    2. expands each hit into a small window of ``per_anchor_window`` chars
       centred on the hit;
    3. merges overlapping windows so adjacent hits share context;
    4. caps the total concatenated excerpt at ``max_chars`` chars so the
       prompt stays predictable.

    When no asset name is found, it falls back to the first ``max_chars``
    of the source text and sets ``anchor_assets`` to an empty list.
    """

    if auto_input_artifacts is None:
        return None
    documents = getattr(auto_input_artifacts, "source_documents", ()) or ()
    if not documents:
        return None
    document = documents[0]
    text_path = getattr(document, "text_path", None)
    if text_path is None:
        return None
    path = Path(text_path)
    if not path.exists():
        return None
    try:
        full_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if not full_text.strip():
        return None

    assets = pipeline_snapshot.get("assets") or []
    half_window = max(200, per_anchor_window // 2)
    hits: list[tuple[int, int, str]] = []
    anchor_assets: list[str] = []
    missing_assets: list[str] = []
    for asset in assets:
        name = (asset.get("name") or "").strip()
        if not name or len(name) < 3:
            continue
        index = full_text.find(name)
        if index == -1:
            missing_assets.append(name)
            continue
        start = max(0, index - half_window)
        end = min(len(full_text), index + half_window)
        hits.append((start, end, name))
        anchor_assets.append(name)

    if not hits:
        excerpt = full_text[:max_chars]
        return {
            "source_type": getattr(document, "source_type", None),
            "title": getattr(document, "title", None),
            "url": getattr(document, "url", None),
            "publication_date": getattr(document, "publication_date", None),
            "anchor_assets": [],
            "missing_assets": missing_assets,
            "total_chars": len(full_text),
            "excerpt_chars": len(excerpt),
            "excerpt": excerpt,
        }

    hits.sort(key=lambda item: item[0])
    merged_windows: list[tuple[int, int]] = []
    for start, end, _ in hits:
        if merged_windows and start <= merged_windows[-1][1]:
            previous_start, previous_end = merged_windows[-1]
            merged_windows[-1] = (previous_start, max(previous_end, end))
        else:
            merged_windows.append((start, end))

    chunks: list[str] = []
    total = 0
    truncated = False
    for start, end in merged_windows:
        if total >= max_chars:
            truncated = True
            break
        available = max_chars - total
        chunk = full_text[start:end]
        if len(chunk) > available:
            chunk = chunk[:available]
            truncated = True
        header = f"[... source ~offset {start} ...]\n"
        chunks.append(header + chunk)
        total += len(chunk) + len(header)

    excerpt = "\n---\n".join(chunks)

    return {
        "source_type": getattr(document, "source_type", None),
        "title": getattr(document, "title", None),
        "url": getattr(document, "url", None),
        "publication_date": getattr(document, "publication_date", None),
        "anchor_assets": anchor_assets,
        "missing_assets": missing_assets,
        "total_chars": len(full_text),
        "excerpt_chars": len(excerpt),
        "excerpt": excerpt,
        "truncated": truncated,
    }


def _llm_agent_result_payload(result: Any) -> dict[str, Any]:
    """Serialize an AgentRunResult to a JSON-friendly dict."""

    return {
        "findings": [
            {
                "agent_name": f.agent_name,
                "summary": f.summary,
                "risks": list(f.risks),
                "confidence": f.confidence,
                "needs_human_review": f.needs_human_review,
                "evidence": [
                    {
                        "claim": ev.claim,
                        "source": ev.source,
                        "confidence": ev.confidence,
                        "is_inferred": ev.is_inferred,
                    }
                    for ev in f.evidence
                ],
            }
            for f in getattr(result, "findings", ())
        ],
        "steps": [
            {
                "agent_name": s.agent_name,
                "ok": s.ok,
                "skipped": s.skipped,
                "error": s.error,
                "latency_ms": s.latency_ms,
                "warnings": list(s.warnings),
            }
            for s in getattr(result, "steps", ())
        ],
        "warnings": list(getattr(result, "warnings", ())),
        "cost_summary": dict(getattr(result, "cost_summary", {}) or {}),
    }


def resolve_company_identity(
    *,
    company: str | None = None,
    ticker: str | None = None,
    market: str | None = None,
    sector: str = "biotech",
    search_term: str | None = None,
    registry_path: str | Path | None = "data/input/company_registry.json",
) -> CompanyIdentity:
    """Resolve company identity from explicit args and an optional registry."""

    clean_company = _clean_text(company)
    clean_ticker = _clean_text(ticker)
    if not clean_company and not clean_ticker:
        raise ValueError("company-report requires --company or --ticker")

    registry_match = _registry_match(
        query=clean_company or clean_ticker or "",
        ticker=clean_ticker,
        registry_path=registry_path,
    )
    if registry_match:
        clean_company = clean_company or _clean_text(registry_match.get("company"))
        clean_ticker = clean_ticker or _clean_text(registry_match.get("ticker"))
        market = market or _clean_text(registry_match.get("market"))
        sector = _clean_text(registry_match.get("sector")) or sector
        search_term = search_term or _clean_text(registry_match.get("search_term"))
        aliases = tuple(
            alias.strip()
            for alias in registry_match.get("aliases", [])
            if isinstance(alias, str) and alias.strip()
        )
        registry_name = _clean_text(registry_match.get("company"))
    else:
        aliases = ()
        registry_name = None

    clean_company = clean_company or clean_ticker
    clean_ticker = clean_ticker or None
    resolved_market = market or _market_from_ticker(clean_ticker) or "HK"
    resolved_search_term = search_term or _best_search_term(clean_company, aliases)
    return CompanyIdentity(
        company=clean_company,
        ticker=clean_ticker,
        market=resolved_market,
        sector=sector,
        search_term=resolved_search_term,
        aliases=aliases,
        registry_match=registry_name,
    )


def discover_company_inputs(
    identity: CompanyIdentity,
    *,
    input_dir: str | Path = "data/input",
) -> CompanyReportInputPaths:
    """Find existing curated input files for a company."""

    root = Path(input_dir)
    if not root.exists():
        return CompanyReportInputPaths()

    files = tuple(path for path in root.rglob("*.json") if path.is_file())
    tokens = _identity_tokens(identity)
    ticker_tokens = _identity_ticker_tokens(identity)
    discovered: dict[str, Path | None] = {}
    for key, suffixes in INPUT_SUFFIXES.items():
        discovered[key] = _select_input_file(
            files=files,
            tokens=tokens,
            ticker_tokens=ticker_tokens,
            suffixes=suffixes,
        )

    return CompanyReportInputPaths(**discovered)


def enrich_identity_from_auto_input_artifacts(
    *,
    identity: CompanyIdentity,
    auto_input_artifacts: Any | None,
) -> CompanyIdentity:
    """Use discovered source metadata to improve aliases and search terms."""

    source_documents = getattr(auto_input_artifacts, "source_documents", ()) or ()
    aliases = list(identity.aliases)
    for document in source_documents:
        stock_name = getattr(document, "stock_name", None)
        for alias in _hkex_stock_name_aliases(stock_name):
            if alias not in aliases and alias != identity.company:
                aliases.append(alias)

    search_term = identity.search_term
    if not _has_ascii_letter(search_term or ""):
        search_term = next(
            (alias for alias in aliases if _has_ascii_letter(alias)),
            search_term,
        )
    if tuple(aliases) == identity.aliases and search_term == identity.search_term:
        return identity
    return replace(
        identity,
        aliases=tuple(aliases),
        search_term=search_term,
    )


def build_missing_inputs(
    *,
    identity: CompanyIdentity,
    input_paths: CompanyReportInputPaths,
    input_dir: str | Path = "data/input",
) -> tuple[MissingInput, ...]:
    """Return missing curated inputs with suggested future paths."""

    root = Path(input_dir)
    slug = _identity_slug(identity)
    missing: list[MissingInput] = []
    for key, spec in MISSING_INPUT_SPECS.items():
        if getattr(input_paths, key) is not None:
            continue
        suggested_path = root / f"{slug}_{key}.json"
        missing.append(
            MissingInput(
                key=key,
                severity=str(spec["severity"]),
                reason=str(spec["reason"]),
                suggested_path=suggested_path,
                next_action=str(spec["next_action"]),
                template_command=_template_command(
                    command=str(spec["template_command"]),
                    identity=identity,
                    output=suggested_path,
                ),
            )
        )
    return tuple(missing)


def write_missing_inputs_report(
    *,
    output_dir: str | Path,
    result: SingleCompanyResearchResult,
    identity: CompanyIdentity,
    input_paths: CompanyReportInputPaths,
    missing_inputs: tuple[MissingInput, ...],
    auto_inputs: bool = False,
) -> Path:
    """Write a report describing missing inputs for the one-command run."""

    if result.artifacts.manifest_json:
        output_path = (
            Path(result.artifacts.manifest_json).parent
            / f"{result.run_id}_missing_inputs_report.json"
        )
    else:
        output_path = (
            Path(output_dir)
            / "processed"
            / "company_report"
            / _identity_slug(identity)
            / f"{result.run_id}_missing_inputs_report.json"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            missing_inputs_payload(
                result=result,
                identity=identity,
                input_paths=input_paths,
                missing_inputs=missing_inputs,
                auto_inputs=auto_inputs,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def missing_inputs_payload(
    *,
    result: SingleCompanyResearchResult,
    identity: CompanyIdentity,
    input_paths: CompanyReportInputPaths,
    missing_inputs: tuple[MissingInput, ...],
    auto_inputs: bool = False,
) -> dict[str, Any]:
    """Return JSON payload for missing-input reports."""

    return {
        "run_id": result.run_id,
        "identity": _jsonable(asdict(identity)),
        "discovered_inputs": _jsonable(asdict(input_paths)),
        "missing_inputs": [_jsonable(asdict(item)) for item in missing_inputs],
        "next_actions": next_actions(
            identity=identity,
            missing_inputs=missing_inputs,
            auto_inputs=auto_inputs,
        ),
        "quality_gate": report_quality_gate(
            result=result,
            missing_inputs=missing_inputs,
        ),
        "rerun_command": company_report_rerun_command(
            identity,
            auto_inputs=auto_inputs,
        ),
        "notes": (
            "The report was generated with available inputs.",
            "Missing high-severity inputs should be filled before relying on "
            "asset-level conclusions.",
            "This keeps the MVP one-command flow compatible with future "
            "automatic source discovery and extraction.",
        ),
    }


def company_report_summary(result: CompanyReportResult) -> dict[str, Any]:
    """Return compact JSON summary for CLI output."""

    auto_inputs = result.auto_input_artifacts is not None
    return {
        "identity": _jsonable(asdict(result.identity)),
        "research": result_summary(result.research_result),
        "discovered_inputs": _jsonable(asdict(result.input_paths)),
        "auto_input_artifacts": _jsonable(
            asdict(result.auto_input_artifacts)
            if result.auto_input_artifacts
            else None
        ),
        "missing_input_count": len(result.missing_inputs),
        "missing_inputs": [_jsonable(asdict(item)) for item in result.missing_inputs],
        "next_actions": next_actions(
            identity=result.identity,
            missing_inputs=result.missing_inputs,
            auto_inputs=auto_inputs,
        ),
        "quality_gate": report_quality_gate(
            result=result.research_result,
            missing_inputs=result.missing_inputs,
        ),
        "rerun_command": company_report_rerun_command(
            result.identity,
            auto_inputs=auto_inputs,
        ),
        "missing_inputs_report": (
            str(result.missing_inputs_report)
            if result.missing_inputs_report
            else None
        ),
        "llm_agents": (
            _llm_agent_result_payload(result.llm_agent_result)
            if result.llm_agent_result is not None
            else None
        ),
        "llm_trace_path": (
            str(result.llm_trace_path) if result.llm_trace_path else None
        ),
    }


def report_quality_gate(
    *,
    result: SingleCompanyResearchResult,
    missing_inputs: tuple[MissingInput, ...],
) -> dict[str, Any]:
    """Summarize whether a company report is decision-ready."""

    high_missing = sum(1 for item in missing_inputs if item.severity == "high")
    medium_missing = sum(1 for item in missing_inputs if item.severity == "medium")
    warning_count = sum(
        len(report.get("warnings", []))
        for report in result.input_validation.values()
        if isinstance(report, dict)
    )
    needs_human_review = any(
        finding.needs_human_review for finding in result.memo.findings
    )
    if high_missing > 0:
        level = "incomplete"
        rationale = "high-severity curated inputs are missing"
    elif needs_human_review or warning_count > 0 or medium_missing > 0:
        level = "research_ready_with_review"
        rationale = "report generated but requires manual review"
    else:
        level = "decision_ready"
        rationale = "required inputs and checks are in acceptable shape"
    return {
        "level": level,
        "rationale": rationale,
        "missing_high_severity_inputs": high_missing,
        "missing_medium_severity_inputs": medium_missing,
        "input_warning_count": warning_count,
        "needs_human_review": needs_human_review,
    }


def _merge_input_paths(
    *,
    primary: CompanyReportInputPaths,
    fallback: CompanyReportInputPaths,
) -> CompanyReportInputPaths:
    return CompanyReportInputPaths(
        pipeline_assets=primary.pipeline_assets or fallback.pipeline_assets,
        financials=primary.financials or fallback.financials,
        competitors=primary.competitors or fallback.competitors,
        valuation=primary.valuation or fallback.valuation,
        conference_catalysts=(
            primary.conference_catalysts or fallback.conference_catalysts
        ),
        target_price_assumptions=(
            primary.target_price_assumptions
            or fallback.target_price_assumptions
        ),
    )


def next_actions(
    *,
    identity: CompanyIdentity,
    missing_inputs: tuple[MissingInput, ...],
    auto_inputs: bool = False,
) -> tuple[str, ...]:
    """Return human-oriented next steps for the current report."""

    if not missing_inputs:
        return (
            "All curated input files were found. Review the memo, manifest, "
            "scorecard, catalysts, and target-price artifacts if present.",
        )

    high_priority = tuple(
        item for item in missing_inputs if item.severity == "high"
    )
    medium_priority = tuple(
        item for item in missing_inputs if item.severity == "medium"
    )
    optional = tuple(item for item in missing_inputs if item.severity == "optional")
    actions: list[str] = []
    if high_priority:
        keys = ", ".join(item.key for item in high_priority)
        actions.append(f"First create and fill high-priority inputs: {keys}.")
    if medium_priority:
        keys = ", ".join(item.key for item in medium_priority)
        actions.append(f"Then add medium-priority context inputs: {keys}.")
    if optional:
        actions.append(
            "Add target-price assumptions after the asset and financial inputs "
            "are source-backed enough for scenario work."
        )
    actions.append(
        "Run each generated template through its validate command before "
        "rerunning company-report."
    )
    actions.append(
        f"Rerun: {company_report_rerun_command(identity, auto_inputs=auto_inputs)}"
    )
    return tuple(actions)


def company_report_rerun_command(
    identity: CompanyIdentity,
    *,
    auto_inputs: bool = False,
) -> str:
    """Return the one-command rerun command for an identity."""

    parts = [
        "PYTHONPATH=src",
        "python3",
        "-m",
        "biotech_alpha.cli",
        "company-report",
        "--company",
        _quote(identity.company),
    ]
    if identity.ticker:
        parts.extend(("--ticker", _quote(identity.ticker)))
    if identity.market:
        parts.extend(("--market", _quote(identity.market)))
    if auto_inputs:
        parts.append("--auto-inputs")
    return " ".join(parts)


def _registry_match(
    *,
    query: str,
    ticker: str | None,
    registry_path: str | Path | None,
) -> dict[str, Any] | None:
    if not registry_path:
        return None
    path = Path(registry_path)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("companies") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return None

    query_key = _match_key(query)
    ticker_key = _match_key(ticker or "")
    for row in rows:
        if not isinstance(row, dict):
            continue
        values = (
            row.get("company"),
            row.get("ticker"),
            row.get("search_term"),
            *(row.get("aliases") or []),
        )
        keys = {_match_key(value) for value in values if isinstance(value, str)}
        if query_key in keys or (ticker_key and ticker_key in keys):
            return row
    return None


def _select_input_file(
    *,
    files: tuple[Path, ...],
    tokens: tuple[str, ...],
    ticker_tokens: tuple[str, ...],
    suffixes: tuple[str, ...],
) -> Path | None:
    candidates = []
    for path in files:
        stem = _match_key(path.stem)
        if not any(suffix in stem for suffix in suffixes):
            continue
        if not tokens or not any(token in stem for token in tokens):
            continue
        if ticker_tokens and not all(token in stem for token in ticker_tokens):
            continue
        candidates.append(path)
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (len(str(item)), str(item)))[0]


def _identity_tokens(identity: CompanyIdentity) -> tuple[str, ...]:
    values = (
        identity.company,
        identity.ticker or "",
        identity.search_term or "",
        *identity.aliases,
    )
    tokens: list[str] = []
    for value in values:
        match_key = _match_key(value)
        if len(match_key) >= 2:
            tokens.append(match_key)
        for token in re.split(r"[^0-9a-zA-Z]+", value.lower()):
            if len(token) >= 2:
                tokens.append(token)
    return tuple(dict.fromkeys(tokens))


def _identity_ticker_tokens(identity: CompanyIdentity) -> tuple[str, ...]:
    ticker = (identity.ticker or "").strip().lower()
    if not ticker:
        return ()
    tokens = [
        token
        for token in re.split(r"[^0-9a-zA-Z]+", ticker)
        if len(token) >= 2 and any(character.isdigit() for character in token)
    ]
    return tuple(tokens)


def _identity_slug(identity: CompanyIdentity) -> str:
    value = identity.ticker or identity.company
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "company"


def _best_search_term(company: str, aliases: tuple[str, ...]) -> str:
    for value in (company, *aliases):
        if _has_ascii_letter(value):
            return value
    return company


def _hkex_stock_name_aliases(value: Any) -> tuple[str, ...]:
    stock_name = _clean_text(value)
    if not stock_name:
        return ()
    normalized = re.sub(r"-(?:B|W|SW|S)$", "", stock_name, flags=re.IGNORECASE)
    aliases = []
    if normalized and normalized != stock_name:
        aliases.append(normalized)
    aliases.append(stock_name)
    return tuple(dict.fromkeys(aliases))


def _has_ascii_letter(value: str) -> bool:
    return any("a" <= character.lower() <= "z" for character in value)


def _market_from_ticker(ticker: str | None) -> str | None:
    if not ticker:
        return None
    upper = ticker.upper()
    if upper.endswith(".HK"):
        return "HK"
    if upper.endswith(".SS") or upper.endswith(".SZ"):
        return "CN_A"
    if "." not in upper:
        return "US"
    return None


def _match_key(value: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", value.lower())


def _clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _template_command(
    *,
    command: str,
    identity: CompanyIdentity,
    output: Path,
) -> str:
    parts = [
        "PYTHONPATH=src",
        "python3",
        "-m",
        "biotech_alpha.cli",
        command,
        "--company",
        _quote(identity.company),
    ]
    if identity.ticker:
        parts.extend(("--ticker", _quote(identity.ticker)))
    parts.extend(("--output", _quote(str(output)), "--force"))
    return " ".join(parts)


def _quote(value: str) -> str:
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
