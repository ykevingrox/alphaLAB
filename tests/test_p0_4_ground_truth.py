from __future__ import annotations

import unittest
from pathlib import Path

from biotech_alpha.p0_4_ground_truth import (
    evaluate_p0_4_ground_truth,
    load_p0_4_ground_truth_cases,
)


class P04GroundTruthTest(unittest.TestCase):
    def test_ground_truth_harness_meets_minimum_quality(self) -> None:
        cases_path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "p0_4_ground_truth_cases.json"
        )
        cases = load_p0_4_ground_truth_cases(cases_path)
        report = evaluate_p0_4_ground_truth(cases)
        self.assertGreaterEqual(report.regulatory_pathway.f1, 0.80)
        self.assertGreaterEqual(report.next_binary_event.f1, 0.75)
        self.assertGreaterEqual(report.regulatory_pathway.exact_match_rate, 0.80)
        self.assertGreaterEqual(report.next_binary_event.exact_match_rate, 0.70)


if __name__ == "__main__":
    unittest.main()
