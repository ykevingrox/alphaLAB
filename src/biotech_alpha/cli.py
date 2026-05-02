"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence

from biotech_alpha.alerts import (
    build_catalyst_alerts,
    catalyst_alerts_as_dicts,
    catalyst_alerts_to_csv_text,
    write_catalyst_alerts_csv,
)
from biotech_alpha.clinicaltrials import (
    ClinicalTrialsClient,
    extract_trial_summaries,
    summaries_as_dicts,
)
from biotech_alpha.china_cde import (
    fetch_cde_feed,
    filter_cde_items,
    parse_cde_feed,
    track_cde_updates,
)
from biotech_alpha.company_report import company_report_summary, run_company_report
from biotech_alpha.competition import (
    competition_validation_report_as_dict,
    validate_competitor_file,
    write_competitor_template,
)
from biotech_alpha.conference import (
    conference_validation_report_as_dict,
    validate_conference_catalyst_file,
    write_conference_catalyst_template,
)
from biotech_alpha.financials import (
    financial_validation_report_as_dict,
    validate_financial_snapshot_file,
    write_financial_snapshot_template,
)
from biotech_alpha.hkexnews import (
    fetch_hkex_rss,
    filter_hkex_items_by_ticker,
    parse_hkex_rss,
    track_hkex_news_updates,
)
from biotech_alpha.pipeline import (
    validate_pipeline_asset_file,
    validation_report_as_dict,
    write_pipeline_asset_template,
)
from biotech_alpha.p3 import (
    bilingual_memo_markdown,
    export_html,
    export_pdf,
    historical_memo_diff,
    technical_timing_from_ohlcv,
)
from biotech_alpha.research import result_summary, run_single_company_research
from biotech_alpha.target_price import (
    build_target_price_analysis,
    load_target_price_assumptions,
    target_price_payload,
    target_price_summary,
    target_price_summary_csv_text,
    target_price_validation_report_as_dict,
    validate_target_price_assumptions_file,
    write_target_price_artifacts,
    write_target_price_assumptions_template,
)
from biotech_alpha.valuation import (
    validate_valuation_snapshot_file,
    valuation_validation_report_as_dict,
    write_valuation_snapshot_template,
)
from biotech_alpha.watchlist import (
    filter_watchlist_entries_by_quality_gate,
    latest_watchlist_entries,
    load_watchlist_entries,
    rank_watchlist_entries,
    watchlist_entries_as_dicts,
    watchlist_entries_to_csv_text,
    write_watchlist_csv,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biotech-alpha")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trials_parser = subparsers.add_parser(
        "clinical-trials",
        help="Search ClinicalTrials.gov and print normalized trial summaries.",
    )
    trials_parser.add_argument(
        "term",
        help="Search term, such as company or asset name.",
    )
    trials_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of studies to request. ClinicalTrials.gov allows 1-1000.",
    )

    version_parser = subparsers.add_parser(
        "clinical-trials-version",
        help="Print ClinicalTrials.gov API version metadata.",
    )
    version_parser.set_defaults(command="clinical-trials-version")

    research_parser = subparsers.add_parser(
        "research",
        help="Run the single-company research pipeline.",
    )
    research_parser.add_argument(
        "--company",
        required=True,
        help="Company name to research, such as Akeso.",
    )
    research_parser.add_argument(
        "--ticker",
        help="Optional listed ticker, such as 9926.HK.",
    )
    research_parser.add_argument(
        "--market",
        default="HK",
        help="Market label to preserve in outputs. Defaults to HK.",
    )
    research_parser.add_argument(
        "--search-term",
        help="Optional ClinicalTrials.gov search term. Defaults to company name.",
    )
    research_parser.add_argument(
        "--pipeline-assets",
        help="Optional JSON file containing disclosed pipeline assets.",
    )
    research_parser.add_argument(
        "--financials",
        help="Optional JSON file containing a financial snapshot for runway.",
    )
    research_parser.add_argument(
        "--competitors",
        help="Optional JSON file containing curated competitor assets.",
    )
    research_parser.add_argument(
        "--valuation",
        help="Optional JSON file containing a market valuation snapshot.",
    )
    research_parser.add_argument(
        "--conference-catalysts",
        help="Optional JSON file containing conference catalyst inputs.",
    )
    research_parser.add_argument(
        "--target-price-assumptions",
        help="Optional JSON file containing catalyst-adjusted target-price inputs.",
    )
    research_parser.add_argument(
        "--no-asset-queries",
        action="store_true",
        help="Do not run extra ClinicalTrials.gov searches for asset names/aliases.",
    )
    research_parser.add_argument(
        "--max-asset-query-terms",
        type=int,
        default=20,
        help="Maximum number of asset name/alias searches to add. Defaults to 20.",
    )
    research_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of ClinicalTrials.gov studies to request.",
    )
    research_parser.add_argument(
        "--output-dir",
        default="data",
        help="Directory for raw, processed, and memo artifacts. Defaults to data.",
    )
    research_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Run without writing artifacts to disk.",
    )

    company_report_parser = subparsers.add_parser(
        "company-report",
        help="Run a one-command company report with auto-discovered inputs.",
    )
    company_report_parser.add_argument(
        "--company",
        help="Company name to research, such as DualityBio or 映恩生物.",
    )
    company_report_parser.add_argument(
        "--ticker",
        help="Optional listed ticker, such as 09606.HK.",
    )
    company_report_parser.add_argument(
        "--market",
        help="Optional market label. Defaults from ticker or HK.",
    )
    company_report_parser.add_argument(
        "--sector",
        default="biotech",
        help="Sector label for future industry plugins. Defaults to biotech.",
    )
    company_report_parser.add_argument(
        "--search-term",
        help="Optional ClinicalTrials.gov search term.",
    )
    company_report_parser.add_argument(
        "--input-dir",
        default="data/input",
        help="Directory to scan for curated input files. Defaults to data/input.",
    )
    company_report_parser.add_argument(
        "--output-dir",
        default="data",
        help="Directory for raw, processed, and memo artifacts. Defaults to data.",
    )
    company_report_parser.add_argument(
        "--registry",
        default="data/input/company_registry.json",
        help="Optional company registry JSON for aliases and tickers.",
    )
    company_report_parser.add_argument(
        "--auto-inputs",
        action="store_true",
        help="Auto-generate draft pipeline and financial inputs from HKEX sources.",
    )
    company_report_parser.add_argument(
        "--generated-input-dir",
        default="data/input/generated",
        help="Directory for generated draft inputs.",
    )
    company_report_parser.add_argument(
        "--overwrite-auto-inputs",
        action="store_true",
        help="Overwrite generated draft inputs if they already exist.",
    )
    company_report_parser.add_argument(
        "--market-data",
        choices=("none", "hk-public"),
        default="none",
        help=(
            "Optional source-backed market-data provider for the valuation "
            "auto-draft. 'hk-public' queries Tencent's public HK feed first "
            "(qt.gtimg.cn) and falls back to Yahoo Finance; failures degrade "
            "to warnings and do not break the report."
        ),
    )
    company_report_parser.add_argument(
        "--market-data-freshness-days",
        type=float,
        default=None,
        help=(
            "Maximum age in days a market-data quote can have before the "
            "provider emits a staleness warning. Fractional values are "
            "allowed (e.g. 0.5 for 12 hours). Defaults to the provider's "
            "built-in freshness window (3 days for hk-public). Only "
            "meaningful together with --market-data."
        ),
    )
    company_report_parser.add_argument(
        "--competitor-discovery",
        choices=("none", "clinicaltrials"),
        default="none",
        help=(
            "Optional source-backed competitor discovery for generated "
            "competitor drafts. 'clinicaltrials' queries ClinicalTrials.gov "
            "from generated target discovery requests and writes a review-"
            "gated competitor discovery candidate pack."
        ),
    )
    company_report_parser.add_argument(
        "--competitor-discovery-max-requests",
        type=int,
        default=3,
        help=(
            "Maximum number of generated target discovery requests to send "
            "to the competitor discovery provider. Defaults to 3."
        ),
    )
    company_report_parser.add_argument(
        "--macro-signals",
        choices=("none", "yahoo-hk"),
        default="none",
        help=(
            "Optional live macro-signals feed for the MacroContextLLMAgent. "
            "'yahoo-hk' pulls HSI level / 30-day trend and USD/HKD spot "
            "from Yahoo's public chart endpoint and attaches them to the "
            "macro_context fact under 'live_signals'. Failures degrade "
            "silently (the macro agent falls back to 'insufficient_data')."
        ),
    )
    company_report_parser.add_argument(
        "--technical-features",
        choices=("none", "yfinance"),
        default="none",
        help=(
            "Optional historical price feature provider for "
            "market-regime-timing and market-expectations. 'yfinance' "
            "requires installing the optional market extra and degrades "
            "silently when unavailable."
        ),
    )
    company_report_parser.add_argument(
        "--technical-benchmark-symbol",
        default="^HSI",
        help=(
            "Benchmark symbol for technical relative strength when "
            "--technical-features is enabled. Defaults to ^HSI."
        ),
    )
    company_report_parser.add_argument(
        "--macro-signals-cache-ttl-hours",
        type=float,
        default=6.0,
        help=(
            "TTL in hours for the disk-backed macro-signals cache. "
            "Macro signals (HSI, USD/HKD) are shared across every company "
            "in the same market, so one successful fetch per TTL serves "
            "every run in the same session. Default 6 hours; set to 0 "
            "to force a fresh fetch every run. Only meaningful together "
            "with --macro-signals."
        ),
    )
    company_report_parser.add_argument(
        "--no-macro-signals-cache",
        action="store_true",
        help=(
            "Bypass the macro-signals disk cache entirely. Equivalent to "
            "--macro-signals-cache-ttl-hours 0 but also disables the "
            "stale-if-error fallback."
        ),
    )
    company_report_parser.add_argument(
        "--hkexnews-feed-url",
        help="Optional HKEXnews RSS URL for change tracking artifacts.",
    )
    company_report_parser.add_argument(
        "--hkexnews-feed-file",
        help="Optional local HKEXnews RSS XML file path for offline tracking.",
    )
    company_report_parser.add_argument(
        "--hkexnews-state-file",
        default="data/cache/hkexnews/seen_guids.json",
        help="Path to persist seen HKEXnews GUID state across runs.",
    )
    company_report_parser.add_argument(
        "--cde-feed-url",
        help="Optional China CDE feed URL for change tracking artifacts.",
    )
    company_report_parser.add_argument(
        "--cde-feed-file",
        help="Optional local China CDE XML file path for offline tracking.",
    )
    company_report_parser.add_argument(
        "--cde-state-file",
        default="data/cache/cde/seen_guids.json",
        help="Path to persist seen China CDE GUID state across runs.",
    )
    company_report_parser.add_argument(
        "--cde-query",
        help="Optional China CDE query keyword (defaults to company name).",
    )
    company_report_parser.add_argument(
        "--no-asset-queries",
        action="store_true",
        help="Do not run extra ClinicalTrials.gov searches for asset names/aliases.",
    )
    company_report_parser.add_argument(
        "--max-asset-query-terms",
        type=int,
        default=20,
        help="Maximum number of asset name/alias searches to add. Defaults to 20.",
    )
    company_report_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of ClinicalTrials.gov studies to request.",
    )
    company_report_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Run without writing artifacts to disk.",
    )
    company_report_parser.add_argument(
        "--llm-agents",
        nargs="*",
        default=(),
        choices=(
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
        ),
        help=(
            "Opt-in LLM agents to run after deterministic research. "
            "Requires provider-specific env keys (see .env.example): "
            "BIOTECH_ALPHA_LLM_API_KEY/DASHSCOPE_API_KEY for "
            "openai-compatible, or ANTHROPIC_API_KEY when "
            "BIOTECH_ALPHA_LLM_PROVIDER=anthropic. When triage agents are "
            "combined with the skeptic, triage runs first and the skeptic "
            "consumes their findings through the FactStore. Outputs are "
            "written to data/memos/<run_id>_llm_findings.json and a trace "
            "JSONL to data/traces/<run_id>.jsonl."
        ),
    )
    company_report_parser.add_argument(
        "--llm-trace-path",
        help=(
            "Optional override for the LLM trace JSONL path. Defaults to "
            "data/traces/<run_id>.jsonl."
        ),
    )
    quick_report_parser = subparsers.add_parser(
        "report",
        help=(
            "Ultra-simple one-command entry: one company/ticker in, report out."
        ),
    )
    quick_report_parser.add_argument(
        "query",
        help="Company name or ticker (e.g. DualityBio or 09606.HK).",
    )
    quick_report_parser.add_argument(
        "--output-dir",
        default="data",
        help="Directory for report artifacts. Defaults to data.",
    )
    quick_report_parser.add_argument(
        "--input-dir",
        default="data/input",
        help="Directory to scan for curated input files. Defaults to data/input.",
    )
    quick_report_parser.add_argument(
        "--registry",
        default="data/input/company_registry.json",
        help="Optional company registry JSON for aliases and tickers.",
    )
    quick_report_parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Force deterministic-only mode (skip all LLM agents).",
    )
    quick_report_parser.add_argument(
        "--no-competitor-discovery",
        action="store_true",
        help="Skip ClinicalTrials.gov competitor discovery in quick mode.",
    )
    quick_report_parser.add_argument(
        "--competitor-discovery-max-requests",
        type=int,
        default=3,
        help=(
            "Maximum number of generated target discovery requests to send "
            "to ClinicalTrials.gov in quick mode. Defaults to 3."
        ),
    )
    quick_report_parser.add_argument(
        "--allow-no-llm",
        action="store_true",
        help=(
            "Deprecated compatibility flag. Quick report now auto-degrades to "
            "deterministic mode when LLM is unavailable."
        ),
    )
    quick_report_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Run without writing artifacts to disk.",
    )
    quick_report_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the compact machine-readable JSON summary.",
    )
    quick_report_parser.add_argument(
        "--hkexnews-feed-url",
        help="Optional HKEXnews RSS URL for change tracking artifacts.",
    )
    quick_report_parser.add_argument(
        "--hkexnews-feed-file",
        help="Optional local HKEXnews RSS XML file path for offline tracking.",
    )
    quick_report_parser.add_argument(
        "--hkexnews-state-file",
        default="data/cache/hkexnews/seen_guids.json",
        help="Path to persist seen HKEXnews GUID state across runs.",
    )
    quick_report_parser.add_argument(
        "--cde-feed-url",
        help="Optional China CDE feed URL for change tracking artifacts.",
    )
    quick_report_parser.add_argument(
        "--cde-feed-file",
        help="Optional local China CDE XML file path for offline tracking.",
    )
    quick_report_parser.add_argument(
        "--cde-state-file",
        default="data/cache/cde/seen_guids.json",
        help="Path to persist seen China CDE GUID state across runs.",
    )
    quick_report_parser.add_argument(
        "--cde-query",
        help="Optional China CDE query keyword (defaults to company name).",
    )

    template_parser = subparsers.add_parser(
        "pipeline-template",
        help="Write a starter JSON file for disclosed pipeline assets.",
    )
    template_parser.add_argument(
        "--company",
        required=True,
        help="Company name for the template metadata.",
    )
    template_parser.add_argument(
        "--ticker",
        help="Optional listed ticker for the template metadata.",
    )
    template_parser.add_argument(
        "--output",
        required=True,
        help="Output JSON path, such as data/input/akeso_pipeline_assets.json.",
    )
    template_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )

    validate_parser = subparsers.add_parser(
        "pipeline-validate",
        help="Validate a curated pipeline asset JSON file.",
    )
    validate_parser.add_argument(
        "path",
        help="Pipeline asset JSON file to validate.",
    )

    financial_template_parser = subparsers.add_parser(
        "financial-template",
        help="Write a starter JSON file for financial snapshot inputs.",
    )
    financial_template_parser.add_argument(
        "--company",
        required=True,
        help="Company name for the template metadata.",
    )
    financial_template_parser.add_argument(
        "--ticker",
        help="Optional listed ticker for the template metadata.",
    )
    financial_template_parser.add_argument(
        "--output",
        required=True,
        help="Output JSON path, such as data/input/akeso_financials.json.",
    )
    financial_template_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )

    financial_validate_parser = subparsers.add_parser(
        "financial-validate",
        help="Validate a financial snapshot JSON file.",
    )
    financial_validate_parser.add_argument(
        "path",
        help="Financial snapshot JSON file to validate.",
    )

    competitor_template_parser = subparsers.add_parser(
        "competitor-template",
        help="Write a starter JSON file for competitive landscape inputs.",
    )
    competitor_template_parser.add_argument(
        "--company",
        required=True,
        help="Company name for the template metadata.",
    )
    competitor_template_parser.add_argument(
        "--ticker",
        help="Optional listed ticker for the template metadata.",
    )
    competitor_template_parser.add_argument(
        "--output",
        required=True,
        help="Output JSON path, such as data/input/akeso_competitors.json.",
    )
    competitor_template_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )

    competitor_validate_parser = subparsers.add_parser(
        "competitor-validate",
        help="Validate a curated competitor asset JSON file.",
    )
    competitor_validate_parser.add_argument(
        "path",
        help="Competitor asset JSON file to validate.",
    )

    conference_template_parser = subparsers.add_parser(
        "conference-template",
        help="Write a starter JSON file for conference catalyst inputs.",
    )
    conference_template_parser.add_argument(
        "--company",
        required=True,
        help="Company name for the template metadata.",
    )
    conference_template_parser.add_argument(
        "--ticker",
        help="Optional listed ticker for the template metadata.",
    )
    conference_template_parser.add_argument(
        "--output",
        required=True,
        help="Output JSON path, such as data/input/akeso_conference_catalysts.json.",
    )
    conference_template_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )

    conference_validate_parser = subparsers.add_parser(
        "conference-validate",
        help="Validate a curated conference catalyst JSON file.",
    )
    conference_validate_parser.add_argument(
        "path",
        help="Conference catalyst JSON file to validate.",
    )

    valuation_template_parser = subparsers.add_parser(
        "valuation-template",
        help="Write a starter JSON file for valuation snapshot inputs.",
    )
    valuation_template_parser.add_argument(
        "--company",
        required=True,
        help="Company name for the template metadata.",
    )
    valuation_template_parser.add_argument(
        "--ticker",
        help="Optional listed ticker for the template metadata.",
    )
    valuation_template_parser.add_argument(
        "--output",
        required=True,
        help="Output JSON path, such as data/input/akeso_valuation.json.",
    )
    valuation_template_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )

    valuation_validate_parser = subparsers.add_parser(
        "valuation-validate",
        help="Validate a valuation snapshot JSON file.",
    )
    valuation_validate_parser.add_argument(
        "path",
        help="Valuation snapshot JSON file to validate.",
    )

    watchlist_parser = subparsers.add_parser(
        "watchlist-rank",
        help="Rank saved single-company research runs by watchlist score.",
    )
    watchlist_parser.add_argument(
        "--processed-dir",
        default="data/processed/single_company",
        help="Directory containing saved single-company processed artifacts.",
    )
    watchlist_parser.add_argument(
        "--format",
        choices=("json", "csv"),
        default="json",
        help="Output format. Defaults to json.",
    )
    watchlist_parser.add_argument(
        "--output",
        help="Optional file path to write the ranked watchlist.",
    )
    watchlist_parser.add_argument(
        "--latest-only",
        action="store_true",
        help="Keep only the newest saved run for each company or ticker.",
    )
    watchlist_parser.add_argument(
        "--min-quality-gate",
        choices=("incomplete", "research_ready_with_review", "decision_ready"),
        help="Keep only entries at or above this quality gate level.",
    )
    watchlist_parser.add_argument(
        "--with-scorecard-dimensions",
        action="store_true",
        help=(
            "Include per-dimension score/weight/contribution fields in "
            "watchlist JSON rows and expanded CSV columns."
        ),
    )

    alerts_parser = subparsers.add_parser(
        "catalyst-alerts",
        help="Compare recent saved runs and report catalyst calendar changes.",
    )
    alerts_parser.add_argument(
        "--processed-dir",
        default="data/processed/single_company",
        help="Directory containing saved single-company processed artifacts.",
    )
    alerts_parser.add_argument(
        "--format",
        choices=("json", "csv"),
        default="json",
        help="Output format. Defaults to json.",
    )
    alerts_parser.add_argument(
        "--output",
        help="Optional file path to write catalyst alerts.",
    )
    hkexnews_parser = subparsers.add_parser(
        "hkexnews-track",
        help="Track new HKEXnews RSS announcements since last run.",
    )
    hkexnews_parser.add_argument(
        "--feed-url",
        help="HKEXnews RSS URL. Provide this or --feed-file.",
    )
    hkexnews_parser.add_argument(
        "--feed-file",
        help="Local RSS XML file path. Useful for offline checks/tests.",
    )
    hkexnews_parser.add_argument(
        "--ticker",
        help="Optional ticker filter (e.g., 09887.HK).",
    )
    hkexnews_parser.add_argument(
        "--state-file",
        default="data/cache/hkexnews/seen_guids.json",
        help="Path used to persist seen announcement GUIDs.",
    )
    hkexnews_parser.add_argument(
        "--output",
        help="Optional file path to write JSON output.",
    )
    cde_parser = subparsers.add_parser(
        "cde-track",
        help="Track new China CDE feed updates since last run.",
    )
    cde_parser.add_argument(
        "--feed-url",
        help="China CDE feed URL. Provide this or --feed-file.",
    )
    cde_parser.add_argument(
        "--feed-file",
        help="Local feed XML file path for offline checks/tests.",
    )
    cde_parser.add_argument(
        "--query",
        help="Optional query filter (company, asset, indication keyword).",
    )
    cde_parser.add_argument(
        "--state-file",
        default="data/cache/cde/seen_guids.json",
        help="Path used to persist seen CDE GUIDs.",
    )
    cde_parser.add_argument(
        "--output",
        help="Optional file path to write JSON output.",
    )

    target_price_template_parser = subparsers.add_parser(
        "target-price-template",
        help="Write a starter JSON file for target-price assumptions.",
    )
    target_price_template_parser.add_argument(
        "--company",
        required=True,
        help="Company name for the template metadata.",
    )
    target_price_template_parser.add_argument(
        "--ticker",
        help="Optional listed ticker for the template metadata.",
    )
    target_price_template_parser.add_argument(
        "--output",
        required=True,
        help=(
            "Output JSON path, such as "
            "data/input/akeso_target_price_assumptions.json."
        ),
    )
    target_price_template_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )

    target_price_validate_parser = subparsers.add_parser(
        "target-price-validate",
        help="Validate a target-price assumptions JSON file.",
    )
    target_price_validate_parser.add_argument(
        "path",
        help="Target-price assumptions JSON file to validate.",
    )

    event_impact_parser = subparsers.add_parser(
        "event-impact",
        help="Calculate catalyst-adjusted target-price scenarios.",
    )
    event_impact_parser.add_argument(
        "--company",
        required=True,
        help="Company name for artifact paths and output labels.",
    )
    event_impact_parser.add_argument(
        "--assumptions",
        required=True,
        help="Target-price assumptions JSON file to calculate.",
    )
    event_impact_parser.add_argument(
        "--output-dir",
        default="data/processed/target_price",
        help="Directory for event-impact artifacts.",
    )
    event_impact_parser.add_argument(
        "--format",
        choices=("json", "csv"),
        default="json",
        help="Output format for stdout. Defaults to json.",
    )
    event_impact_parser.add_argument(
        "--no-save",
        action="store_true",
        help="Run without writing target-price artifacts to disk.",
    )
    technical_parser = subparsers.add_parser(
        "technical-timing",
        help="Build deterministic technical timing summary from OHLCV CSV.",
    )
    technical_parser.add_argument(
        "--ohlcv",
        required=True,
        help="OHLCV CSV path with at least close column.",
    )
    technical_parser.add_argument(
        "--symbol",
        help="Optional company/security symbol for the feature payload.",
    )
    technical_parser.add_argument(
        "--provider",
        default="csv",
        help="Provider label for the feature payload. Defaults to csv.",
    )
    technical_parser.add_argument(
        "--benchmark-ohlcv",
        help="Optional benchmark OHLCV CSV path for relative strength.",
    )
    technical_parser.add_argument(
        "--benchmark-symbol",
        help="Optional benchmark symbol label, such as ^HSI.",
    )
    technical_parser.add_argument(
        "--output",
        help="Optional output JSON path.",
    )
    memo_diff_parser = subparsers.add_parser(
        "memo-diff",
        help="Diff two memo markdown files.",
    )
    memo_diff_parser.add_argument("--previous", required=True, help="Previous memo path.")
    memo_diff_parser.add_argument("--current", required=True, help="Current memo path.")
    memo_diff_parser.add_argument("--output", help="Optional output JSON path.")
    bilingual_parser = subparsers.add_parser(
        "memo-bilingual",
        help="Export bilingual markdown from an English memo.",
    )
    bilingual_parser.add_argument("--input", required=True, help="Input memo markdown path.")
    bilingual_parser.add_argument("--output", required=True, help="Output bilingual markdown path.")
    export_parser = subparsers.add_parser(
        "memo-export",
        help="Export memo markdown to HTML and optional PDF.",
    )
    export_parser.add_argument("--input", required=True, help="Input memo markdown path.")
    export_parser.add_argument("--html-output", required=True, help="Output HTML path.")
    export_parser.add_argument("--pdf-output", help="Optional output PDF path.")
    export_parser.add_argument(
        "--pipeline-assets",
        help="Optional pipeline-assets JSON path for gantt chart rendering.",
    )
    export_parser.add_argument(
        "--catalyst-csv",
        help="Optional catalyst calendar CSV path for timeline rendering.",
    )
    export_parser.add_argument(
        "--target-price-json",
        help="Optional target-price JSON path for rNPV stack rendering.",
    )

    args = parser.parse_args(argv)
    client = ClinicalTrialsClient(timeout=8)

    if args.command == "clinical-trials":
        response = client.search_studies(args.term, page_size=args.limit)
        summaries = extract_trial_summaries(response)
        print(json.dumps(summaries_as_dicts(summaries), ensure_ascii=False, indent=2))
        return 0

    if args.command == "clinical-trials-version":
        print(json.dumps(client.version(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "research":
        result = run_single_company_research(
            company=args.company,
            ticker=args.ticker,
            market=args.market,
            search_term=args.search_term,
            pipeline_assets_path=args.pipeline_assets,
            competitors_path=args.competitors,
            financials_path=args.financials,
            valuation_path=args.valuation,
            conference_catalysts_path=args.conference_catalysts,
            target_price_assumptions_path=args.target_price_assumptions,
            include_asset_queries=not args.no_asset_queries,
            max_asset_query_terms=args.max_asset_query_terms,
            limit=args.limit,
            output_dir=args.output_dir,
            save=not args.no_save,
            client=client,
        )
        print(json.dumps(result_summary(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "company-report":
        market_data_provider = _resolve_market_data_provider(
            args.market_data,
            freshness_days=args.market_data_freshness_days,
        )
        macro_signals_provider = _resolve_macro_signals_provider(
            getattr(args, "macro_signals", "none"),
            cache_ttl_hours=getattr(
                args, "macro_signals_cache_ttl_hours", 6.0
            ),
            disable_cache=getattr(args, "no_macro_signals_cache", False),
        )
        technical_features_provider = _resolve_technical_features_provider(
            getattr(args, "technical_features", "none"),
            benchmark_symbol=getattr(args, "technical_benchmark_symbol", None),
        )
        llm_agents = tuple(getattr(args, "llm_agents", ()) or ())
        llm_client = _build_llm_client(llm_agents)
        result = run_company_report(
            company=args.company,
            ticker=args.ticker,
            market=args.market,
            sector=args.sector,
            search_term=args.search_term,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            registry_path=args.registry,
            auto_inputs=args.auto_inputs,
            generated_input_dir=args.generated_input_dir,
            overwrite_auto_inputs=args.overwrite_auto_inputs,
            market_data_provider=market_data_provider,
            competitor_discovery_client=(
                client if args.competitor_discovery == "clinicaltrials" else None
            ),
            competitor_discovery_max_requests=(
                args.competitor_discovery_max_requests
            ),
            include_asset_queries=not args.no_asset_queries,
            max_asset_query_terms=args.max_asset_query_terms,
            limit=args.limit,
            save=not args.no_save,
            client=client,
            llm_agents=llm_agents,
            llm_client=llm_client,
            llm_trace_path=getattr(args, "llm_trace_path", None),
            macro_signals_provider=macro_signals_provider,
            technical_features_provider=technical_features_provider,
            hkexnews_feed_url=getattr(args, "hkexnews_feed_url", None),
            hkexnews_feed_file=getattr(args, "hkexnews_feed_file", None),
            hkexnews_state_file=getattr(
                args,
                "hkexnews_state_file",
                "data/cache/hkexnews/seen_guids.json",
            ),
            cde_feed_url=getattr(args, "cde_feed_url", None),
            cde_feed_file=getattr(args, "cde_feed_file", None),
            cde_state_file=getattr(
                args,
                "cde_state_file",
                "data/cache/cde/seen_guids.json",
            ),
            cde_query=getattr(args, "cde_query", None),
        )
        print(json.dumps(company_report_summary(result), ensure_ascii=False, indent=2))
        return 0

    if args.command == "report":
        company, ticker = _split_company_or_ticker(args.query)
        if not args.json:
            _print_quick_report_stage(
                1,
                4,
                "Resolve query",
                _format_quick_report_identity(company=company, ticker=ticker),
            )
        llm_agents: tuple[str, ...] = ()
        llm_client = None
        if not args.no_llm:
            llm_agents = (
                "provisional-pipeline",
                "provisional-financial",
                "pipeline-triage",
                "financial-triage",
                "competition-triage",
                "macro-context",
                "scientific-skeptic",
                "investment-thesis",
                "valuation-commercial",
                "valuation-rnpv",
                "valuation-balance-sheet",
                "valuation-committee",
                "report-quality",
            )
            if not args.json:
                _print_quick_report_stage(
                    2,
                    4,
                    "Prepare LLM agents",
                    ", ".join(llm_agents),
                )
            try:
                llm_client = _build_llm_client(llm_agents)
            except Exception as exc:
                llm_agents = ()
                llm_client = None
                if not args.json:
                    _print_quick_report_note(
                        f"unavailable; continuing without LLM ({exc})",
                    )
        elif not args.json:
            _print_quick_report_stage(
                2,
                4,
                "Prepare LLM agents",
                "disabled by --no-llm",
            )

        market_data_provider = _resolve_market_data_provider("hk-public")
        macro_signals_provider = _resolve_macro_signals_provider("yahoo-hk")
        if not args.json:
            _print_quick_report_stage(
                3,
                4,
                "Run research graph",
                "auto-inputs, HK market data, macro signals, CT.gov competitors",
            )
        result = run_company_report(
            company=company,
            ticker=ticker,
            market=None,
            sector="biotech",
            search_term=None,
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            registry_path=args.registry,
            auto_inputs=True,
            generated_input_dir="data/input/generated",
            overwrite_auto_inputs=False,
            market_data_provider=market_data_provider,
            competitor_discovery_client=(
                None if args.no_competitor_discovery else client
            ),
            competitor_discovery_max_requests=(
                args.competitor_discovery_max_requests
            ),
            include_asset_queries=True,
            max_asset_query_terms=20,
            limit=20,
            save=not args.no_save,
            client=client,
            llm_agents=llm_agents,
            llm_client=llm_client,
            llm_trace_path=None,
            macro_signals_provider=macro_signals_provider,
            hkexnews_feed_url=getattr(args, "hkexnews_feed_url", None),
            hkexnews_feed_file=getattr(args, "hkexnews_feed_file", None),
            hkexnews_state_file=getattr(
                args,
                "hkexnews_state_file",
                "data/cache/hkexnews/seen_guids.json",
            ),
            cde_feed_url=getattr(args, "cde_feed_url", None),
            cde_feed_file=getattr(args, "cde_feed_file", None),
            cde_state_file=getattr(
                args,
                "cde_state_file",
                "data/cache/cde/seen_guids.json",
            ),
            cde_query=getattr(args, "cde_query", None),
        )
        summary = company_report_summary(result)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            quick_paths = _publish_quick_report_shortcuts(
                summary=summary,
                output_dir=args.output_dir,
                save=not args.no_save,
            )
            _print_quick_report_stage(
                4,
                4,
                "Report complete",
                f"run_id={_quick_report_run_id(summary)}",
            )
            _print_quick_report_summary(
                summary,
                save=not args.no_save,
                output_dir=args.output_dir,
                quick_paths=quick_paths,
            )
        return 0

    if args.command == "pipeline-template":
        path = write_pipeline_asset_template(
            path=args.output,
            company=args.company,
            ticker=args.ticker,
            overwrite=args.force,
        )
        print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "pipeline-validate":
        report = validate_pipeline_asset_file(args.path)
        print(
            json.dumps(
                validation_report_as_dict(report),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if report.errors else 0

    if args.command == "financial-template":
        path = write_financial_snapshot_template(
            path=args.output,
            company=args.company,
            ticker=args.ticker,
            overwrite=args.force,
        )
        print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "financial-validate":
        report = validate_financial_snapshot_file(args.path)
        print(
            json.dumps(
                financial_validation_report_as_dict(report),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if report.errors else 0

    if args.command == "competitor-template":
        path = write_competitor_template(
            path=args.output,
            company=args.company,
            ticker=args.ticker,
            overwrite=args.force,
        )
        print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "competitor-validate":
        report = validate_competitor_file(args.path)
        print(
            json.dumps(
                competition_validation_report_as_dict(report),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if report.errors else 0

    if args.command == "conference-template":
        path = write_conference_catalyst_template(
            path=args.output,
            company=args.company,
            ticker=args.ticker,
            overwrite=args.force,
        )
        print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "conference-validate":
        report = validate_conference_catalyst_file(args.path)
        print(
            json.dumps(
                conference_validation_report_as_dict(report),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if report.errors else 0

    if args.command == "valuation-template":
        path = write_valuation_snapshot_template(
            path=args.output,
            company=args.company,
            ticker=args.ticker,
            overwrite=args.force,
        )
        print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "valuation-validate":
        report = validate_valuation_snapshot_file(args.path)
        print(
            json.dumps(
                valuation_validation_report_as_dict(report),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if report.errors else 0

    if args.command == "watchlist-rank":
        loaded_entries = load_watchlist_entries(args.processed_dir)
        entries = (
            latest_watchlist_entries(loaded_entries)
            if args.latest_only
            else loaded_entries
        )
        entries = filter_watchlist_entries_by_quality_gate(
            entries,
            min_level=args.min_quality_gate,
        )
        entries = rank_watchlist_entries(entries)
        if args.format == "csv":
            if args.output:
                path = write_watchlist_csv(
                    args.output,
                    entries,
                    include_scorecard_dimensions=args.with_scorecard_dimensions,
                )
                print(
                    json.dumps(
                        {
                            "path": str(path),
                            "entry_count": len(entries),
                            "loaded_entry_count": len(loaded_entries),
                            "latest_only": args.latest_only,
                            "min_quality_gate": args.min_quality_gate,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(
                    watchlist_entries_to_csv_text(
                        entries,
                        include_scorecard_dimensions=args.with_scorecard_dimensions,
                    ),
                    end="",
                )
            return 0

        payload = {
            "entry_count": len(entries),
            "loaded_entry_count": len(loaded_entries),
            "latest_only": args.latest_only,
            "min_quality_gate": args.min_quality_gate,
            "entries": watchlist_entries_as_dicts(
                entries,
                include_scorecard_dimensions=args.with_scorecard_dimensions,
            ),
        }
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "path": str(path),
                        "entry_count": len(entries),
                        "loaded_entry_count": len(loaded_entries),
                        "latest_only": args.latest_only,
                        "min_quality_gate": args.min_quality_gate,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "catalyst-alerts":
        alerts = build_catalyst_alerts(args.processed_dir)
        if args.format == "csv":
            if args.output:
                path = write_catalyst_alerts_csv(args.output, alerts)
                print(
                    json.dumps(
                        {"path": str(path), "alert_count": len(alerts)},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(catalyst_alerts_to_csv_text(alerts), end="")
            return 0

        payload = {
            "alert_count": len(alerts),
            "alerts": catalyst_alerts_as_dicts(alerts),
        }
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {"path": str(path), "alert_count": len(alerts)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "hkexnews-track":
        if not args.feed_url and not args.feed_file:
            print(
                json.dumps(
                    {
                        "error": "Provide --feed-url or --feed-file for hkexnews-track."
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        xml_text = (
            Path(args.feed_file).read_text(encoding="utf-8")
            if args.feed_file
            else fetch_hkex_rss(args.feed_url)
        )
        items = parse_hkex_rss(xml_text)
        filtered = filter_hkex_items_by_ticker(items, ticker=args.ticker)
        payload = track_hkex_news_updates(
            items=filtered,
            state_path=args.state_file,
        )
        payload["ticker_filter"] = args.ticker
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {"path": str(path), "new_count": payload["new_count"]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "cde-track":
        if not args.feed_url and not args.feed_file:
            print(
                json.dumps(
                    {
                        "error": "Provide --feed-url or --feed-file for cde-track."
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        xml_text = (
            Path(args.feed_file).read_text(encoding="utf-8")
            if args.feed_file
            else fetch_cde_feed(args.feed_url)
        )
        items = parse_cde_feed(xml_text)
        filtered = filter_cde_items(items, query=args.query)
        payload = track_cde_updates(
            items=filtered,
            state_path=args.state_file,
        )
        payload["query"] = args.query
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {"path": str(path), "new_count": payload["new_count"]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "target-price-template":
        path = write_target_price_assumptions_template(
            path=args.output,
            company=args.company,
            ticker=args.ticker,
            overwrite=args.force,
        )
        print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "target-price-validate":
        report = validate_target_price_assumptions_file(args.path)
        print(
            json.dumps(
                target_price_validation_report_as_dict(report),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1 if report.errors else 0

    if args.command == "event-impact":
        assumptions = load_target_price_assumptions(args.assumptions)
        analysis = build_target_price_analysis(assumptions)
        artifacts = {}
        if not args.no_save:
            artifacts = {
                key: str(path)
                for key, path in write_target_price_artifacts(
                    output_dir=args.output_dir,
                    company=args.company,
                    assumptions=assumptions,
                    analysis=analysis,
                ).items()
            }
        if args.format == "csv":
            print(target_price_summary_csv_text(analysis), end="")
            return 0

        print(
            json.dumps(
                {
                    "company": args.company,
                    "summary": target_price_summary(analysis),
                    "analysis": target_price_payload(assumptions, analysis)[
                        "analysis"
                    ],
                    "artifacts": artifacts,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "technical-timing":
        payload = technical_timing_from_ohlcv(
            args.ohlcv,
            symbol=args.symbol,
            provider=args.provider,
            benchmark_path=args.benchmark_ohlcv,
            benchmark_symbol=args.benchmark_symbol,
        )
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memo-diff":
        payload = historical_memo_diff(args.previous, args.current)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memo-bilingual":
        source = Path(args.input).read_text(encoding="utf-8")
        text = bilingual_memo_markdown(source)
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(json.dumps({"path": str(path)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "memo-export":
        html_path = export_html(
            args.input,
            args.html_output,
            pipeline_assets_path=args.pipeline_assets,
            catalyst_csv_path=args.catalyst_csv,
            target_price_json_path=args.target_price_json,
        )
        payload: dict[str, object] = {"html_path": str(html_path), "pdf_path": None, "pdf_warning": None}
        if args.pdf_output:
            pdf_path, warning = export_pdf(args.input, args.pdf_output)
            payload["pdf_path"] = str(pdf_path) if pdf_path is not None else None
            payload["pdf_warning"] = warning
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _resolve_market_data_provider(
    choice: str, *, freshness_days: float | None = None,
):
    """Return a market-data provider callable for a CLI choice, or None.

    When ``freshness_days`` is provided and the chosen provider supports the
    keyword, the callable is wrapped so the staleness window is applied
    without the caller needing to care about the underlying provider
    identity.
    """

    if choice == "hk-public":
        from functools import partial

        from biotech_alpha.market_data_providers import (
            hk_public_quote_provider,
        )

        if freshness_days is None:
            return hk_public_quote_provider
        if freshness_days <= 0:
            raise ValueError(
                "--market-data-freshness-days must be a positive number"
            )
        return partial(
            hk_public_quote_provider, freshness_days=freshness_days
        )
    if freshness_days is not None and choice == "none":
        raise ValueError(
            "--market-data-freshness-days requires --market-data to be set "
            "to a real provider (e.g. hk-public)"
        )
    return None


def _resolve_macro_signals_provider(
    choice: str,
    *,
    cache_ttl_hours: float | None = 6.0,
    disable_cache: bool = False,
):
    """Return a macro-signals provider callable for a CLI choice, or None.

    When a real provider is selected, the returned callable is wrapped
    in :class:`CachingMacroSignalsProvider` so every company in the
    same session reuses a single fresh fetch. Pass
    ``disable_cache=True`` (or ``cache_ttl_hours=0``) to return the
    bare provider without the cache wrapper.

    Providers are only consulted when ``macro-context`` is also in
    ``--llm-agents``; ``_run_llm_agent_pipeline`` guards the call so
    selecting ``--macro-signals yahoo-hk`` without the macro agent is a
    no-op rather than an error.
    """

    if choice != "yahoo-hk":
        return None

    from biotech_alpha.macro_signals_providers import (
        CachingMacroSignalsProvider,
        DEFAULT_CACHE_DIR,
        FallbackMacroSignalsProvider,
        hk_macro_signals_stooq,
        hk_macro_signals_yahoo,
    )
    composite = FallbackMacroSignalsProvider(
        providers=[
            ("yahoo-hk", hk_macro_signals_yahoo),
            ("stooq-hk", hk_macro_signals_stooq),
        ]
    )

    if disable_cache:
        return composite
    if cache_ttl_hours is not None and cache_ttl_hours <= 0:
        return composite
    from datetime import timedelta

    ttl = timedelta(hours=cache_ttl_hours or 6.0)
    return CachingMacroSignalsProvider(
        inner=composite,
        provider_label="yahoo-hk+stooq-hk",
        cache_dir=DEFAULT_CACHE_DIR,
        ttl=ttl,
    )


def _resolve_technical_features_provider(
    choice: str,
    *,
    benchmark_symbol: str | None = "^HSI",
):
    """Return a technical-feature provider for a CLI choice, or None."""

    if choice != "yfinance":
        return None

    def _provider(identity):  # noqa: ANN001 - simple CLI adapter
        from biotech_alpha.yfinance_provider import (
            yfinance_technical_feature_payload_for_identity,
        )

        return yfinance_technical_feature_payload_for_identity(
            identity,
            benchmark_symbol=benchmark_symbol,
        )

    return _provider


def _build_llm_client(llm_agents: tuple[str, ...]):
    """Build an LLM client from env when any LLM agent is requested."""

    if not llm_agents:
        return None
    from biotech_alpha.llm import (
        AnthropicLLMClient,
        LLMConfig,
        LLMTraceRecorder,
        OpenAICompatibleLLMClient,
    )

    config = LLMConfig.from_env()
    recorder = LLMTraceRecorder()
    if config.provider == "anthropic":
        return AnthropicLLMClient(config, trace_recorder=recorder)
    return OpenAICompatibleLLMClient(config, trace_recorder=recorder)


def _print_quick_report_stage(
    step: int,
    total: int,
    title: str,
    detail: str,
) -> None:
    """Print one human-readable progress stage for the quick report."""

    print(f"[{step}/{total}] {title}: {detail}")


def _print_quick_report_note(detail: str) -> None:
    print(f"      {detail}")


def _format_quick_report_identity(
    *,
    company: str | None,
    ticker: str | None,
) -> str:
    if ticker:
        return ticker
    return company or "unknown company"


def _print_quick_report_summary(
    summary: dict[str, object],
    *,
    save: bool,
    output_dir: str | Path = "data",
    quick_paths: dict[str, str] | None = None,
) -> None:
    """Print a compact operator-facing summary for ``report``."""

    identity = _dict_value(summary, "identity")
    research = _dict_value(summary, "research")
    quality_gate = _dict_value(summary, "quality_gate")
    artifacts = _dict_value(research, "artifacts")

    company = (
        _string_value(identity, "company")
        or _string_value(research, "company")
        or "Unknown company"
    )
    ticker = _string_value(identity, "ticker") or _string_value(
        research, "ticker"
    )
    ticker_text = f" ({ticker})" if ticker else ""
    quality_level = _string_value(quality_gate, "level") or "unknown"
    quality_reason = _string_value(quality_gate, "rationale") or "no rationale"
    decision = _string_value(research, "decision") or "unknown"
    bucket = _string_value(research, "watchlist_bucket") or "unknown"
    score = research.get("watchlist_score", "n/a")

    print()
    print("Result")
    print(f"Company: {company}{ticker_text}")
    print(f"Quality gate: {quality_level} ({quality_reason})")
    print(f"Decision: {decision}")
    print(f"Watchlist: {bucket} (score {score})")
    print(
        "Coverage: "
        f"{research.get('pipeline_asset_count', 0)} assets, "
        f"{research.get('trial_count', 0)} trials, "
        f"{research.get('competitor_asset_count', 0)} competitors, "
        f"{research.get('catalyst_count', 0)} catalysts"
    )

    missing_count = summary.get("missing_input_count", 0)
    warning_count = research.get("input_warning_count", 0)
    print(f"Review load: {missing_count} missing inputs, {warning_count} warnings")
    _print_quick_report_extraction_audit(summary)
    _print_quick_report_llm_summary(summary)
    _print_quick_report_artifacts(
        summary=summary,
        research=research,
        artifacts=artifacts,
        save=save,
        output_dir=output_dir,
        quick_paths=quick_paths or {},
    )
    _print_quick_report_next_action(summary)


def _print_quick_report_extraction_audit(summary: dict[str, object]) -> None:
    audit = _dict_value(summary, "extraction_audit")
    if not audit:
        return
    counts = _dict_value(audit, "counts")
    source = _dict_value(audit, "source_excerpt")
    asset_count = audit.get("asset_count", 0)
    supported = counts.get("supported", 0)
    review = counts.get("needs_review", 0)
    missing_anchor = counts.get("missing_anchor", 0)
    source_text = "source unavailable"
    if source:
        source_text = (
            f"{source.get('anchor_count', 0)} anchors, "
            f"{source.get('missing_anchor_count', 0)} missing anchors"
        )
    print(
        "Extraction audit: "
        f"{supported}/{asset_count} supported, {review} need review, "
        f"{missing_anchor} missing anchors ({source_text})"
    )
    focus = audit.get("top_review_assets")
    if not isinstance(focus, list) or not focus:
        return
    parts = []
    for item in focus[:3]:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        reasons = item.get("reasons")
        reason_text = "review source"
        if isinstance(reasons, list) and reasons:
            reason_text = "; ".join(str(reason) for reason in reasons[:2])
        if name:
            parts.append(f"{name} ({reason_text})")
    if parts:
        print("Audit focus: " + "; ".join(parts))


def _print_quick_report_llm_summary(summary: dict[str, object]) -> None:
    llm_agents = _dict_value(summary, "llm_agents")
    if not llm_agents:
        print("LLM agents: not run")
        return

    steps = llm_agents.get("steps", ())
    if not isinstance(steps, list):
        steps = []
    ok_count = sum(1 for step in steps if isinstance(step, dict) and step.get("ok"))
    skipped_count = sum(
        1 for step in steps if isinstance(step, dict) and step.get("skipped")
    )
    failed_count = len(steps) - ok_count - skipped_count
    cost = llm_agents.get("cost_summary", {})
    total_tokens = None
    if isinstance(cost, dict):
        total_tokens = cost.get("total_tokens")
    token_text = f", {total_tokens} tokens" if total_tokens is not None else ""
    print(
        "LLM agents: "
        f"{ok_count}/{len(steps)} ok, {failed_count} failed, "
        f"{skipped_count} skipped{token_text}"
    )
    fallback_modules = llm_agents.get("fallback_modules")
    if isinstance(fallback_modules, list) and fallback_modules:
        print("LLM fallback modules: " + ", ".join(str(x) for x in fallback_modules))


def _print_quick_report_artifacts(
    *,
    summary: dict[str, object],
    research: dict[str, object],
    artifacts: dict[str, object],
    save: bool,
    output_dir: str | Path,
    quick_paths: dict[str, str],
) -> None:
    print()
    print("Artifacts")
    if not save:
        print("- Not saved (--no-save)")
        return

    _print_path_line("Memo", artifacts.get("memo_markdown"))
    _print_path_line("Manifest", artifacts.get("manifest_json"))
    _print_path_line("Extraction audit report", artifacts.get("extraction_audit"))
    _print_path_line("Scorecard", artifacts.get("scorecard"))
    _print_path_line("Catalysts", artifacts.get("catalyst_calendar_csv"))
    _print_path_line("Missing-input report", summary.get("missing_inputs_report"))
    _print_path_line("LLM trace", summary.get("llm_trace_path"))
    _print_path_line("打开报告（中文）", quick_paths.get("latest_report"))
    _print_path_line("Open this folder", quick_paths.get("latest_dir"))

    llm_agents = _dict_value(summary, "llm_agents")
    run_id = _string_value(research, "run_id")
    if llm_agents and run_id:
        findings_path = Path(output_dir) / "memos" / f"{run_id}_llm_findings.json"
        _print_path_line("LLM findings", findings_path)


def _publish_quick_report_shortcuts(
    *,
    summary: dict[str, object],
    output_dir: str | Path,
    save: bool,
) -> dict[str, str]:
    if not save:
        return {}
    research = _dict_value(summary, "research")
    artifacts = _dict_value(research, "artifacts")
    memo_path = artifacts.get("memo_markdown")
    if not isinstance(memo_path, str) or not memo_path.strip():
        return {}
    source = Path(memo_path)
    if not source.exists():
        return {}
    source_text = source.read_text(encoding="utf-8")
    latest_dir = Path(output_dir) / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    latest_report_zh = latest_dir / "latest-report-zh.md"
    latest_report = latest_dir / "latest-report.md"
    bilingual = bilingual_memo_markdown(source_text)
    zh_text = _zh_only_from_bilingual(bilingual)
    latest_report.write_text(zh_text, encoding="utf-8")
    latest_report_zh.write_text(zh_text, encoding="utf-8")
    company = _string_value(_dict_value(summary, "identity"), "company") or "company"
    slug = re.sub(r"[^a-z0-9]+", "-", company.casefold()).strip("-") or "company"
    company_latest_zh = latest_dir / f"{slug}-latest-report-zh.md"
    company_latest = latest_dir / f"{slug}-latest-report.md"
    company_latest.write_text(zh_text, encoding="utf-8")
    company_latest_zh.write_text(zh_text, encoding="utf-8")
    return {
        "latest_report": str(latest_report),
        "latest_report_zh": str(latest_report_zh),
        "latest_dir": str(latest_dir),
        "company_latest_report": str(company_latest),
        "company_latest_report_zh": str(company_latest_zh),
    }


def _zh_only_from_bilingual(text: str) -> str:
    marker = "### 中文"
    if marker not in text:
        return text
    tail = text.split(marker, maxsplit=1)[1].lstrip()
    title = "## 中文报告\n\n"
    return f"{title}{tail}".rstrip() + "\n"


def _print_quick_report_next_action(summary: dict[str, object]) -> None:
    next_actions = summary.get("next_actions", ())
    if not isinstance(next_actions, list) or not next_actions:
        return
    print()
    print("Next action")
    print(f"- {next_actions[0]}")


def _quick_report_run_id(summary: dict[str, object]) -> str:
    return _string_value(_dict_value(summary, "research"), "run_id") or "unknown"


def _print_path_line(label: str, path: object) -> None:
    if path:
        print(f"- {label}: {path}")


def _dict_value(mapping: dict[str, object], key: str) -> dict[str, object]:
    value = mapping.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _string_value(mapping: dict[str, object], key: str) -> str | None:
    value = mapping.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _split_company_or_ticker(query: str) -> tuple[str | None, str | None]:
    """Return (company, ticker) for a quick-mode query string."""

    value = query.strip()
    if not value:
        raise ValueError("query must not be empty")
    normalized = value.upper().replace(" ", "")
    if re.fullmatch(r"\d{4,5}\.HK", normalized):
        return None, normalized
    return value, None


if __name__ == "__main__":
    raise SystemExit(main())
