"""One-command company report orchestration."""

from __future__ import annotations

import json
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


SUPPORTED_LLM_AGENTS = ("scientific-skeptic",)


def _run_llm_agent_pipeline(
    *,
    research_result: SingleCompanyResearchResult,
    identity: CompanyIdentity,
    llm_agents: tuple[str, ...],
    llm_client: Any,
    output_dir: str | Path,
    save: bool,
    llm_trace_path: str | Path | None,
) -> tuple[Any, Path | None]:
    """Run the opt-in LLM agent graph over a finished research result."""

    from biotech_alpha.agent_runtime import (
        AgentGraph,
        DeterministicAgent,
    )
    from biotech_alpha.agents import AgentContext
    from biotech_alpha.agents_llm import ScientificSkepticLLMAgent

    unknown = [name for name in llm_agents if name not in SUPPORTED_LLM_AGENTS]
    if unknown:
        raise ValueError(
            f"unknown llm_agents: {unknown}. "
            f"supported: {list(SUPPORTED_LLM_AGENTS)}"
        )

    facts = build_llm_agent_facts(research_result=research_result)
    context = AgentContext(
        company=identity.company,
        ticker=identity.ticker,
        market=identity.market,
    )

    trace_recorder = getattr(llm_client, "trace", None)
    graph = AgentGraph(trace_recorder=trace_recorder)

    def _publish(ctx, store):  # noqa: ANN001 - runtime adapter
        for key, value in facts.items():
            store.put(key, value)
        return None

    graph.add(DeterministicAgent("publish_research_facts", _publish))
    if "scientific-skeptic" in llm_agents:
        graph.add(
            ScientificSkepticLLMAgent(
                llm_client=llm_client,
                depends_on=("publish_research_facts",),
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
) -> dict[str, Any]:
    """Serialize a research result into the fact-store shape LLM agents expect.

    The LLM adapter layer deliberately accepts only plain dicts/lists/strings
    (and numbers). This keeps prompts reproducible: the same research result
    always renders to the same prompt body regardless of dataclass identity.
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

    return {
        "skeptic_risks": skeptic_risks,
        "pipeline_snapshot": pipeline_snapshot,
        "trial_summary": trial_summary,
        "valuation_snapshot": valuation_snapshot or None,
        "input_warnings": input_warnings,
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
    discovered: dict[str, Path | None] = {}
    for key, suffixes in INPUT_SUFFIXES.items():
        discovered[key] = _select_input_file(
            files=files,
            tokens=tokens,
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
    suffixes: tuple[str, ...],
) -> Path | None:
    candidates = []
    for path in files:
        stem = _match_key(path.stem)
        if not any(suffix in stem for suffix in suffixes):
            continue
        if not tokens or not any(token in stem for token in tokens):
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
