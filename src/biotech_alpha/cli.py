"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
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
from biotech_alpha.pipeline import (
    validate_pipeline_asset_file,
    validation_report_as_dict,
    write_pipeline_asset_template,
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
        choices=("scientific-skeptic", "pipeline-triage"),
        help=(
            "Opt-in LLM agents to run after deterministic research. Requires "
            "BIOTECH_ALPHA_LLM_API_KEY in env (see .env.example). When both "
            "agents are supplied, pipeline-triage runs first and the skeptic "
            "consumes its findings. Outputs are written to "
            "data/memos/<run_id>_llm_findings.json and a trace JSONL to "
            "data/traces/<run_id>.jsonl."
        ),
    )
    company_report_parser.add_argument(
        "--llm-trace-path",
        help=(
            "Optional override for the LLM trace JSONL path. Defaults to "
            "data/traces/<run_id>.jsonl."
        ),
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

    args = parser.parse_args(argv)
    client = ClinicalTrialsClient()

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
        market_data_provider = _resolve_market_data_provider(args.market_data)
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
            include_asset_queries=not args.no_asset_queries,
            max_asset_query_terms=args.max_asset_query_terms,
            limit=args.limit,
            save=not args.no_save,
            client=client,
            llm_agents=llm_agents,
            llm_client=llm_client,
            llm_trace_path=getattr(args, "llm_trace_path", None),
        )
        print(json.dumps(company_report_summary(result), ensure_ascii=False, indent=2))
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
                path = write_watchlist_csv(args.output, entries)
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
                print(watchlist_entries_to_csv_text(entries), end="")
            return 0

        payload = {
            "entry_count": len(entries),
            "loaded_entry_count": len(loaded_entries),
            "latest_only": args.latest_only,
            "min_quality_gate": args.min_quality_gate,
            "entries": watchlist_entries_as_dicts(entries),
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

    parser.error(f"Unknown command: {args.command}")
    return 2


def _resolve_market_data_provider(choice: str):
    """Return a market-data provider callable for a CLI choice, or None."""

    if choice == "hk-public":
        from biotech_alpha.market_data_providers import hk_public_quote_provider

        return hk_public_quote_provider
    return None


def _build_llm_client(llm_agents: tuple[str, ...]):
    """Build an LLM client from env when any LLM agent is requested."""

    if not llm_agents:
        return None
    from biotech_alpha.llm import (
        LLMConfig,
        LLMTraceRecorder,
        OpenAICompatibleLLMClient,
    )

    config = LLMConfig.from_env()
    recorder = LLMTraceRecorder()
    return OpenAICompatibleLLMClient(config, trace_recorder=recorder)


if __name__ == "__main__":
    raise SystemExit(main())
