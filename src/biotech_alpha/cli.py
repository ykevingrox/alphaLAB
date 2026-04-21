"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from biotech_alpha.clinicaltrials import (
    ClinicalTrialsClient,
    extract_trial_summaries,
    summaries_as_dicts,
)
from biotech_alpha.competition import (
    competition_validation_report_as_dict,
    validate_competitor_file,
    write_competitor_template,
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
from biotech_alpha.valuation import (
    validate_valuation_snapshot_file,
    valuation_validation_report_as_dict,
    write_valuation_snapshot_template,
)
from biotech_alpha.watchlist import (
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
            include_asset_queries=not args.no_asset_queries,
            max_asset_query_terms=args.max_asset_query_terms,
            limit=args.limit,
            output_dir=args.output_dir,
            save=not args.no_save,
            client=client,
        )
        print(json.dumps(result_summary(result), ensure_ascii=False, indent=2))
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
        entries = rank_watchlist_entries(
            load_watchlist_entries(args.processed_dir)
        )
        if args.format == "csv":
            if args.output:
                path = write_watchlist_csv(args.output, entries)
                print(
                    json.dumps(
                        {"path": str(path), "entry_count": len(entries)},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(watchlist_entries_to_csv_text(entries), end="")
            return 0

        payload = {
            "entry_count": len(entries),
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
                    {"path": str(path), "entry_count": len(entries)},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
