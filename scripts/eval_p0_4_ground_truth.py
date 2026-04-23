from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from biotech_alpha.p0_4_ground_truth import (
    evaluate_p0_4_ground_truth,
    load_p0_4_ground_truth_cases,
    report_to_dict,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate P0.4 extraction quality against a ground-truth set."
    )
    parser.add_argument(
        "--cases",
        default="tests/fixtures/p0_4_ground_truth_cases.json",
        help="Path to the P0.4 ground-truth cases JSON file.",
    )
    parser.add_argument(
        "--min-regulatory-f1",
        type=float,
        default=0.0,
        help="Optional minimum F1 threshold for regulatory_pathway.",
    )
    parser.add_argument(
        "--min-binary-event-f1",
        type=float,
        default=0.0,
        help="Optional minimum F1 threshold for next_binary_event.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    path = Path(args.cases)
    cases = load_p0_4_ground_truth_cases(path)
    report = evaluate_p0_4_ground_truth(cases)
    payload = report_to_dict(report)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    if report.regulatory_pathway.f1 < args.min_regulatory_f1:
        return 1
    if report.next_binary_event.f1 < args.min_binary_event_f1:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
