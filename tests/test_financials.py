from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from biotech_alpha.financials import (
    cash_runway_finding,
    estimate_cash_runway,
    financial_snapshot_template,
    load_financial_snapshot,
    validate_financial_snapshot_file,
    write_financial_snapshot_template,
)


class FinancialsTest(unittest.TestCase):
    def test_estimate_cash_runway_from_quarterly_burn(self) -> None:
        payload = {
            "as_of_date": "2025-12-31",
            "currency": "HKD",
            "cash_and_equivalents": 1200,
            "short_term_debt": 300,
            "quarterly_cash_burn": 150,
            "source": "annual-report.pdf",
            "source_date": "2026-03-28",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "financials.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snapshot = load_financial_snapshot(path)

        estimate = estimate_cash_runway(snapshot)
        finding = cash_runway_finding(
            company="Example Biotech",
            snapshot=snapshot,
            estimate=estimate,
        )

        self.assertEqual(estimate.net_cash, 900)
        self.assertEqual(estimate.monthly_cash_burn, 50)
        self.assertEqual(estimate.runway_months, 18)
        self.assertFalse(estimate.needs_human_review)
        self.assertIn("18.0 months", finding.summary)
        self.assertEqual(finding.evidence[0].source, "annual-report.pdf")

    def test_estimate_cash_runway_flags_missing_burn(self) -> None:
        payload = {
            "as_of_date": "2025-12-31",
            "currency": "HKD",
            "cash_and_equivalents": 100,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "financials.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snapshot = load_financial_snapshot(path)

        estimate = estimate_cash_runway(snapshot)

        self.assertIsNone(estimate.runway_months)
        self.assertTrue(estimate.needs_human_review)
        self.assertIn("no burn input provided", estimate.warnings)

    def test_financial_template_can_be_written_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "financials.json"

            written_path = write_financial_snapshot_template(
                path=path,
                company="Example Biotech",
                ticker="9999.HK",
            )
            payload = json.loads(written_path.read_text())
            snapshot = load_financial_snapshot(written_path)
            report = validate_financial_snapshot_file(written_path)

        self.assertEqual(payload["company"], "Example Biotech")
        self.assertEqual(payload["ticker"], "9999.HK")
        self.assertEqual(snapshot.currency, "HKD")
        self.assertEqual(report.runway_months, 18)
        self.assertIn("replace placeholder as_of_date", report.warnings)

    def test_financial_template_refuses_to_overwrite_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "financials.json"
            write_financial_snapshot_template(path=path, company="Example Biotech")

            with self.assertRaises(FileExistsError):
                write_financial_snapshot_template(
                    path=path,
                    company="Example Biotech",
                )

    def test_validate_financial_snapshot_file_reports_runway(self) -> None:
        payload = {
            "as_of_date": "2025-12-31",
            "currency": "HKD",
            "cash_and_equivalents": 1200,
            "quarterly_cash_burn": 300,
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "financials.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            report = validate_financial_snapshot_file(path)

        self.assertTrue(report.has_snapshot)
        self.assertEqual(report.runway_months, 12)
        self.assertEqual(report.errors, ())

    def test_validate_financial_snapshot_file_reports_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "financials.json"
            path.write_text(json.dumps({"currency": "HKD"}))
            report = validate_financial_snapshot_file(path)

        self.assertFalse(report.has_snapshot)
        self.assertTrue(report.errors)

    def test_financial_snapshot_template_requires_company(self) -> None:
        with self.assertRaises(ValueError):
            financial_snapshot_template(company="")


if __name__ == "__main__":
    unittest.main()
