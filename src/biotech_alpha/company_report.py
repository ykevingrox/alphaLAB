"""One-command company report orchestration."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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


INPUT_SUFFIXES = {
    "pipeline_assets": ("pipeline_assets", "pipeline"),
    "financials": ("financials", "financial"),
    "competitors": ("competitors", "competitor"),
    "valuation": ("valuation",),
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
            "Create the valuation template, then fill market cap or share price "
            "and shares outstanding, cash, debt, revenue if available, and source."
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
    include_asset_queries: bool = True,
    max_asset_query_terms: int = 20,
    limit: int = 20,
    save: bool = True,
    client: ClinicalTrialsSource | None = None,
    now: datetime | None = None,
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
    input_paths = discover_company_inputs(identity, input_dir=input_dir)
    research_result = run_single_company_research(
        company=identity.company,
        ticker=identity.ticker,
        market=identity.market,
        search_term=identity.search_term,
        pipeline_assets_path=input_paths.pipeline_assets,
        competitors_path=input_paths.competitors,
        financials_path=input_paths.financials,
        valuation_path=input_paths.valuation,
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
        )

    return CompanyReportResult(
        identity=identity,
        input_paths=input_paths,
        missing_inputs=missing_inputs,
        missing_inputs_report=missing_report_path,
        research_result=research_result,
    )


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
        ),
        "rerun_command": company_report_rerun_command(identity),
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

    return {
        "identity": _jsonable(asdict(result.identity)),
        "research": result_summary(result.research_result),
        "discovered_inputs": _jsonable(asdict(result.input_paths)),
        "missing_input_count": len(result.missing_inputs),
        "missing_inputs": [_jsonable(asdict(item)) for item in result.missing_inputs],
        "next_actions": next_actions(
            identity=result.identity,
            missing_inputs=result.missing_inputs,
        ),
        "rerun_command": company_report_rerun_command(result.identity),
        "missing_inputs_report": (
            str(result.missing_inputs_report)
            if result.missing_inputs_report
            else None
        ),
    }


def next_actions(
    *,
    identity: CompanyIdentity,
    missing_inputs: tuple[MissingInput, ...],
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
    actions.append(f"Rerun: {company_report_rerun_command(identity)}")
    return tuple(actions)


def company_report_rerun_command(identity: CompanyIdentity) -> str:
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
        if any("a" <= character.lower() <= "z" for character in value):
            return value
    return company


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
