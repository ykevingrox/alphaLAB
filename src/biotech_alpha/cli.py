"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from biotech_alpha.clinicaltrials import (
    ClinicalTrialsClient,
    extract_trial_summaries,
    summaries_as_dicts,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biotech-alpha")
    subparsers = parser.add_subparsers(dest="command", required=True)

    trials_parser = subparsers.add_parser(
        "clinical-trials",
        help="Search ClinicalTrials.gov and print normalized trial summaries.",
    )
    trials_parser.add_argument("term", help="Search term, such as company or asset name.")
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

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
