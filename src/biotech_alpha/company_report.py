"""One-command company report orchestration."""

from __future__ import annotations

import json
import os
import re
import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from biotech_alpha.hkexnews import (
    fetch_hkex_rss,
    filter_hkex_items_by_ticker,
    parse_hkex_rss,
    track_hkex_news_updates,
    typed_items_to_catalyst_rows,
    typed_items_to_event_impact_suggestions,
    suggest_expected_dilution_pct,
)
from biotech_alpha.china_cde import (
    fetch_cde_feed,
    filter_cde_items,
    parse_cde_feed,
    track_cde_updates,
)
from biotech_alpha.research import (
    ClinicalTrialsSource,
    SingleCompanyResearchResult,
    memo_to_markdown,
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
    report_quality_path: Path | None = None
    valuation_pod_path: Path | None = None
    decision_log_path: Path | None = None
    hkexnews_updates_path: Path | None = None
    cde_updates_path: Path | None = None
    hkexnews_event_impacts_path: Path | None = None
    hkexnews_dilution_hint_path: Path | None = None
    peer_valuation_path: Path | None = None


INPUT_SUFFIXES = {
    "pipeline_assets": ("pipeline_assets", "pipeline"),
    "financials": ("financials", "financial"),
    "competitors": ("competitors", "competitor"),
    "valuation": ("valuation",),
    "conference_catalysts": ("conference_catalysts", "conference"),
    "target_price_assumptions": ("target_price_assumptions", "target_price"),
}

_BUILTIN_IDENTITY_OVERRIDES: tuple[dict[str, Any], ...] = (
    {
        "company": "映恩生物",
        "ticker": "09606.HK",
        "market": "HK",
        "search_term": "DualityBio",
        "aliases": ("DualityBio", "Duality", "映恩"),
    },
)

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
    competitor_discovery_client: ClinicalTrialsSource | None = None,
    competitor_discovery_max_requests: int = 3,
    include_asset_queries: bool = True,
    max_asset_query_terms: int = 20,
    limit: int = 20,
    save: bool = True,
    client: ClinicalTrialsSource | None = None,
    now: datetime | None = None,
    llm_agents: tuple[str, ...] = (),
    llm_client: Any | None = None,
    llm_trace_path: str | Path | None = None,
    macro_signals_provider: Callable[[str], dict[str, Any] | None]
    | None = None,
    technical_features_provider: Callable[
        [CompanyIdentity], dict[str, Any] | None
    ]
    | None = None,
    hkexnews_feed_url: str | None = None,
    hkexnews_feed_file: str | Path | None = None,
    hkexnews_state_file: str | Path = "data/cache/hkexnews/seen_guids.json",
    cde_feed_url: str | None = None,
    cde_feed_file: str | Path | None = None,
    cde_state_file: str | Path = "data/cache/cde/seen_guids.json",
    cde_query: str | None = None,
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
                competitor_discovery_client=competitor_discovery_client,
                competitor_discovery_max_requests=(
                    competitor_discovery_max_requests
                ),
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
            technical_features_provider=technical_features_provider,
        )
        if save:
            write_llm_memo_addendum(
                research_result=research_result,
                llm_agent_result=llm_agent_result,
                llm_trace_path=resolved_llm_trace_path,
                output_dir=output_dir,
            )

    report_result = CompanyReportResult(
        identity=identity,
        input_paths=input_paths,
        missing_inputs=missing_inputs,
        missing_inputs_report=missing_report_path,
        research_result=research_result,
        auto_input_artifacts=auto_input_artifacts,
        llm_agent_result=llm_agent_result,
        llm_trace_path=resolved_llm_trace_path,
    )
    if save and (hkexnews_feed_url or hkexnews_feed_file):
        report_result = write_hkexnews_updates_report(
            output_dir=output_dir,
            result=report_result,
            feed_url=hkexnews_feed_url,
            feed_file=hkexnews_feed_file,
            state_file=hkexnews_state_file,
        )
    if save and (cde_feed_url or cde_feed_file):
        report_result = write_cde_updates_report(
            output_dir=output_dir,
            result=report_result,
            feed_url=cde_feed_url,
            feed_file=cde_feed_file,
            state_file=cde_state_file,
            query=cde_query or result.identity.company,
        )
    if save:
        report_result = write_extraction_audit_report(
            output_dir=output_dir,
            result=report_result,
        )
    if save and llm_agent_result is not None:
        report_result = write_stage_a_llm_reports(
            output_dir=output_dir,
            result=report_result,
        )
    return report_result


def write_llm_memo_addendum(
    *,
    research_result: SingleCompanyResearchResult,
    llm_agent_result: Any,
    llm_trace_path: Path | None,
    output_dir: str | Path,
) -> Path | None:
    """Rewrite the saved markdown memo with merged LLM sections + metadata."""

    memo_path = research_result.artifacts.memo_markdown
    if memo_path is None:
        return None

    memo_path.parent.mkdir(parents=True, exist_ok=True)
    llm_findings = tuple(getattr(llm_agent_result, "findings", ()) or ())
    llm_facts = getattr(llm_agent_result, "facts", {}) or {}
    report_quality_payload = (
        llm_facts.get("report_quality_payload")
        if isinstance(llm_facts, dict)
        else None
    )
    report_synthesizer_payload = (
        llm_facts.get("report_synthesizer_payload")
        if isinstance(llm_facts, dict)
        else None
    )
    base = memo_to_markdown(
        research_result.memo,
        llm_findings=llm_findings,
        report_quality_payload=(
            report_quality_payload
            if isinstance(report_quality_payload, dict)
            else None
        ),
        report_synthesizer_payload=(
            report_synthesizer_payload
            if isinstance(report_synthesizer_payload, dict)
            else None
        ),
    ).rstrip()
    addendum = llm_memo_addendum_markdown(
        llm_agent_result,
        llm_trace_path=llm_trace_path,
        output_dir=output_dir,
    )
    memo_path.write_text(f"{base}\n\n{addendum}\n", encoding="utf-8")
    return memo_path


def llm_memo_addendum_markdown(
    llm_agent_result: Any,
    *,
    llm_trace_path: Path | None = None,
    output_dir: str | Path = "data",
) -> str:
    """Render metadata-only LLM run status appendix."""

    findings = tuple(getattr(llm_agent_result, "findings", ()) or ())
    steps = tuple(getattr(llm_agent_result, "steps", ()) or ())
    warnings = tuple(getattr(llm_agent_result, "warnings", ()) or ())
    cost_summary = dict(getattr(llm_agent_result, "cost_summary", {}) or {})
    ok_steps = sum(1 for step in steps if getattr(step, "ok", False))
    failed_steps = sum(
        1
        for step in steps
        if getattr(step, "error", None) and not getattr(step, "skipped", False)
    )
    skipped_steps = sum(1 for step in steps if getattr(step, "skipped", False))

    lines = [
        "## LLM Agent 附录",
        "",
        (
            f"- 运行状态：{ok_steps}/{len(steps)} 步成功，"
            f"{failed_steps} 步失败，{skipped_steps} 步跳过。"
        ),
    ]
    total_tokens = cost_summary.get("total_tokens")
    calls = cost_summary.get("calls")
    if total_tokens is not None:
        call_label = f" across {calls} call(s)" if calls is not None else ""
        lines.append(f"- LLM 总 token：{total_tokens}{call_label}。")
    if llm_trace_path is not None:
        lines.append(f"- 追踪文件：{_display_path(llm_trace_path, output_dir)}")
    lines.extend(
        [
            "- 以下结论由模型生成，默认需人工复核。",
            "",
        ]
    )

    high_conf = sum(1 for finding in findings if finding.confidence >= 0.3)
    low_conf = sum(1 for finding in findings if finding.confidence < 0.3)
    lines.append(
        "- Findings merged into main memo sections when confidence >= 0.30."
    )
    lines.append(f"- High-confidence findings merged: {high_conf}.")
    lines.append(f"- Low-confidence findings kept out of main sections: {low_conf}.")

    failing_steps = [
        step
        for step in steps
        if getattr(step, "error", None) or getattr(step, "skipped", False)
    ]
    if failing_steps:
        lines.extend(["", "### LLM Step Issues", ""])
        for step in failing_steps:
            status = "skipped" if getattr(step, "skipped", False) else "failed"
            error = str(getattr(step, "error", "") or "no error detail")
            lines.append(
                f"- {_llm_agent_label(getattr(step, 'agent_name', 'agent'))}: "
                f"{status}: {_one_line(error)}"
            )

    if warnings:
        lines.extend(["", "### LLM Warnings", ""])
        for warning in warnings[:10]:
            lines.append(f"- {_one_line(str(warning))}")
        if len(warnings) > 10:
            lines.append(f"- ... {len(warnings) - 10} more warning(s)")

    return "\n".join(lines)


def _llm_agent_label(agent_name: str) -> str:
    text = agent_name
    if text.endswith("_llm_agent"):
        text = text[: -len("_llm_agent")]
    text = text.replace("_", " ").strip()
    return (text.title() if text else "LLM Agent") + " LLM"


def _display_path(path: Path, output_dir: str | Path) -> str:
    try:
        return str(path.relative_to(Path(output_dir)))
    except ValueError:
        return str(path)


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


SUPPORTED_LLM_AGENTS = (
    "provisional-pipeline",
    "provisional-financial",
    "scientific-skeptic",
    "pipeline-triage",
    "financial-triage",
    "competition-triage",
    "strategic-economics",
    "catalyst",
    "data-collector",
    "macro-context",
    "market-regime-timing",
    "market-expectations",
    "decision-debate",
    "investment-thesis",
    "report-synthesizer",
    "valuation-specialist",
    "valuation-commercial",
    "valuation-rnpv",
    "valuation-balance-sheet",
    "valuation-committee",
    "report-quality",
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
    technical_features_provider: Callable[
        [CompanyIdentity], dict[str, Any] | None
    ]
    | None = None,
) -> tuple[Any, Path | None]:
    """Run the opt-in LLM agent graph over a finished research result."""

    from biotech_alpha.agent_runtime import (
        AgentGraph,
        DeterministicAgent,
    )
    from biotech_alpha.agents import AgentContext
    from biotech_alpha.agents_llm import (
        CatalystLLMAgent,
        CompetitionTriageLLMAgent,
        DataCollectorLLMAgent,
        DecisionDebateLLMAgent,
        FinancialTriageLLMAgent,
        InvestmentThesisLLMAgent,
        MacroContextLLMAgent,
        MarketExpectationsLLMAgent,
        MarketRegimeTimingLLMAgent,
        PipelineTriageLLMAgent,
        ProvisionalFinancialLLMAgent,
        ProvisionalPipelineLLMAgent,
        ReportQualityLLMAgent,
        ReportSynthesizerLLMAgent,
        ScientificSkepticLLMAgent,
        StrategicEconomicsLLMAgent,
        ValuationBalanceSheetLLMAgent,
        ValuationCommercialLLMAgent,
        ValuationCommitteeLLMAgent,
        ValuationPipelineRnpvLLMAgent,
        ValuationSpecialistLLMAgent,
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

    technical_features: dict[str, Any] | None = None
    if (
        technical_features_provider is not None
        and (
            "market-regime-timing" in llm_agents
            or "market-expectations" in llm_agents
        )
    ):
        try:
            technical_features = technical_features_provider(identity)
        except Exception:  # noqa: BLE001 - live/history feeds are optional
            technical_features = None

    prior_decision_logs = None
    if "decision-debate" in llm_agents:
        prior_decision_logs = _load_prior_decision_logs(
            output_dir=output_dir,
            identity=identity,
            current_run_id=research_result.run_id,
        )

    facts = build_llm_agent_facts(
        research_result=research_result,
        auto_input_artifacts=auto_input_artifacts,
        macro_signals=macro_signals,
        technical_features=technical_features,
        prior_decision_logs=prior_decision_logs,
    )
    context = AgentContext(
        company=identity.company,
        ticker=identity.ticker,
        market=identity.market,
        as_of_date=_run_date_from_run_id(research_result.run_id),
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
    if "provisional-pipeline" in llm_agents:
        graph.add(
            ProvisionalPipelineLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "provisional-financial" in llm_agents:
        graph.add(
            ProvisionalFinancialLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
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
    if "competition-triage" in llm_agents:
        graph.add(
            CompetitionTriageLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "strategic-economics" in llm_agents:
        strategic_deps = ["publish_research_facts"]
        if "pipeline-triage" in llm_agents:
            strategic_deps.append("pipeline_triage_llm_agent")
        if "competition-triage" in llm_agents:
            strategic_deps.append("competition_triage_llm_agent")
        graph.add(
            StrategicEconomicsLLMAgent(
                llm_client=llm_client,
                depends_on=tuple(strategic_deps),
            )
        )
    if "catalyst" in llm_agents:
        catalyst_deps = ["publish_research_facts"]
        if "pipeline-triage" in llm_agents:
            catalyst_deps.append("pipeline_triage_llm_agent")
        if "strategic-economics" in llm_agents:
            catalyst_deps.append("strategic_economics_llm_agent")
        graph.add(
            CatalystLLMAgent(
                llm_client=llm_client,
                depends_on=tuple(catalyst_deps),
            )
        )
    if "data-collector" in llm_agents:
        graph.add(
            DataCollectorLLMAgent(
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
    if "market-regime-timing" in llm_agents:
        timing_deps = ["publish_research_facts"]
        if "macro-context" in llm_agents:
            timing_deps.append("macro_context_llm_agent")
        graph.add(
            MarketRegimeTimingLLMAgent(
                llm_client=llm_client,
                depends_on=tuple(timing_deps),
            )
        )
    if "market-expectations" in llm_agents:
        expectations_deps = ["publish_research_facts"]
        if "strategic-economics" in llm_agents:
            expectations_deps.append("strategic_economics_llm_agent")
        if "catalyst" in llm_agents:
            expectations_deps.append("catalyst_llm_agent")
        if "valuation-committee" in llm_agents:
            expectations_deps.append("valuation_committee_llm_agent")
        if "market-regime-timing" in llm_agents:
            expectations_deps.append("market_regime_timing_llm_agent")
        elif "macro-context" in llm_agents:
            expectations_deps.append("macro_context_llm_agent")
        graph.add(
            MarketExpectationsLLMAgent(
                llm_client=llm_client,
                depends_on=tuple(dict.fromkeys(expectations_deps)),
            )
        )
    if "decision-debate" in llm_agents:
        debate_deps = ["publish_research_facts"]
        for requested, agent_name in (
            ("data-collector", "data_collector_llm_agent"),
            ("strategic-economics", "strategic_economics_llm_agent"),
            ("catalyst", "catalyst_llm_agent"),
            ("valuation-commercial", "valuation_commercial_llm_agent"),
            ("valuation-rnpv", "valuation_rnpv_llm_agent"),
            ("valuation-balance-sheet", "valuation_balance_sheet_llm_agent"),
            ("valuation-committee", "valuation_committee_llm_agent"),
            ("market-regime-timing", "market_regime_timing_llm_agent"),
            ("market-expectations", "market_expectations_llm_agent"),
        ):
            if requested in llm_agents:
                debate_deps.append(agent_name)
        graph.add(
            DecisionDebateLLMAgent(
                llm_client=llm_client,
                depends_on=tuple(dict.fromkeys(debate_deps)),
            )
        )
    if "scientific-skeptic" in llm_agents:
        graph.add(
            ScientificSkepticLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "investment-thesis" in llm_agents:
        graph.add(
            InvestmentThesisLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "report-synthesizer" in llm_agents:
        synthesizer_deps = ["publish_research_facts"]
        for requested, agent_name in (
            ("scientific-skeptic", "scientific_skeptic_llm_agent"),
            ("investment-thesis", "investment_thesis_llm_agent"),
            ("data-collector", "data_collector_llm_agent"),
            ("strategic-economics", "strategic_economics_llm_agent"),
            ("catalyst", "catalyst_llm_agent"),
            ("market-expectations", "market_expectations_llm_agent"),
            ("market-regime-timing", "market_regime_timing_llm_agent"),
            ("valuation-committee", "valuation_committee_llm_agent"),
            ("decision-debate", "decision_debate_llm_agent"),
        ):
            if requested in llm_agents:
                synthesizer_deps.append(agent_name)
        graph.add(
            ReportSynthesizerLLMAgent(
                llm_client=llm_client,
                depends_on=tuple(dict.fromkeys(synthesizer_deps)),
            )
        )
    if "valuation-specialist" in llm_agents:
        graph.add(
            ValuationSpecialistLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "valuation-commercial" in llm_agents:
        graph.add(
            ValuationCommercialLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "valuation-rnpv" in llm_agents:
        graph.add(
            ValuationPipelineRnpvLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "valuation-balance-sheet" in llm_agents:
        graph.add(
            ValuationBalanceSheetLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
            )
        )
    if "valuation-committee" in llm_agents:
        committee_deps = ["publish_research_facts"]
        if "strategic-economics" in llm_agents:
            committee_deps.append("strategic_economics_llm_agent")
        if "catalyst" in llm_agents:
            committee_deps.append("catalyst_llm_agent")
        if "valuation-commercial" in llm_agents:
            committee_deps.append("valuation_commercial_llm_agent")
        if "valuation-rnpv" in llm_agents:
            committee_deps.append("valuation_rnpv_llm_agent")
        if "valuation-balance-sheet" in llm_agents:
            committee_deps.append("valuation_balance_sheet_llm_agent")
        graph.add(
            ValuationCommitteeLLMAgent(
                llm_client=llm_client,
                depends_on=tuple(committee_deps),
            )
        )
    if "report-quality" in llm_agents:
        quality_deps = ["publish_research_facts"]
        if "scientific-skeptic" in llm_agents:
            quality_deps.append("scientific_skeptic_llm_agent")
        if "investment-thesis" in llm_agents:
            quality_deps.append("investment_thesis_llm_agent")
        if "report-synthesizer" in llm_agents:
            quality_deps.append("report_synthesizer_llm_agent")
        if "valuation-specialist" in llm_agents:
            quality_deps.append("valuation_specialist_llm_agent")
        if "strategic-economics" in llm_agents:
            quality_deps.append("strategic_economics_llm_agent")
        if "catalyst" in llm_agents:
            quality_deps.append("catalyst_llm_agent")
        if "data-collector" in llm_agents:
            quality_deps.append("data_collector_llm_agent")
        if "valuation-commercial" in llm_agents:
            quality_deps.append("valuation_commercial_llm_agent")
        if "valuation-rnpv" in llm_agents:
            quality_deps.append("valuation_rnpv_llm_agent")
        if "valuation-balance-sheet" in llm_agents:
            quality_deps.append("valuation_balance_sheet_llm_agent")
        if "valuation-committee" in llm_agents:
            quality_deps.append("valuation_committee_llm_agent")
        if "market-regime-timing" in llm_agents:
            quality_deps.append("market_regime_timing_llm_agent")
        if "market-expectations" in llm_agents:
            quality_deps.append("market_expectations_llm_agent")
        if "decision-debate" in llm_agents:
            quality_deps.append("decision_debate_llm_agent")
        graph.add(
            ReportQualityLLMAgent(
                llm_client=llm_client,
                depends_on=tuple(dict.fromkeys(quality_deps)),
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
    technical_features: dict[str, Any] | None = None,
    prior_decision_logs: dict[str, Any] | None = None,
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
                "cash": getattr(snap, "cash_and_equivalents", None),
                "debt": getattr(snap, "total_debt", None),
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
    market_sentiment = _build_market_sentiment_payload(
        macro_context=macro_context,
        technical_features=technical_features,
    )
    competition_snapshot = _build_competition_snapshot(
        research_result=research_result
    )
    fallback_context = _build_fallback_context(
        research_result=research_result,
        auto_input_artifacts=auto_input_artifacts,
    )

    return {
        "skeptic_risks": skeptic_risks,
        "pipeline_snapshot": pipeline_snapshot,
        "trial_summary": trial_summary,
        "valuation_snapshot": valuation_snapshot or None,
        "input_warnings": input_warnings,
        "input_validation_payload": dict(research_result.input_validation or {}),
        "source_text_excerpt": source_text_excerpt,
        "financials_snapshot": financials_snapshot,
        "competition_snapshot": competition_snapshot,
        "macro_context": macro_context,
        "technical_feature_payload": technical_features,
        "market_sentiment_payload": market_sentiment,
        "prior_decision_logs_payload": prior_decision_logs,
        "catalyst_calendar_payload": _build_catalyst_calendar_payload(
            research_result
        ),
        "event_impact_payload": _build_event_impact_payload(research_result),
        "fallback_context": fallback_context,
        "target_price_snapshot": _build_target_price_snapshot(research_result),
        "scorecard_summary": _build_scorecard_summary(research_result),
        "memo_scaffold_payload": _build_memo_scaffold_payload(research_result),
        "memo_review_payload": _build_memo_review_payload(research_result),
    }


def _build_memo_scaffold_payload(
    research_result: SingleCompanyResearchResult,
) -> dict[str, Any]:
    memo = research_result.memo
    context = getattr(research_result, "context", None)
    key_assets = getattr(memo, "key_assets", ()) or ()
    catalysts = getattr(memo, "catalysts", ()) or ()
    return {
        "company": getattr(memo, "company", None)
        or getattr(context, "company", None),
        "ticker": getattr(memo, "ticker", None) or getattr(context, "ticker", None),
        "market": getattr(memo, "market", None) or getattr(context, "market", None),
        "decision": getattr(memo, "decision", None),
        "deterministic_summary": getattr(memo, "summary", None),
        "bull_case": list(getattr(memo, "bull_case", ()) or ()),
        "bear_case": list(getattr(memo, "bear_case", ()) or ()),
        "key_assets": [
            {
                "name": asset.name,
                "target": asset.target,
                "indication": asset.indication,
                "phase": asset.phase,
                "next_milestone": asset.next_milestone,
                "next_binary_event": asset.next_binary_event,
            }
            for asset in key_assets[:5]
        ],
        "catalyst_count": len(catalysts),
        "finding_summaries": [
            {
                "agent_name": finding.agent_name,
                "summary": finding.summary,
                "confidence": finding.confidence,
                "needs_human_review": finding.needs_human_review,
            }
            for finding in (getattr(memo, "findings", ()) or ())[:20]
        ],
        "follow_up_questions": list(
            getattr(memo, "follow_up_questions", ()) or ()
        ),
    }


def _build_memo_review_payload(
    research_result: SingleCompanyResearchResult,
    *,
    max_chars: int = 7000,
) -> dict[str, Any] | None:
    memo = getattr(research_result, "memo", None)
    if memo is None:
        return None

    try:
        markdown = memo_to_markdown(memo)
        render_mode = "deterministic_markdown"
    except (AttributeError, TypeError, ValueError):
        markdown = _fallback_memo_review_markdown(memo)
        render_mode = "fallback_fields"

    excerpt = markdown[:max_chars]
    headings = [
        line.strip()
        for line in markdown.splitlines()
        if line.startswith("#")
    ][:20]
    return {
        "available": bool(excerpt.strip()),
        "render_mode": render_mode,
        "markdown_chars": len(markdown),
        "excerpt_chars": len(excerpt),
        "truncated": len(markdown) > max_chars,
        "section_headings": headings,
        "decision": str(getattr(memo, "decision", "") or ""),
        "summary": str(getattr(memo, "summary", "") or ""),
        "markdown_excerpt": excerpt,
    }


def _fallback_memo_review_markdown(memo: Any) -> str:
    lines = [
        f"# {getattr(memo, 'company', None) or 'Unknown'} 研究报告",
        "",
        f"- 代码: {getattr(memo, 'ticker', None) or '未识别'}",
        f"- 市场: {getattr(memo, 'market', None) or 'unknown'}",
        f"- 结论: `{getattr(memo, 'decision', None) or 'unknown'}`",
        "",
        "## 执行结论",
        "",
        str(getattr(memo, "summary", "") or ""),
    ]
    for section, attr in (
        ("看多驱动", "bull_case"),
        ("看空驱动", "bear_case"),
        ("后续问题", "follow_up_questions"),
    ):
        values = [
            str(item).strip()
            for item in (getattr(memo, attr, ()) or ())
            if str(item).strip()
        ]
        if not values:
            continue
        lines.extend(["", f"## {section}", ""])
        lines.extend(f"- {item}" for item in values[:8])
    lines.append("")
    return "\n".join(lines)


def _build_catalyst_calendar_payload(
    research_result: SingleCompanyResearchResult,
) -> dict[str, Any] | None:
    memo = getattr(research_result, "memo", None)
    catalysts = getattr(memo, "catalysts", ()) if memo is not None else ()
    if not catalysts:
        return None
    rows: list[dict[str, Any]] = []
    for catalyst in catalysts:
        evidence_rows = []
        for evidence in getattr(catalyst, "evidence", ()) or ():
            evidence_rows.append(
                {
                    "claim": getattr(evidence, "claim", None),
                    "source": getattr(evidence, "source", None),
                    "source_date": getattr(evidence, "source_date", None),
                    "confidence": getattr(evidence, "confidence", None),
                    "is_inferred": getattr(evidence, "is_inferred", None),
                }
            )
        rows.append(
            {
                "title": getattr(catalyst, "title", None),
                "category": getattr(catalyst, "category", None),
                "expected_date": (
                    catalyst.expected_date.isoformat()
                    if getattr(catalyst, "expected_date", None)
                    else None
                ),
                "expected_window": getattr(catalyst, "expected_window", None),
                "related_asset": getattr(catalyst, "related_asset", None),
                "confidence": getattr(catalyst, "confidence", None),
                "evidence": evidence_rows,
            }
        )
    return {"catalysts": rows, "count": len(rows)}


def _build_event_impact_payload(
    research_result: SingleCompanyResearchResult,
) -> dict[str, Any] | None:
    assumptions = getattr(research_result, "target_price_assumptions", None)
    analysis = getattr(research_result, "target_price_analysis", None)
    event_impacts = (
        list(getattr(assumptions, "event_impacts", ()) or ())
        if assumptions is not None
        else []
    )
    if not event_impacts and analysis is None:
        return None
    payload: dict[str, Any] = {
        "event_impacts": [asdict(item) for item in event_impacts],
    }
    if analysis is not None:
        payload.update(
            {
                "as_of_date": getattr(analysis, "as_of_date", None),
                "currency": getattr(analysis, "currency", None),
                "pre_event_equity_value": getattr(
                    analysis, "pre_event_equity_value", None
                ),
                "post_event_base_equity_value": getattr(
                    getattr(analysis, "base", None), "equity_value", None
                ),
                "event_value_delta": getattr(analysis, "event_value_delta", None),
                "asset_value_delta": getattr(analysis, "asset_value_delta", None),
                "key_drivers": list(getattr(analysis, "key_drivers", ()) or ()),
                "needs_human_review": getattr(
                    analysis, "needs_human_review", None
                ),
            }
        )
    return payload


def _build_fallback_context(
    *,
    research_result: SingleCompanyResearchResult,
    auto_input_artifacts: Any | None,
) -> dict[str, Any]:
    """Build broad context for LLM fallback when structured facts are thin."""

    memo_evidence = getattr(research_result.memo, "evidence", ()) or ()
    evidence_rows = [
        {
            "claim": evidence.claim,
            "source": evidence.source,
            "source_date": evidence.source_date,
            "confidence": evidence.confidence,
            "is_inferred": evidence.is_inferred,
        }
        for evidence in memo_evidence[:20]
    ]
    trial_rows = [
        {
            "registry_id": trial.registry_id,
            "title": trial.title,
            "status": trial.status,
            "phase": trial.phase,
            "conditions": list(trial.conditions),
            "interventions": list(trial.interventions),
            "primary_completion_date": trial.primary_completion_date,
        }
        for trial in (research_result.trials or ())[:25]
    ]
    source_docs = []
    if auto_input_artifacts is not None:
        for doc in getattr(auto_input_artifacts, "source_documents", ()) or ():
            source_docs.append(
                {
                    "title": getattr(doc, "title", None),
                    "url": getattr(doc, "url", None),
                    "source_type": getattr(doc, "source_type", None),
                    "publication_date": getattr(doc, "publication_date", None),
                }
            )
    return {
        "trial_rows": trial_rows,
        "evidence_rows": evidence_rows,
        "source_documents": source_docs[:20],
        "input_validation": dict(research_result.input_validation or {}),
    }


def _run_date_from_run_id(run_id: str) -> str | None:
    try:
        return datetime.strptime(run_id[:8], "%Y%m%d").date().isoformat()
    except (TypeError, ValueError):
        return None


def _build_competition_snapshot(
    *, research_result: SingleCompanyResearchResult
) -> dict[str, Any] | None:
    """Serialize competitor assets and deterministic matches for LLM review."""

    competitors = getattr(research_result, "competitor_assets", ()) or ()
    matches = getattr(research_result, "competitive_matches", ()) or ()
    if not competitors and not matches:
        return None

    return {
        "competitor_assets": [
            {
                "company": item.company,
                "asset_name": item.asset_name,
                "target": item.target,
                "mechanism": item.mechanism,
                "indication": item.indication,
                "phase": item.phase,
                "geography": item.geography,
                "differentiation": item.differentiation,
            }
            for item in competitors
        ],
        "competitive_matches": [
            {
                "asset_name": item.asset_name,
                "competitor_company": item.competitor_company,
                "competitor_asset": item.competitor_asset,
                "match_scope": item.match_scope,
                "confidence": item.confidence,
            }
            for item in matches
        ],
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
            "cash": getattr(valuation, "cash_and_equivalents", None),
            "debt": getattr(valuation, "total_debt", None),
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
        "live HSI index trend",
        "live HSBIO index trend",
        "HIBOR tenor levels",
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
                if "HSI index" not in item
            ]
        if live_block.get("hsbio"):
            known_unknowns = [
                item for item in known_unknowns if "HSBIO" not in item
            ]
        if live_block.get("hkd_usd"):
            known_unknowns = [
                item
                for item in known_unknowns
                if "USD/HKD" not in item and "peg" not in item
            ]
        if live_block.get("hibor"):
            known_unknowns = [
                item for item in known_unknowns if "HIBOR" not in item
            ]
        if live_block.get("news"):
            known_unknowns = [
                item for item in known_unknowns if "news titles" not in item
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


def _build_market_sentiment_payload(
    *,
    macro_context: dict[str, Any] | None,
    technical_features: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Build a provider-neutral sentiment/fund-flow proxy from existing facts."""

    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []
    score = 0

    technical_state = None
    relative_strength_state = None
    volume_state = None
    one_month_return = None
    three_month_return = None
    if isinstance(technical_features, dict):
        technical_state = technical_features.get("technical_state")
        relative_strength = technical_features.get("relative_strength")
        if isinstance(relative_strength, dict):
            relative_strength_state = relative_strength.get("state")
            spread = relative_strength.get("3m_spread_pct")
            if spread is not None:
                evidence.append(
                    {
                        "signal": "relative_strength_3m_spread_pct",
                        "value": spread,
                        "source": "technical_feature_payload",
                    }
                )
        volume_trend = technical_features.get("volume_trend")
        if isinstance(volume_trend, dict):
            volume_state = volume_trend.get("state")
            evidence.append(
                {
                    "signal": "volume_trend",
                    "value": volume_state,
                    "source": "technical_feature_payload",
                }
            )
        returns = technical_features.get("returns")
        if isinstance(returns, dict):
            one_month_return = returns.get("1m_pct")
            three_month_return = returns.get("3m_pct")
            evidence.append(
                {
                    "signal": "returns",
                    "value": {
                        "1m_pct": one_month_return,
                        "3m_pct": three_month_return,
                    },
                    "source": "technical_feature_payload",
                }
            )
        score += _market_signal_score(technical_state)
        score += _market_signal_score(relative_strength_state)
        if volume_state == "rising" and _is_positive_number(three_month_return):
            score += 1
        elif volume_state == "rising" and _is_negative_number(three_month_return):
            score -= 1
    else:
        warnings.append("missing technical_feature_payload")

    hsbio_trend = None
    if isinstance(macro_context, dict):
        live_signals = macro_context.get("live_signals")
        if isinstance(live_signals, dict):
            hsbio = live_signals.get("hsbio")
            if isinstance(hsbio, dict):
                hsbio_trend = hsbio.get("trend_30d_pct")
                evidence.append(
                    {
                        "signal": "hsbio_30d_trend",
                        "value": hsbio_trend,
                        "source": "macro_context.live_signals",
                    }
                )
                if _is_positive_number(hsbio_trend):
                    score += 1
                elif _is_negative_number(hsbio_trend):
                    score -= 1
    else:
        warnings.append("missing macro_context")

    if not evidence:
        return None

    sentiment_state = "mixed"
    if score >= 2:
        sentiment_state = "constructive"
    elif score <= -2:
        sentiment_state = "cautious"

    fund_flow_proxy_state = "unknown"
    if volume_state == "rising" and relative_strength_state == "outperforming":
        fund_flow_proxy_state = "accumulation_proxy"
    elif volume_state == "rising" and relative_strength_state == "underperforming":
        fund_flow_proxy_state = "distribution_proxy"
    elif volume_state in {"flat", "falling"}:
        fund_flow_proxy_state = "no_clear_flow_proxy"

    confidence = min(0.75, 0.2 + 0.12 * len(evidence))
    if warnings:
        confidence = min(confidence, 0.45)

    return {
        "sentiment_state": sentiment_state,
        "fund_flow_proxy_state": fund_flow_proxy_state,
        "liquidity_proxy_state": volume_state or "unknown",
        "technical_state": technical_state or "unknown",
        "relative_strength_state": relative_strength_state or "unknown",
        "sector_trend_30d_pct": hsbio_trend,
        "evidence": evidence,
        "warnings": warnings,
        "confidence": round(confidence, 2),
        "needs_human_review": True,
        "guidance_type": "research_only",
        "notes": (
            "Deterministic proxy assembled from existing macro and technical payloads.",
            "Not a trading signal and not a substitute for real fund-flow data.",
        ),
    }


def _market_signal_score(value: Any) -> int:
    text = str(value or "").strip().lower()
    if text in {"constructive", "uptrend", "outperforming", "positive"}:
        return 1
    if text in {"weak", "downtrend", "underperforming", "negative"}:
        return -1
    return 0


def _is_positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _is_negative_number(value: Any) -> bool:
    try:
        return float(value) < 0
    except (TypeError, ValueError):
        return False


def _build_target_price_snapshot(
    research_result: SingleCompanyResearchResult,
) -> dict[str, Any] | None:
    analysis = getattr(research_result, "target_price_analysis", None)
    if analysis is None:
        return None
    top_assets = sorted(
        getattr(analysis.base, "asset_rnpv", ()) or (),
        key=lambda item: getattr(item, "rnpv", 0.0),
        reverse=True,
    )[:5]
    return {
        "currency": analysis.currency,
        "current_share_price": analysis.current_share_price,
        "shares_outstanding": analysis.shares_outstanding,
        "diluted_shares": analysis.diluted_shares,
        "current_equity_value": analysis.current_equity_value,
        "bear_target_price": analysis.bear.target_price,
        "base_target_price": analysis.base.target_price,
        "bull_target_price": analysis.bull.target_price,
        "bear_pipeline_rnpv": analysis.bear.pipeline_rnpv,
        "base_pipeline_rnpv": analysis.base.pipeline_rnpv,
        "bull_pipeline_rnpv": analysis.bull.pipeline_rnpv,
        "probability_weighted_target_price": (
            analysis.probability_weighted_target_price
        ),
        "implied_upside_downside_pct": analysis.implied_upside_downside_pct,
        "event_value_delta": analysis.event_value_delta,
        "asset_value_delta": analysis.asset_value_delta,
        "base_top_asset_rnpv": [
            {
                "asset_name": getattr(item, "asset_name", None),
                "rnpv": getattr(item, "rnpv", None),
                "probability_of_success": getattr(item, "probability_of_success", None),
                "peak_sales": getattr(item, "peak_sales", None),
                "discount_rate": getattr(item, "discount_rate", None),
                "years_to_launch": getattr(item, "years_to_launch", None),
            }
            for item in top_assets
        ],
        "missing_assumptions": list(analysis.missing_assumptions),
        "needs_human_review": analysis.needs_human_review,
    }


def _build_scorecard_summary(
    research_result: SingleCompanyResearchResult,
) -> dict[str, Any] | None:
    scorecard = getattr(research_result, "scorecard", None)
    if scorecard is None:
        return None
    dimensions = []
    for dimension in getattr(scorecard, "dimensions", ()) or ():
        dimensions.append(
            {
                "name": getattr(dimension, "name", None),
                "score": getattr(dimension, "score", None),
                "rationale": getattr(dimension, "rationale", None),
            }
        )
    return {
        "total_score": getattr(scorecard, "total_score", None),
        "bucket": getattr(scorecard, "bucket", None),
        "dimensions": dimensions,
        "monitoring_rules": list(getattr(scorecard, "monitoring_rules", ()) or ()),
        "needs_human_review": getattr(scorecard, "needs_human_review", None),
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
    anchor_details: list[dict[str, Any]] = []
    anchor_assets: list[str] = []
    missing_assets: list[str] = []
    for asset in assets:
        name = (asset.get("name") or "").strip()
        if not name or len(name) < 3:
            continue
        hit = _best_source_excerpt_hit(
            full_text=full_text,
            asset=asset,
            name=name,
            half_window=half_window,
        )
        if hit is None:
            missing_assets.append(name)
            continue
        start, end, score, hit_count = hit
        hits.append((start, end, name))
        anchor_assets.append(name)
        anchor_details.append(
            {
                "asset": name,
                "selected_offset": start,
                "hit_count": hit_count,
                "signal_score": score,
            }
        )

    if not hits:
        excerpt = full_text[:max_chars]
        return {
            "source_type": getattr(document, "source_type", None),
            "title": getattr(document, "title", None),
            "url": getattr(document, "url", None),
            "publication_date": getattr(document, "publication_date", None),
            "anchor_assets": [],
            "anchor_details": [],
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
        "anchor_details": anchor_details,
        "missing_assets": missing_assets,
        "total_chars": len(full_text),
        "excerpt_chars": len(excerpt),
        "excerpt": excerpt,
        "truncated": truncated,
    }


def _best_source_excerpt_hit(
    *,
    full_text: str,
    asset: dict[str, Any],
    name: str,
    half_window: int,
) -> tuple[int, int, int, int] | None:
    matches = list(re.finditer(re.escape(name), full_text))
    if not matches:
        return None
    scored: list[tuple[int, int, int, int]] = []
    for match in matches:
        start = max(0, match.start() - half_window)
        end = min(len(full_text), match.start() + half_window)
        window = full_text[start:end]
        scored.append(
            (
                _source_signal_score(window, asset),
                start,
                end,
                match.start(),
            )
        )
    score, start, end, _ = max(scored, key=lambda item: (item[0], item[3]))
    return start, end, score, len(matches)


_SOURCE_SIGNAL_TERMS = (
    "phase",
    "trial",
    "clinical",
    "BLA",
    "Biologics License Application",
    "IND",
    "approved",
    "accepted",
    "under review",
    "submitted",
    "NMPA",
)


def _source_signal_score(window: str, asset: dict[str, Any]) -> int:
    lowered = window.casefold()
    score = sum(2 for term in _SOURCE_SIGNAL_TERMS if term.casefold() in lowered)
    for key in ("phase", "target", "indication", "partner"):
        value = str(asset.get(key) or "").strip()
        if not value:
            continue
        for token in re.split(r"[;/,]|\s+x\s+", value):
            token = token.strip()
            if len(token) >= 3 and token.casefold() in lowered:
                score += 3
    if "phase 3.0" in lowered:
        score -= 4
    return score


def _llm_agent_result_payload(result: Any) -> dict[str, Any]:
    """Serialize an AgentRunResult to a JSON-friendly dict."""

    fallback_modules: list[str] = []
    for step in getattr(result, "steps", ()) or ():
        for warning in getattr(step, "warnings", ()) or ():
            text = str(warning)
            if text.startswith("fallback_context:"):
                fallback_modules.append(text.split(":", 1)[1].strip())
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
        "fallback_modules": list(dict.fromkeys(fallback_modules)),
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
        override = _builtin_identity_override(clean_company or clean_ticker or "")
        if override is not None:
            clean_company = _clean_text(override.get("company")) or clean_company
            clean_ticker = _clean_text(override.get("ticker")) or clean_ticker
            market = market or _clean_text(override.get("market"))
            search_term = search_term or _clean_text(override.get("search_term"))
            aliases = tuple(
                str(alias).strip()
                for alias in override.get("aliases", ())
                if str(alias).strip()
            )

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


def _builtin_identity_override(query: str) -> dict[str, Any] | None:
    normalized = _clean_text(query).casefold()
    if not normalized:
        return None
    for row in _BUILTIN_IDENTITY_OVERRIDES:
        candidates = [
            row.get("company"),
            row.get("ticker"),
            row.get("search_term"),
            *(row.get("aliases") or ()),
        ]
        for candidate in candidates:
            text = _clean_text(candidate)
            if text and text.casefold() == normalized:
                return row
    return None


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

    search_term = next(
        (alias for alias in aliases if _has_ascii_letter(alias)),
        identity.search_term,
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


def write_extraction_audit_report(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> CompanyReportResult:
    """Write a saved extraction-audit artifact and attach it to manifest."""

    output_path = _extraction_audit_report_path(
        output_dir=output_dir,
        result=result,
    )
    payload = extraction_audit_payload(result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    artifacts = replace(
        result.research_result.artifacts,
        extraction_audit=output_path,
    )
    research_result = replace(result.research_result, artifacts=artifacts)
    result = replace(result, research_result=research_result)
    _update_manifest_with_extraction_audit(
        result=result,
        output_path=output_path,
        audit=payload["extraction_audit"],
    )
    return result


def write_hkexnews_updates_report(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
    feed_url: str | None = None,
    feed_file: str | Path | None = None,
    state_file: str | Path = "data/cache/hkexnews/seen_guids.json",
) -> CompanyReportResult:
    """Save HKEXnews updates and attach artifact metadata to manifest."""

    if not feed_url and not feed_file:
        return result
    xml_text = (
        Path(feed_file).read_text(encoding="utf-8")
        if feed_file
        else fetch_hkex_rss(feed_url or "")
    )
    items = parse_hkex_rss(xml_text)
    filtered = filter_hkex_items_by_ticker(items, ticker=result.identity.ticker)
    payload = track_hkex_news_updates(items=filtered, state_path=state_file)
    payload["ticker_filter"] = result.identity.ticker
    payload["feed_url"] = feed_url
    typed_items = payload.get("typed_new_items")
    typed_rows = typed_items if isinstance(typed_items, list) else []

    output_path = _hkexnews_updates_report_path(output_dir=output_dir, result=result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _append_hkexnews_memo_section(
        result=result,
        payload=payload,
    )
    _append_hkexnews_catalyst_rows(
        result=result,
        typed_rows=typed_rows,
    )
    _update_manifest_with_extra_artifact(
        result=result,
        artifact_key="hkexnews_updates",
        artifact_path=output_path,
        payload_key="hkexnews_updates",
        payload_value={
            "item_count": payload.get("item_count"),
            "new_count": payload.get("new_count"),
            "ticker_filter": payload.get("ticker_filter"),
            "state_path": payload.get("state_path"),
            "typed_new_items": payload.get("typed_new_items", []),
        },
    )
    event_impacts_payload = {
        "event_impacts": typed_items_to_event_impact_suggestions(typed_rows),
        "needs_human_review": True,
    }
    event_impacts_path = _hkexnews_event_impacts_report_path(
        output_dir=output_dir,
        result=result,
    )
    event_impacts_path.parent.mkdir(parents=True, exist_ok=True)
    event_impacts_path.write_text(
        json.dumps(event_impacts_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _update_manifest_with_extra_artifact(
        result=result,
        artifact_key="hkexnews_event_impacts",
        artifact_path=event_impacts_path,
        payload_key="hkexnews_event_impacts",
        payload_value={
            "event_impact_count": len(event_impacts_payload["event_impacts"]),
            "needs_human_review": True,
        },
    )

    dilution_payload = suggest_expected_dilution_pct(
        typed_items=typed_rows,
        current_expected_dilution_pct=(
            result.research_result.target_price_assumptions.expected_dilution_pct
            if result.research_result.target_price_assumptions
            else None
        ),
    )
    dilution_path = _hkexnews_dilution_hint_report_path(
        output_dir=output_dir,
        result=result,
    )
    dilution_path.parent.mkdir(parents=True, exist_ok=True)
    dilution_path.write_text(
        json.dumps(dilution_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _update_manifest_with_extra_artifact(
        result=result,
        artifact_key="hkexnews_dilution_hint",
        artifact_path=dilution_path,
        payload_key="hkexnews_dilution_hint",
        payload_value={
            "suggested_expected_dilution_pct": dilution_payload.get(
                "suggested_expected_dilution_pct"
            ),
            "financing_signal_count": dilution_payload.get("financing_signal_count"),
            "needs_human_review": True,
        },
    )

    peer_payload = _build_peer_valuation_payload(result)
    peer_path = _peer_valuation_report_path(output_dir=output_dir, result=result)
    peer_path.parent.mkdir(parents=True, exist_ok=True)
    peer_path.write_text(
        json.dumps(peer_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _update_manifest_with_extra_artifact(
        result=result,
        artifact_key="peer_valuation",
        artifact_path=peer_path,
        payload_key="peer_valuation",
        payload_value={
            "peer_count": peer_payload.get("peer_count", 0),
            "needs_human_review": True,
        },
    )

    return replace(
        result,
        hkexnews_updates_path=output_path,
        hkexnews_event_impacts_path=event_impacts_path,
        hkexnews_dilution_hint_path=dilution_path,
        peer_valuation_path=peer_path,
    )


def write_cde_updates_report(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
    feed_url: str | None = None,
    feed_file: str | Path | None = None,
    state_file: str | Path = "data/cache/cde/seen_guids.json",
    query: str | None = None,
) -> CompanyReportResult:
    if not feed_url and not feed_file:
        return result
    xml_text = (
        Path(feed_file).read_text(encoding="utf-8")
        if feed_file
        else fetch_cde_feed(feed_url or "")
    )
    items = parse_cde_feed(xml_text)
    filtered = filter_cde_items(items, query=query)
    payload = track_cde_updates(items=filtered, state_path=state_file)
    payload["query"] = query
    payload["feed_url"] = feed_url
    output_path = _cde_updates_report_path(output_dir=output_dir, result=result)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _append_cde_memo_section(result=result, payload=payload)
    _update_manifest_with_extra_artifact(
        result=result,
        artifact_key="cde_updates",
        artifact_path=output_path,
        payload_key="cde_updates",
        payload_value={
            "item_count": payload.get("item_count"),
            "new_count": payload.get("new_count"),
            "query": payload.get("query"),
            "state_path": payload.get("state_path"),
            "typed_new_items": payload.get("typed_new_items", []),
            "normalized_new_records": payload.get("normalized_new_records", []),
        },
    )
    return replace(result, cde_updates_path=output_path)


def _append_hkexnews_memo_section(
    *,
    result: CompanyReportResult,
    payload: dict[str, Any],
) -> None:
    memo_path = result.research_result.artifacts.memo_markdown
    if memo_path is None:
        return
    path = Path(memo_path)
    if not path.exists():
        return
    base = path.read_text(encoding="utf-8").rstrip()
    section = hkexnews_memo_addendum_markdown(payload)
    path.write_text(f"{base}\n\n{section}\n", encoding="utf-8")


def _append_hkexnews_catalyst_rows(
    *,
    result: CompanyReportResult,
    typed_rows: list[dict[str, Any]],
) -> None:
    path = result.research_result.artifacts.catalyst_calendar_csv
    if path is None:
        return
    csv_path = Path(path)
    if not csv_path.exists():
        return
    rows = typed_items_to_catalyst_rows(typed_rows)
    if not rows:
        return
    existing = csv_path.read_text(encoding="utf-8").splitlines()
    if not existing:
        return
    fields = existing[0].split(",")
    known_titles = {line.split(",")[0] for line in existing[1:] if line}
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        for row in rows:
            if row["title"] in known_titles:
                continue
            writer.writerow(row)
            known_titles.add(row["title"])


def _append_cde_memo_section(
    *,
    result: CompanyReportResult,
    payload: dict[str, Any],
) -> None:
    memo_path = result.research_result.artifacts.memo_markdown
    if memo_path is None:
        return
    path = Path(memo_path)
    if not path.exists():
        return
    base = path.read_text(encoding="utf-8").rstrip()
    section = cde_memo_addendum_markdown(payload)
    path.write_text(f"{base}\n\n{section}\n", encoding="utf-8")


def cde_memo_addendum_markdown(payload: dict[str, Any]) -> str:
    typed = payload.get("typed_new_items")
    rows = typed if isinstance(typed, list) else []
    normalized = payload.get("normalized_new_records")
    normalized_rows = normalized if isinstance(normalized, list) else []
    lines = ["## China CDE Updates", ""]
    lines.append(
        f"- New CDE items since last state: {payload.get('new_count', 0)} "
        f"(total fetched: {payload.get('item_count', 0)})."
    )
    lines.append("- Review-gated: deterministic classification requires analyst confirmation.")
    if not rows:
        lines.append("- No query-matched CDE updates in this run.")
        return "\n".join(lines)
    lines.append("")
    for row in rows[:5]:
        title = str(row.get("title") or "Untitled CDE item")
        event_type = str(row.get("event_type") or "other")
        published = row.get("published_at") or "unknown time"
        lines.append(f"- [{event_type}] {title} (published {published})")
    if len(rows) > 5:
        lines.append(f"- ... {len(rows) - 5} more update(s)")
    if normalized_rows:
        lines.extend(["", "### Normalized Trial Registry Draft"])
        for row in normalized_rows[:5]:
            lines.append(
                "- "
                f"{row.get('application_no') or 'no-app-no'} | "
                f"{row.get('status') or 'other'} | "
                f"{row.get('phase') or 'phase_tbd'} | "
                f"{row.get('indication') or 'indication_tbd'}"
            )
    return "\n".join(lines)


def hkexnews_memo_addendum_markdown(payload: dict[str, Any]) -> str:
    typed = payload.get("typed_new_items")
    rows = typed if isinstance(typed, list) else []
    lines = ["## HKEXnews Updates", ""]
    lines.append(
        f"- New announcements since last state: {payload.get('new_count', 0)} "
        f"(total fetched: {payload.get('item_count', 0)})."
    )
    if not rows:
        lines.append("- No new ticker-matched announcements in this run.")
        lines.append("- Review-gated: classification is deterministic and needs analyst confirmation.")
        return "\n".join(lines)
    lines.append("- Review-gated: classification is deterministic and needs analyst confirmation.")
    lines.append("")
    for row in rows[:5]:
        title = str(row.get("title") or "Untitled announcement")
        event_type = str(row.get("event_type") or "corporate")
        published = row.get("published_at") or "unknown time"
        lines.append(
            f"- [{event_type}] {title} (published {published})"
        )
    if len(rows) > 5:
        lines.append(f"- ... {len(rows) - 5} more announcement(s)")
    return "\n".join(lines)


def extraction_audit_payload(result: CompanyReportResult) -> dict[str, Any]:
    """Return the persisted JSON shape for extraction audit artifacts."""

    audit = _build_extraction_audit(result)
    return {
        "run_id": result.research_result.run_id,
        "identity": _jsonable(asdict(result.identity)),
        "quality_gate": report_quality_gate(
            result=result.research_result,
            missing_inputs=result.missing_inputs,
        ),
        "extraction_audit": audit,
    }


def _extraction_audit_report_path(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> Path:
    manifest = result.research_result.artifacts.manifest_json
    if manifest:
        return Path(manifest).parent / (
            f"{result.research_result.run_id}_extraction_audit.json"
        )
    return (
        Path(output_dir)
        / "processed"
        / "company_report"
        / _identity_slug(result.identity)
        / f"{result.research_result.run_id}_extraction_audit.json"
    )


def _hkexnews_updates_report_path(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> Path:
    manifest = result.research_result.artifacts.manifest_json
    if manifest:
        return Path(manifest).parent / (
            f"{result.research_result.run_id}_hkexnews_updates.json"
        )
    return (
        Path(output_dir)
        / "processed"
        / "company_report"
        / _identity_slug(result.identity)
        / f"{result.research_result.run_id}_hkexnews_updates.json"
    )


def _hkexnews_event_impacts_report_path(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> Path:
    manifest = result.research_result.artifacts.manifest_json
    if manifest:
        return Path(manifest).parent / (
            f"{result.research_result.run_id}_hkexnews_event_impacts.json"
        )
    return (
        Path(output_dir)
        / "processed"
        / "company_report"
        / _identity_slug(result.identity)
        / f"{result.research_result.run_id}_hkexnews_event_impacts.json"
    )


def _hkexnews_dilution_hint_report_path(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> Path:
    manifest = result.research_result.artifacts.manifest_json
    if manifest:
        return Path(manifest).parent / (
            f"{result.research_result.run_id}_hkexnews_dilution_hint.json"
        )
    return (
        Path(output_dir)
        / "processed"
        / "company_report"
        / _identity_slug(result.identity)
        / f"{result.research_result.run_id}_hkexnews_dilution_hint.json"
    )


def _peer_valuation_report_path(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> Path:
    manifest = result.research_result.artifacts.manifest_json
    if manifest:
        return Path(manifest).parent / (
            f"{result.research_result.run_id}_peer_valuation.json"
        )
    return (
        Path(output_dir)
        / "processed"
        / "company_report"
        / _identity_slug(result.identity)
        / f"{result.research_result.run_id}_peer_valuation.json"
    )


def _cde_updates_report_path(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> Path:
    manifest = result.research_result.artifacts.manifest_json
    if manifest:
        return Path(manifest).parent / f"{result.research_result.run_id}_cde_updates.json"
    return (
        Path(output_dir)
        / "processed"
        / "company_report"
        / _identity_slug(result.identity)
        / f"{result.research_result.run_id}_cde_updates.json"
    )


def _report_quality_report_path(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> Path:
    manifest = result.research_result.artifacts.manifest_json
    if manifest:
        return Path(manifest).parent / (
            f"{result.research_result.run_id}_report_quality.json"
        )
    return (
        Path(output_dir)
        / "processed"
        / "company_report"
        / _identity_slug(result.identity)
        / f"{result.research_result.run_id}_report_quality.json"
    )


def _valuation_pod_report_path(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> Path:
    manifest = result.research_result.artifacts.manifest_json
    if manifest:
        return Path(manifest).parent / (
            f"{result.research_result.run_id}_valuation_pod.json"
        )
    return (
        Path(output_dir)
        / "processed"
        / "company_report"
        / _identity_slug(result.identity)
        / f"{result.research_result.run_id}_valuation_pod.json"
    )


def _decision_log_report_path(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> Path:
    manifest = result.research_result.artifacts.manifest_json
    if manifest:
        return Path(manifest).parent / (
            f"{result.research_result.run_id}_decision_log.json"
        )
    return (
        Path(output_dir)
        / "processed"
        / "company_report"
        / _identity_slug(result.identity)
        / f"{result.research_result.run_id}_decision_log.json"
    )


def write_stage_a_llm_reports(
    *,
    output_dir: str | Path,
    result: CompanyReportResult,
) -> CompanyReportResult:
    llm_result = result.llm_agent_result
    if llm_result is None:
        return result
    facts = getattr(llm_result, "facts", {}) or {}
    if not isinstance(facts, dict):
        facts = {}

    report_quality_payload = facts.get("report_quality_payload")
    report_quality_path: Path | None = None
    if isinstance(report_quality_payload, dict):
        report_quality_path = _report_quality_report_path(
            output_dir=output_dir,
            result=result,
        )
        report_quality_path.parent.mkdir(parents=True, exist_ok=True)
        report_quality_path.write_text(
            json.dumps(_jsonable(report_quality_payload), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        _update_manifest_with_extra_artifact(
            result=result,
            artifact_key="report_quality",
            artifact_path=report_quality_path,
            payload_key="report_quality",
            payload_value={
                "publish_gate": report_quality_payload.get("publish_gate"),
                "critical_issue_count": len(
                    report_quality_payload.get("critical_issues") or []
                ),
                "recommended_fix_count": len(
                    report_quality_payload.get("recommended_fixes") or []
                ),
            },
        )

    valuation_pod_payload = _valuation_pod_payload_from_llm_facts(facts)
    valuation_pod_path: Path | None = None
    if valuation_pod_payload["available"]:
        valuation_pod_path = _valuation_pod_report_path(
            output_dir=output_dir,
            result=result,
        )
        valuation_pod_path.parent.mkdir(parents=True, exist_ok=True)
        valuation_pod_path.write_text(
            json.dumps(_jsonable(valuation_pod_payload), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        _update_manifest_with_extra_artifact(
            result=result,
            artifact_key="valuation_pod",
            artifact_path=valuation_pod_path,
            payload_key="valuation_pod_summary",
            payload_value=valuation_pod_payload["summary"],
        )

    decision_payload = _decision_debate_payload_from_llm_facts(facts)
    decision_log_path: Path | None = None
    if decision_payload["available"]:
        decision_log_path = _decision_log_report_path(
            output_dir=output_dir,
            result=result,
        )
        decision_artifact = {
            **decision_payload,
            "run_id": result.research_result.run_id,
            "identity": _jsonable(asdict(result.identity)),
        }
        decision_log_path.parent.mkdir(parents=True, exist_ok=True)
        decision_log_path.write_text(
            json.dumps(_jsonable(decision_artifact), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        _update_manifest_with_extra_artifact(
            result=result,
            artifact_key="decision_log",
            artifact_path=decision_log_path,
            payload_key="decision_log_summary",
            payload_value=decision_payload["summary"],
        )

    return replace(
        result,
        report_quality_path=report_quality_path,
        valuation_pod_path=valuation_pod_path,
        decision_log_path=decision_log_path,
    )


def _decision_debate_payload_from_llm_facts(facts: dict[str, Any]) -> dict[str, Any]:
    payload = facts.get("decision_debate_payload")
    if not isinstance(payload, dict):
        return {"available": False, "summary": {}, "payload": None}

    decision_log = payload.get("decision_log")
    if not isinstance(decision_log, dict):
        decision_log = {}
    summary = {
        "fundamental_view": payload.get("fundamental_view"),
        "timing_view": payload.get("timing_view"),
        "current_decision": decision_log.get("current_decision"),
        "bull_case_count": len(payload.get("bull_case") or []),
        "bear_case_count": len(payload.get("bear_case") or []),
        "invalidation_trigger_count": len(
            decision_log.get("invalidation_triggers") or []
        ),
        "evidence_gap_count": len(decision_log.get("evidence_gaps") or []),
        "confidence": payload.get("confidence"),
        "needs_human_review": payload.get("needs_human_review"),
    }
    return {
        "available": True,
        "summary": summary,
        "payload": payload,
    }


def _load_prior_decision_logs(
    *,
    output_dir: str | Path,
    identity: CompanyIdentity,
    current_run_id: str,
    limit: int = 3,
) -> dict[str, Any] | None:
    root = Path(output_dir)
    if not root.exists():
        return None

    entries: list[dict[str, Any]] = []
    for entry in _iter_decision_log_entries(output_dir=root):
        run_id = str(entry.get("run_id") or "")
        if run_id == current_run_id:
            continue
        if not _decision_log_entry_matches_identity(entry, identity):
            continue
        entries.append(entry)

    if not entries:
        return None
    entries.sort(key=lambda item: str(item.get("run_id") or ""), reverse=True)
    entries = entries[:limit]
    return {
        "count": len(entries),
        "entries": entries,
    }


def _iter_decision_log_entries(
    *,
    output_dir: str | Path,
) -> list[dict[str, Any]]:
    root = Path(output_dir)
    if not root.exists():
        return []

    entries: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in root.glob("**/*_decision_log.json"):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        entry = _decision_log_entry_from_artifact(path=path, payload=payload)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda item: str(item.get("run_id") or ""), reverse=True)
    return entries


def _decision_log_entry_from_artifact(
    *,
    path: Path,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    raw_payload = payload.get("payload")
    if not isinstance(raw_payload, dict):
        raw_payload = {}
    decision_log = raw_payload.get("decision_log")
    if not isinstance(decision_log, dict):
        decision_log = {}
    identity = payload.get("identity")
    if not isinstance(identity, dict):
        identity = {}
    return {
        "run_id": str(payload.get("run_id") or _run_id_from_artifact_name(path)),
        "path": str(path),
        "identity": identity,
        "summary": summary,
        "decision_log": {
            "current_decision": decision_log.get("current_decision"),
            "key_assumptions": decision_log.get("key_assumptions") or [],
            "reasons_to_revisit": decision_log.get("reasons_to_revisit") or [],
            "invalidation_triggers": decision_log.get("invalidation_triggers")
            or [],
            "evidence_gaps": decision_log.get("evidence_gaps") or [],
            "next_review_triggers": decision_log.get("next_review_triggers") or [],
        },
    }


def _run_id_from_artifact_name(path: Path) -> str:
    suffix = "_decision_log"
    stem = path.stem
    if stem.endswith(suffix):
        return stem[: -len(suffix)]
    return stem


def _decision_log_matches_identity(
    payload: dict[str, Any],
    identity: CompanyIdentity,
) -> bool:
    artifact_identity = payload.get("identity")
    if not isinstance(artifact_identity, dict):
        return False
    expected_ticker = str(identity.ticker or "").strip().casefold()
    actual_ticker = str(artifact_identity.get("ticker") or "").strip().casefold()
    if expected_ticker and actual_ticker and expected_ticker == actual_ticker:
        return True
    expected_company = str(identity.company or "").strip().casefold()
    actual_company = str(artifact_identity.get("company") or "").strip().casefold()
    return bool(
        expected_company
        and actual_company
        and expected_company == actual_company
    )


def _decision_log_entry_matches_identity(
    entry: dict[str, Any],
    identity: CompanyIdentity,
) -> bool:
    artifact_identity = entry.get("identity")
    if not isinstance(artifact_identity, dict):
        return False
    return _decision_log_matches_identity(
        {"identity": artifact_identity},
        identity,
    )


def _valuation_pod_payload_from_llm_facts(facts: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "commercial": facts.get("valuation_commercial_payload"),
        "rnpv": facts.get("valuation_rnpv_payload"),
        "balance_sheet": facts.get("valuation_balance_sheet_payload"),
        "committee": facts.get("valuation_committee_payload"),
    }
    available = any(isinstance(value, dict) for value in payload.values())
    committee = payload.get("committee") if isinstance(payload.get("committee"), dict) else {}
    component_ranges = {
        key: value.get("valuation_range")
        for key, value in payload.items()
        if isinstance(value, dict) and isinstance(value.get("valuation_range"), dict)
    }
    signatures: dict[tuple[float | None, float | None, float | None], int] = {}
    for value in component_ranges.values():
        signature = (
            _optional_float(value.get("bear")),
            _optional_float(value.get("base")),
            _optional_float(value.get("bull")),
        )
        signatures[signature] = signatures.get(signature, 0) + 1
    duplicate_range_count = sum(count - 1 for count in signatures.values() if count > 1)
    summary = {
        "component_count": sum(1 for value in payload.values() if isinstance(value, dict)),
        "has_committee": isinstance(payload.get("committee"), dict),
        "committee_method": committee.get("method"),
        "committee_currency": committee.get("currency"),
        "committee_publishable": bool(committee) and not bool(
            committee.get("needs_human_review", True)
        ),
        "component_methods": {
            key: value.get("method")
            for key, value in payload.items()
            if isinstance(value, dict)
        },
        "component_ranges": component_ranges,
        "duplicate_component_range_count": duplicate_range_count,
        "conservative_rnpv_floor": committee.get("conservative_rnpv_floor"),
        "market_implied_value": committee.get("market_implied_value"),
        "scenario_repricing_range": committee.get("scenario_repricing_range"),
    }
    return {
        "available": available,
        "summary": summary,
        "payload": payload,
    }


def _optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _update_manifest_with_extraction_audit(
    *,
    result: CompanyReportResult,
    output_path: Path,
    audit: dict[str, Any],
) -> None:
    manifest = result.research_result.artifacts.manifest_json
    if manifest is None:
        return
    manifest_path = Path(manifest)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    artifacts = payload.setdefault("artifacts", {})
    if isinstance(artifacts, dict):
        artifacts["extraction_audit"] = str(output_path)
    payload["extraction_audit"] = {
        "status": audit.get("status"),
        "asset_count": audit.get("asset_count"),
        "counts": audit.get("counts"),
        "source_excerpt": audit.get("source_excerpt"),
        "top_review_assets": audit.get("top_review_assets"),
    }
    manifest_path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _update_manifest_with_extra_artifact(
    *,
    result: CompanyReportResult,
    artifact_key: str,
    artifact_path: Path,
    payload_key: str,
    payload_value: dict[str, Any],
) -> None:
    manifest = result.research_result.artifacts.manifest_json
    if manifest is None:
        return
    manifest_path = Path(manifest)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    artifacts = payload.setdefault("artifacts", {})
    if isinstance(artifacts, dict):
        artifacts[artifact_key] = str(artifact_path)
    payload[payload_key] = payload_value
    manifest_path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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


def _build_peer_valuation_payload(result: CompanyReportResult) -> dict[str, Any]:
    current = result.research_result.valuation_metrics
    peers: list[dict[str, Any]] = []
    if current is None:
        return {
            "peer_count": 0,
            "peers": peers,
            "current_enterprise_value": None,
            "current_revenue_multiple": None,
            "needs_human_review": True,
            "rationale": "Current run has no valuation metrics to compare.",
        }
    market = (result.identity.market or "").casefold()
    for match in result.research_result.competitive_matches:
        ev = None
        rev_mult = None
        for peer in result.research_result.competitor_assets:
            if (
                peer.company == match.competitor_company
                and peer.asset_name == match.competitor_asset
            ):
                break
        peers.append(
            {
                "company": match.competitor_company,
                "asset_name": match.competitor_asset,
                "match_scope": match.match_scope,
                "match_confidence": match.confidence,
                "enterprise_value": ev,
                "revenue_multiple": rev_mult,
                "market": market or None,
                "phase": "to_verify",
                "needs_human_review": True,
            }
        )
    return {
        "peer_count": len(peers),
        "peers": peers[:20],
        "current_enterprise_value": current.enterprise_value,
        "current_revenue_multiple": current.revenue_multiple,
        "needs_human_review": True,
        "rationale": (
            "Peer set is seeded from competitive matches; phase and valuation "
            "fields require curated peer snapshots."
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
        "extraction_audit": _build_extraction_audit(result),
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
        "report_quality_path": (
            str(result.report_quality_path) if result.report_quality_path else None
        ),
        "report_quality": _report_quality_summary(result),
        "valuation_pod_path": (
            str(result.valuation_pod_path) if result.valuation_pod_path else None
        ),
        "valuation_pod_summary": _valuation_pod_summary(result),
        "decision_log_path": (
            str(result.decision_log_path) if result.decision_log_path else None
        ),
        "decision_log_summary": _decision_log_summary(result),
        "llm_trace_path": (
            str(result.llm_trace_path) if result.llm_trace_path else None
        ),
        "hkexnews_updates_path": (
            str(result.hkexnews_updates_path) if result.hkexnews_updates_path else None
        ),
        "hkexnews_updates": _build_hkexnews_summary(result),
        "cde_updates_path": (
            str(result.cde_updates_path) if result.cde_updates_path else None
        ),
        "cde_updates": _build_json_artifact_summary(result.cde_updates_path),
        "hkexnews_event_impacts_path": (
            str(result.hkexnews_event_impacts_path)
            if result.hkexnews_event_impacts_path
            else None
        ),
        "hkexnews_event_impacts": _build_json_artifact_summary(
            result.hkexnews_event_impacts_path
        ),
        "hkexnews_dilution_hint_path": (
            str(result.hkexnews_dilution_hint_path)
            if result.hkexnews_dilution_hint_path
            else None
        ),
        "hkexnews_dilution_hint": _build_json_artifact_summary(
            result.hkexnews_dilution_hint_path
        ),
        "peer_valuation_path": (
            str(result.peer_valuation_path) if result.peer_valuation_path else None
        ),
        "peer_valuation": _build_json_artifact_summary(result.peer_valuation_path),
    }


def decision_log_history(
    *,
    output_dir: str | Path = "data",
    company: str | None = None,
    ticker: str | None = None,
    market: str | None = None,
    registry_path: str | Path | None = "data/input/company_registry.json",
    limit: int = 5,
) -> dict[str, Any]:
    """Return recent same-company decision-log artifacts for local review."""

    identity = resolve_company_identity(
        company=company,
        ticker=ticker,
        market=market,
        registry_path=registry_path,
    )
    payload = _load_prior_decision_logs(
        output_dir=output_dir,
        identity=identity,
        current_run_id="",
        limit=limit,
    )
    return {
        "identity": _jsonable(asdict(identity)),
        "available": bool(payload and payload.get("entries")),
        "count": int(payload.get("count", 0)) if isinstance(payload, dict) else 0,
        "entries": payload.get("entries", []) if isinstance(payload, dict) else [],
        "change_summary": _decision_log_history_change_summary(
            payload.get("entries", []) if isinstance(payload, dict) else []
        ),
    }


def decision_log_index(
    *,
    output_dir: str | Path = "data",
    limit: int = 20,
) -> dict[str, Any]:
    """Return recent decision-log artifacts across all local companies."""

    entries = _iter_decision_log_entries(output_dir=output_dir)
    entries = entries[: max(1, limit)]
    return {
        "available": bool(entries),
        "count": len(entries),
        "entries": entries,
    }


def stage_c_review_index(
    *,
    output_dir: str | Path = "data",
    query: str | None = None,
    flags: tuple[str, ...] = (),
    latest_per_identity: bool = False,
    min_severity: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Return an offline review index for saved Stage B/C support artifacts."""

    entries = _iter_stage_c_review_entries(output_dir=output_dir)
    if query:
        entries = [
            entry
            for entry in entries
            if _stage_c_review_entry_matches_query(entry, query)
        ]
    if flags:
        entries = [
            entry
            for entry in entries
            if _stage_c_review_entry_has_flags(entry, flags)
        ]
    if min_severity:
        entries = [
            entry
            for entry in entries
            if _stage_c_review_meets_min_severity(entry, min_severity)
        ]
    if latest_per_identity:
        entries = _stage_c_latest_per_identity(entries)
    entries = entries[: max(1, limit)]
    return {
        "available": bool(entries),
        "count": len(entries),
        "query": query,
        "filters": {
            "flags": list(flags),
            "latest_per_identity": latest_per_identity,
            "min_severity": min_severity,
        },
        "entries": entries,
        "summary": _stage_c_review_summary(entries),
    }


def stage_c_review_markdown(payload: dict[str, Any]) -> str:
    """Render a compact Markdown checklist for offline Stage C review."""

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    query = payload.get("query")
    title = "Stage C Artifact Review"
    if isinstance(query, str) and query.strip():
        title = f"{title}: {query.strip()}"
    lines = [
        f"# {title}",
        "",
        f"- Runs: {summary.get('entry_count', payload.get('count', 0))}",
    ]
    gate_counts = summary.get("publish_gate_counts")
    if isinstance(gate_counts, dict) and gate_counts:
        lines.append("- Quality gates: " + _stage_c_counts_text(gate_counts))
    severity_counts = summary.get("severity_counts")
    if isinstance(severity_counts, dict) and severity_counts:
        lines.append("- Severities: " + _stage_c_counts_text(severity_counts))
    flag_counts = summary.get("flag_counts")
    if isinstance(flag_counts, dict) and flag_counts:
        top_flags = dict(
            sorted(
                flag_counts.items(),
                key=lambda item: (-int(item[1]), str(item[0])),
            )[:8]
        )
        lines.append("- Top flags: " + _stage_c_counts_text(top_flags))
    lines.append("")

    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        lines.append("_No Stage C support artifacts found._")
        return "\n".join(lines).rstrip() + "\n"

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identity = entry.get("identity")
        label = _stage_c_entry_label(entry, identity)
        severity = entry.get("review_severity") or "info"
        lines.extend(
            [
                f"## {entry.get('run_id') or 'unknown'} {label}",
                "",
                f"- Severity: `{severity}`",
            ]
        )
        report_quality = (
            entry.get("report_quality")
            if isinstance(entry.get("report_quality"), dict)
            else {}
        )
        lines.append(
            "- Quality: "
            f"`{report_quality.get('publish_gate') or 'missing'}`"
            f", critical={report_quality.get('critical_issue_count')}"
            f", fixes={report_quality.get('recommended_fix_count')}"
        )
        valuation_pod = (
            entry.get("valuation_pod")
            if isinstance(entry.get("valuation_pod"), dict)
            else {}
        )
        if valuation_pod:
            lines.append(
                "- Valuation: "
                f"committee_publishable={valuation_pod.get('committee_publishable')}"
                f", duplicates={valuation_pod.get('duplicate_component_range_count')}"
            )
        flags = entry.get("review_flags")
        if isinstance(flags, list) and flags:
            lines.append("- Flags: " + ", ".join(f"`{flag}`" for flag in flags[:12]))
        actions = entry.get("next_actions")
        if isinstance(actions, list) and actions:
            lines.append("")
            lines.append("Checklist:")
            for action in actions[:5]:
                text = str(action).strip()
                if text:
                    lines.append(f"- [ ] {text}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _stage_c_counts_text(counts: dict[str, Any]) -> str:
    return ", ".join(f"`{key}`={value}" for key, value in sorted(counts.items()))


def _stage_c_entry_label(entry: dict[str, Any], identity: Any) -> str:
    if isinstance(identity, dict):
        ticker = str(identity.get("ticker") or "").strip()
        if ticker:
            return ticker
        company = str(identity.get("company") or "").strip()
        if company:
            return company
    return str(entry.get("artifact_dir") or "unknown")


_STAGE_C_ARTIFACT_SUFFIXES = {
    "report_quality": "_report_quality",
    "valuation_pod": "_valuation_pod",
    "decision_log": "_decision_log",
}

_STAGE_C_SEVERITY_RANK = {
    "info": 0,
    "coverage": 1,
    "review": 2,
    "critical": 3,
}

_STAGE_C_FLAG_SEVERITY = {
    "report_quality_block": "critical",
    "report_quality_review_required": "review",
    "report_quality_unavailable": "review",
    "missing_report_quality_artifact": "coverage",
    "unreadable_report_quality_artifact": "coverage",
    "missing_valuation_pod_artifact": "coverage",
    "unreadable_valuation_pod_artifact": "coverage",
    "valuation_committee_not_publishable": "review",
    "valuation_duplicate_component_ranges": "critical",
    "valuation_commercial_method_drift": "critical",
    "valuation_balance_sheet_method_drift": "critical",
    "valuation_rnpv_as_sole_fair_value_language": "critical",
    "valuation_overvaluation_language_without_market_bridge": "review",
    "valuation_missing_market_implied_value": "review",
    "valuation_missing_scenario_repricing_range": "review",
    "missing_decision_log_artifact": "coverage",
    "unreadable_decision_log_artifact": "coverage",
    "decision_log_missing_next_review_trigger": "review",
}


def _iter_stage_c_review_entries(
    *,
    output_dir: str | Path,
) -> list[dict[str, Any]]:
    root = Path(output_dir)
    if not root.exists():
        return []

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for artifact_key, suffix in _STAGE_C_ARTIFACT_SUFFIXES.items():
        for path in root.glob(f"**/*{suffix}.json"):
            run_id = _run_id_from_stage_artifact_name(path, suffix=suffix)
            if not run_id:
                continue
            group_key = (str(path.parent), run_id)
            group = grouped.setdefault(
                group_key,
                {
                    "run_id": run_id,
                    "artifact_dir": str(path.parent),
                    "identity": _identity_from_artifact_slug(path.parent.name),
                    "artifacts": {},
                },
            )
            artifacts = group.setdefault("artifacts", {})
            if isinstance(artifacts, dict):
                artifacts[artifact_key] = str(path)

    entries: list[dict[str, Any]] = []
    for group in grouped.values():
        entry = _stage_c_review_entry_from_group(group)
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda item: str(item.get("run_id") or ""), reverse=True)
    return entries


def _run_id_from_stage_artifact_name(path: Path, *, suffix: str) -> str | None:
    stem = path.stem
    if not stem.endswith(suffix):
        return None
    run_id = stem[: -len(suffix)]
    return run_id or None


def _identity_from_artifact_slug(slug: str) -> dict[str, Any]:
    parts = [part for part in re.split(r"[-_]+", slug.strip()) if part]
    ticker = None
    if len(parts) >= 2 and parts[-1].isalpha() and parts[-2].isdigit():
        ticker = f"{parts[-2]}.{parts[-1].upper()}"
    return {
        "company": slug,
        "ticker": ticker,
        "market": ticker.split(".")[-1] if ticker else None,
    }


def _stage_c_review_entry_from_group(
    group: dict[str, Any],
) -> dict[str, Any] | None:
    artifacts = group.get("artifacts")
    if not isinstance(artifacts, dict):
        return None

    report_quality = _stage_c_report_quality_entry(
        _load_json_artifact(artifacts.get("report_quality"))
    )
    valuation_pod = _stage_c_valuation_pod_entry(
        _load_json_artifact(artifacts.get("valuation_pod"))
    )
    decision_log = _stage_c_decision_log_entry(
        _load_json_artifact(artifacts.get("decision_log"))
    )
    identity = group.get("identity") if isinstance(group.get("identity"), dict) else {}
    if decision_log and isinstance(decision_log.get("identity"), dict):
        identity = decision_log["identity"]
    flags = _stage_c_review_flags(
        artifacts=artifacts,
        report_quality=report_quality,
        valuation_pod=valuation_pod,
        decision_log=decision_log,
    )
    return {
        "run_id": group.get("run_id"),
        "artifact_dir": group.get("artifact_dir"),
        "identity": identity,
        "artifacts": dict(artifacts),
        "report_quality": report_quality,
        "valuation_pod": valuation_pod,
        "decision_log": decision_log,
        "review_flags": flags,
        "review_flag_count": len(flags),
        "review_severity": _stage_c_review_severity(flags),
        "next_actions": _stage_c_review_next_actions(flags),
    }


def _load_json_artifact(path_value: Any) -> dict[str, Any] | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    path = Path(path_value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _stage_c_report_quality_entry(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {
        "publish_gate": payload.get("publish_gate"),
        "summary": payload.get("summary"),
        "confidence": payload.get("confidence"),
        "critical_issue_count": len(payload.get("critical_issues") or []),
        "recommended_fix_count": len(payload.get("recommended_fixes") or []),
        "critical_issues": _string_list(payload.get("critical_issues"))[:5],
        "recommended_fixes": _string_list(payload.get("recommended_fixes"))[:5],
        "language_quality_findings": _string_list(
            payload.get("language_quality_findings")
        )[:5],
        "valuation_coherence_findings": _string_list(
            payload.get("valuation_coherence_findings")
        )[:5],
    }


def _stage_c_valuation_pod_entry(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    pod_payload = payload.get("payload")
    if not isinstance(pod_payload, dict):
        pod_payload = {}
    component_methods = _valuation_pod_component_methods(summary, pod_payload)
    component_ranges = _valuation_pod_component_ranges(summary, pod_payload)
    duplicate_count = summary.get("duplicate_component_range_count")
    if duplicate_count is None:
        duplicate_count = _duplicate_component_range_count(component_ranges)
    committee = pod_payload.get("committee")
    if not isinstance(committee, dict):
        committee = {}
    committee_publishable = summary.get("committee_publishable")
    if committee_publishable is None and committee:
        committee_publishable = not bool(committee.get("needs_human_review", True))
    language_flags = _valuation_pod_language_flags(
        pod_payload=pod_payload,
        has_market_implied_value=bool(
            summary.get("market_implied_value") or committee.get("market_implied_value")
        ),
        has_scenario_repricing_range=bool(
            summary.get("scenario_repricing_range")
            or committee.get("scenario_repricing_range")
        ),
    )
    return {
        "available": bool(payload.get("available")),
        "component_count": summary.get("component_count")
        or sum(1 for value in pod_payload.values() if isinstance(value, dict)),
        "has_committee": summary.get("has_committee")
        if "has_committee" in summary
        else bool(committee),
        "committee_method": summary.get("committee_method")
        or committee.get("method"),
        "committee_currency": summary.get("committee_currency")
        or committee.get("currency"),
        "committee_publishable": committee_publishable,
        "component_methods": component_methods,
        "role_boundary_flags": _valuation_pod_role_boundary_flags(pod_payload),
        "duplicate_component_range_count": duplicate_count,
        "has_market_implied_value": bool(
            summary.get("market_implied_value") or committee.get("market_implied_value")
        ),
        "has_scenario_repricing_range": bool(
            summary.get("scenario_repricing_range")
            or committee.get("scenario_repricing_range")
        ),
        "language_flags": language_flags,
    }


def _valuation_pod_component_methods(
    summary: dict[str, Any],
    pod_payload: dict[str, Any],
) -> dict[str, Any]:
    methods = summary.get("component_methods")
    if isinstance(methods, dict):
        return dict(methods)
    return {
        key: value.get("method")
        for key, value in pod_payload.items()
        if isinstance(value, dict)
    }


def _valuation_pod_component_ranges(
    summary: dict[str, Any],
    pod_payload: dict[str, Any],
) -> dict[str, Any]:
    ranges = summary.get("component_ranges")
    if isinstance(ranges, dict):
        return dict(ranges)
    return {
        key: value.get("valuation_range")
        for key, value in pod_payload.items()
        if isinstance(value, dict) and isinstance(value.get("valuation_range"), dict)
    }


def _valuation_pod_role_boundary_flags(
    pod_payload: dict[str, Any],
) -> dict[str, list[str]]:
    flags: dict[str, list[str]] = {}
    for key, value in pod_payload.items():
        if not isinstance(value, dict):
            continue
        raw_flags = _string_list(value.get("role_boundary_flags"))
        if raw_flags:
            flags[key] = raw_flags
    return flags


def _duplicate_component_range_count(component_ranges: dict[str, Any]) -> int:
    signatures: dict[tuple[float | None, float | None, float | None], int] = {}
    for value in component_ranges.values():
        if not isinstance(value, dict):
            continue
        signature = (
            _optional_float(value.get("bear")),
            _optional_float(value.get("base")),
            _optional_float(value.get("bull")),
        )
        signatures[signature] = signatures.get(signature, 0) + 1
    return sum(count - 1 for count in signatures.values() if count > 1)


def _valuation_pod_language_flags(
    *,
    pod_payload: dict[str, Any],
    has_market_implied_value: bool,
    has_scenario_repricing_range: bool,
) -> list[str]:
    text = " ".join(_nested_stage_c_strings(pod_payload, limit=160)).casefold()
    flags: list[str] = []
    if "rnpv" in text and any(
        token in text
        for token in (
            "唯一公允",
            "唯一合理",
            "only fair value",
            "sole fair value",
            "sole reasonable value",
        )
    ):
        flags.append("rnpv_as_sole_fair_value_language")
    has_overvaluation_language = any(
        token in text
        for token in (
            "高估",
            "下行空间",
            "估值透支",
            "远高于",
            "显著高于",
            "overvalued",
            "downside",
        )
    )
    has_gap_context = has_market_implied_value and has_scenario_repricing_range
    if has_overvaluation_language and not has_gap_context:
        flags.append("overvaluation_language_without_market_bridge")
    return flags


def _nested_stage_c_strings(value: Any, *, limit: int = 80) -> list[str]:
    strings: list[str] = []

    def visit(item: Any) -> None:
        if len(strings) >= limit:
            return
        if isinstance(item, str):
            text = item.strip()
            if text:
                strings.append(text)
            return
        if isinstance(item, dict):
            for sub_item in item.values():
                visit(sub_item)
                if len(strings) >= limit:
                    return
            return
        if isinstance(item, (list, tuple)):
            for sub_item in item:
                visit(sub_item)
                if len(strings) >= limit:
                    return

    visit(value)
    return strings


def _stage_c_decision_log_entry(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    entry = _decision_log_entry_from_artifact(
        path=Path(str(payload.get("run_id") or "decision_log")),
        payload=payload,
    )
    if entry is None:
        return None
    return {
        "identity": entry.get("identity"),
        "summary": entry.get("summary"),
        "decision_log": entry.get("decision_log"),
    }


def _stage_c_review_flags(
    *,
    artifacts: dict[str, Any],
    report_quality: dict[str, Any] | None,
    valuation_pod: dict[str, Any] | None,
    decision_log: dict[str, Any] | None,
) -> list[str]:
    flags: list[str] = []
    if "report_quality" not in artifacts:
        flags.append("missing_report_quality_artifact")
    elif report_quality is None:
        flags.append("unreadable_report_quality_artifact")
    else:
        gate = str(report_quality.get("publish_gate") or "").strip()
        if gate == "block":
            flags.append("report_quality_block")
        elif gate == "review_required":
            flags.append("report_quality_review_required")
        critical = " ".join(report_quality.get("critical_issues") or [])
        if "report_quality_unavailable" in critical:
            flags.append("report_quality_unavailable")

    if "valuation_pod" not in artifacts:
        flags.append("missing_valuation_pod_artifact")
    elif valuation_pod is None:
        flags.append("unreadable_valuation_pod_artifact")
    else:
        if valuation_pod.get("committee_publishable") is False:
            flags.append("valuation_committee_not_publishable")
        if int(valuation_pod.get("duplicate_component_range_count") or 0) > 0:
            flags.append("valuation_duplicate_component_ranges")
        methods = valuation_pod.get("component_methods")
        if isinstance(methods, dict):
            if str(methods.get("commercial") or "").casefold() == "rnpv":
                flags.append("valuation_commercial_method_drift")
            if str(methods.get("balance_sheet") or "").casefold() == "rnpv":
                flags.append("valuation_balance_sheet_method_drift")
        role_boundary_flags = valuation_pod.get("role_boundary_flags")
        if isinstance(role_boundary_flags, dict):
            for component, component_flags in role_boundary_flags.items():
                if not isinstance(component_flags, list):
                    continue
                for component_flag in component_flags:
                    normalized_flag = _stage_c_flag_token(str(component_flag))
                    normalized_component = _stage_c_flag_token(str(component))
                    if normalized_flag and normalized_component:
                        flags.append(
                            "valuation_role_boundary_"
                            f"{normalized_component}_{normalized_flag}"
                        )
        language_flags = valuation_pod.get("language_flags")
        if isinstance(language_flags, list):
            for language_flag in language_flags:
                flags.append(f"valuation_{language_flag}")
        if not valuation_pod.get("has_market_implied_value"):
            flags.append("valuation_missing_market_implied_value")
        if not valuation_pod.get("has_scenario_repricing_range"):
            flags.append("valuation_missing_scenario_repricing_range")

    if "decision_log" not in artifacts:
        flags.append("missing_decision_log_artifact")
    elif decision_log is None:
        flags.append("unreadable_decision_log_artifact")
    else:
        log = decision_log.get("decision_log")
        next_triggers = (
            log.get("next_review_triggers") if isinstance(log, dict) else None
        )
        if not _has_nonempty_string(next_triggers):
            flags.append("decision_log_missing_next_review_trigger")
    return flags


def _stage_c_review_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    flag_counts: dict[str, int] = {}
    gate_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for entry in entries:
        for flag in entry.get("review_flags") or []:
            text = str(flag)
            flag_counts[text] = flag_counts.get(text, 0) + 1
        severity = str(entry.get("review_severity") or "info")
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        report_quality = entry.get("report_quality")
        if isinstance(report_quality, dict):
            gate = str(report_quality.get("publish_gate") or "unknown")
        else:
            gate = "missing"
        gate_counts[gate] = gate_counts.get(gate, 0) + 1
    return {
        "entry_count": len(entries),
        "flag_counts": flag_counts,
        "publish_gate_counts": gate_counts,
        "severity_counts": severity_counts,
    }


def _stage_c_review_severity(flags: list[str]) -> str:
    severity = "info"
    for flag in flags:
        flag_severity = _STAGE_C_FLAG_SEVERITY.get(str(flag), "review")
        if _STAGE_C_SEVERITY_RANK[flag_severity] > _STAGE_C_SEVERITY_RANK[severity]:
            severity = flag_severity
    return severity


def _stage_c_review_next_actions(flags: list[str]) -> list[str]:
    actions: list[str] = []
    flag_set = set(flags)
    if "report_quality_block" in flag_set:
        actions.append("Review report-quality critical issues before publishing.")
    if "report_quality_unavailable" in flag_set:
        actions.append("Rerun report-quality after fixing LLM/schema response.")
    if {
        "valuation_commercial_method_drift",
        "valuation_balance_sheet_method_drift",
        "valuation_duplicate_component_ranges",
    } & flag_set:
        actions.append(
            "Inspect valuation pod roles for rNPV leakage, duplicated ranges, or double counting."
        )
    if {
        "valuation_missing_market_implied_value",
        "valuation_missing_scenario_repricing_range",
        "valuation_overvaluation_language_without_market_bridge",
    } & flag_set:
        actions.append(
            "Add or verify market-implied assumptions and scenario repricing bridge."
        )
    if "valuation_rnpv_as_sole_fair_value_language" in flag_set:
        actions.append("Rewrite rNPV framing as a conservative floor or cross-check.")
    if {
        "missing_decision_log_artifact",
        "decision_log_missing_next_review_trigger",
    } & flag_set:
        actions.append(
            "Run or inspect decision-debate so decision logs include observable review triggers."
        )
    if not actions and flags:
        actions.append("Review flagged Stage B/C artifacts manually.")
    return actions[:5]


def _stage_c_review_entry_has_flags(
    entry: dict[str, Any],
    flags: tuple[str, ...],
) -> bool:
    entry_flags = {
        _norm_artifact_query(str(flag))
        for flag in (entry.get("review_flags") or [])
    }
    return all(_norm_artifact_query(flag) in entry_flags for flag in flags)


def _stage_c_review_meets_min_severity(
    entry: dict[str, Any],
    min_severity: str,
) -> bool:
    requested = str(min_severity or "").strip().casefold()
    if requested not in _STAGE_C_SEVERITY_RANK:
        return True
    actual = str(entry.get("review_severity") or "info")
    return _STAGE_C_SEVERITY_RANK.get(actual, 0) >= _STAGE_C_SEVERITY_RANK[requested]


def _stage_c_latest_per_identity(
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for entry in entries:
        key = _stage_c_identity_key(entry)
        if key in latest:
            continue
        latest[key] = entry
    return list(latest.values())


def _stage_c_identity_key(entry: dict[str, Any]) -> str:
    identity = entry.get("identity")
    if isinstance(identity, dict):
        ticker = str(identity.get("ticker") or "").strip().casefold()
        if ticker:
            return f"ticker:{ticker}"
        company = str(identity.get("company") or "").strip().casefold()
        if company:
            return f"company:{company}"
    artifact_dir = str(entry.get("artifact_dir") or "").strip().casefold()
    return f"dir:{artifact_dir}"


def _stage_c_review_entry_matches_query(
    entry: dict[str, Any],
    query: str,
) -> bool:
    needle = _norm_artifact_query(query)
    if not needle:
        return True
    identity = entry.get("identity")
    identity_values = []
    if isinstance(identity, dict):
        identity_values.extend(
            str(identity.get(key) or "")
            for key in ("company", "ticker", "market")
        )
    values = [
        str(entry.get("artifact_dir") or ""),
        str(entry.get("run_id") or ""),
        *identity_values,
    ]
    return any(needle in _norm_artifact_query(value) for value in values)


def _norm_artifact_query(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _stage_c_flag_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _has_nonempty_string(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if not isinstance(value, list):
        return False
    return any(isinstance(item, str) and item.strip() for item in value)


def _decision_log_history_change_summary(
    entries: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(entries) < 2:
        return None
    latest = entries[0]
    previous = entries[1]
    latest_summary = (
        latest.get("summary") if isinstance(latest.get("summary"), dict) else {}
    )
    previous_summary = (
        previous.get("summary") if isinstance(previous.get("summary"), dict) else {}
    )
    latest_log = (
        latest.get("decision_log")
        if isinstance(latest.get("decision_log"), dict)
        else {}
    )
    previous_log = (
        previous.get("decision_log")
        if isinstance(previous.get("decision_log"), dict)
        else {}
    )
    return {
        "latest_run_id": latest.get("run_id"),
        "previous_run_id": previous.get("run_id"),
        "current_decision_changed": latest_summary.get("current_decision")
        != previous_summary.get("current_decision"),
        "fundamental_view_changed": latest_summary.get("fundamental_view")
        != previous_summary.get("fundamental_view"),
        "timing_view_changed": latest_summary.get("timing_view")
        != previous_summary.get("timing_view"),
        "new_evidence_gaps": _list_delta(
            latest_log.get("evidence_gaps"),
            previous_log.get("evidence_gaps"),
        ),
        "repeated_evidence_gaps": _list_intersection(
            latest_log.get("evidence_gaps"),
            previous_log.get("evidence_gaps"),
        ),
        "new_invalidation_triggers": _list_delta(
            latest_log.get("invalidation_triggers"),
            previous_log.get("invalidation_triggers"),
        ),
        "repeated_invalidation_triggers": _list_intersection(
            latest_log.get("invalidation_triggers"),
            previous_log.get("invalidation_triggers"),
        ),
    }


def _list_delta(current: Any, previous: Any) -> list[str]:
    previous_set = {_norm_history_text(item) for item in _string_list(previous)}
    return [
        item
        for item in _string_list(current)
        if _norm_history_text(item) not in previous_set
    ]


def _list_intersection(current: Any, previous: Any) -> list[str]:
    previous_set = {_norm_history_text(item) for item in _string_list(previous)}
    return [
        item
        for item in _string_list(current)
        if _norm_history_text(item) in previous_set
    ]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _norm_history_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _build_hkexnews_summary(result: CompanyReportResult) -> dict[str, Any] | None:
    path = result.hkexnews_updates_path
    if path is None:
        return None
    payload_path = Path(path)
    if not payload_path.exists():
        return {"path": str(payload_path), "available": False}
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(payload_path), "available": False}
    typed = payload.get("typed_new_items")
    return {
        "path": str(payload_path),
        "available": True,
        "item_count": payload.get("item_count", 0),
        "new_count": payload.get("new_count", 0),
        "typed_new_items": typed if isinstance(typed, list) else [],
    }


def _report_quality_summary(result: CompanyReportResult) -> dict[str, Any] | None:
    payload = None
    if result.llm_agent_result is not None:
        facts = getattr(result.llm_agent_result, "facts", {}) or {}
        if isinstance(facts, dict):
            payload = facts.get("report_quality_payload")
    if not isinstance(payload, dict):
        return None
    return {
        "publish_gate": payload.get("publish_gate"),
        "critical_issue_count": len(payload.get("critical_issues") or []),
        "recommended_fix_count": len(payload.get("recommended_fixes") or []),
        "summary": payload.get("summary"),
    }


def _valuation_pod_summary(result: CompanyReportResult) -> dict[str, Any] | None:
    if result.llm_agent_result is None:
        return None
    facts = getattr(result.llm_agent_result, "facts", {}) or {}
    if not isinstance(facts, dict):
        return None
    payload = _valuation_pod_payload_from_llm_facts(facts)
    if not payload.get("available"):
        return None
    return payload.get("summary")


def _decision_log_summary(result: CompanyReportResult) -> dict[str, Any] | None:
    if result.decision_log_path is not None:
        artifact = _build_json_artifact_summary(result.decision_log_path)
        if isinstance(artifact, dict):
            summary = artifact.get("summary")
            if isinstance(summary, dict):
                return summary
    llm_result = result.llm_agent_result
    if llm_result is None:
        return None
    facts = getattr(llm_result, "facts", {}) or {}
    if not isinstance(facts, dict):
        return None
    payload = _decision_debate_payload_from_llm_facts(facts)
    if not payload.get("available"):
        return None
    return payload.get("summary")


def _build_json_artifact_summary(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload_path = Path(path)
    if not payload_path.exists():
        return {"path": str(payload_path), "available": False}
    try:
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"path": str(payload_path), "available": False}
    if isinstance(payload, dict):
        return {"path": str(payload_path), "available": True, **payload}
    return {"path": str(payload_path), "available": True, "payload": payload}


def _build_extraction_audit(result: CompanyReportResult) -> dict[str, Any]:
    assets = result.research_result.pipeline_assets
    warnings_by_asset, global_warnings = _pipeline_warnings_by_asset(
        result.research_result.input_validation
    )
    pipeline_snapshot = {
        "assets": [
            {
                "name": asset.name,
                "target": asset.target,
                "indication": asset.indication,
                "phase": asset.phase,
                "partner": asset.partner,
            }
            for asset in assets
        ]
    }
    excerpt = _build_source_text_excerpt(
        auto_input_artifacts=result.auto_input_artifacts,
        pipeline_snapshot=pipeline_snapshot,
        max_chars=4000,
        per_anchor_window=1200,
    )
    anchor_assets = set(excerpt.get("anchor_assets", ()) if excerpt else ())
    missing_assets = set(excerpt.get("missing_assets", ()) if excerpt else ())
    details = excerpt.get("anchor_details", ()) if excerpt else ()
    details_by_asset = {
        str(item.get("asset")): item
        for item in details
        if isinstance(item, dict) and item.get("asset")
    }

    asset_rows = []
    counts = {
        "supported": 0,
        "needs_review": 0,
        "missing_anchor": 0,
        "missing_evidence": 0,
    }
    for asset in assets:
        warnings = warnings_by_asset.get(asset.name, [])
        support = _asset_source_support(
            asset=asset,
            warnings=warnings,
            anchor_assets=anchor_assets,
            missing_assets=missing_assets,
            excerpt_available=excerpt is not None,
        )
        counts[support] = counts.get(support, 0) + 1
        evidence = asset.evidence[0] if asset.evidence else None
        row = {
            "name": asset.name,
            "source_support": support,
            "review_reasons": warnings,
            "anchor": details_by_asset.get(asset.name),
            "fields": {
                "target": _field_audit_status(asset.target, warnings, "target"),
                "indication": _field_audit_status(
                    asset.indication,
                    warnings,
                    "indication",
                ),
                "phase": _field_audit_status(asset.phase, warnings, "phase"),
                "partner": "present" if asset.partner else "not_provided",
            },
            "evidence": (
                {
                    "source": evidence.source,
                    "source_date": evidence.source_date,
                    "confidence": evidence.confidence,
                    "is_inferred": evidence.is_inferred,
                    "claim_excerpt": evidence.claim[:180],
                }
                if evidence is not None
                else None
            ),
        }
        asset_rows.append(row)

    review_assets = [
        {"name": row["name"], "reasons": row["review_reasons"][:3]}
        for row in asset_rows
        if row["review_reasons"] or row["source_support"] != "supported"
    ]
    return {
        "status": "review_required" if review_assets else "clean",
        "asset_count": len(asset_rows),
        "counts": counts,
        "global_warnings": global_warnings,
        "source_excerpt": (
            {
                "available": True,
                "anchor_count": len(anchor_assets),
                "missing_anchor_count": len(missing_assets),
                "truncated": bool(excerpt.get("truncated")),
                "publication_date": excerpt.get("publication_date"),
            }
            if excerpt
            else {"available": False}
        ),
        "top_review_assets": review_assets[:8],
        "assets": asset_rows,
    }


def _pipeline_warnings_by_asset(
    input_validation: dict[str, Any],
) -> tuple[dict[str, list[str]], list[str]]:
    report = input_validation.get("pipeline_assets")
    warnings = report.get("warnings", []) if isinstance(report, dict) else []
    by_asset: dict[str, list[str]] = {}
    global_warnings: list[str] = []
    for warning in warnings:
        text = str(warning)
        if ":" not in text:
            global_warnings.append(text)
            continue
        asset, detail = text.split(":", 1)
        by_asset.setdefault(asset.strip(), []).append(detail.strip())
    return by_asset, global_warnings


def _asset_source_support(
    *,
    asset: Any,
    warnings: list[str],
    anchor_assets: set[str],
    missing_assets: set[str],
    excerpt_available: bool,
) -> str:
    if not asset.evidence:
        return "missing_evidence"
    if excerpt_available and asset.name in missing_assets:
        return "missing_anchor"
    if warnings:
        return "needs_review"
    if excerpt_available and asset.name not in anchor_assets:
        return "missing_anchor"
    return "supported"


def _field_audit_status(
    value: str | None,
    warnings: list[str],
    field: str,
) -> str:
    marker = f"missing {field}"
    if any(marker in warning for warning in warnings):
        return "missing"
    return "present" if value else "not_provided"


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
    normalized_suffixes = tuple(_match_key(suffix) for suffix in suffixes)
    for path in files:
        stem = _match_key(path.stem)
        if not any(suffix in stem for suffix in normalized_suffixes):
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
