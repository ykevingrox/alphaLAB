from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from biotech_alpha.valuation import (
    calculate_valuation_metrics,
    load_valuation_snapshot,
    validate_valuation_snapshot_file,
    valuation_finding,
    valuation_snapshot_template,
    write_valuation_snapshot_template,
)


class ValuationTest(unittest.TestCase):
    def test_calculate_valuation_metrics_from_market_cap(self) -> None:
        payload = {
            "as_of_date": "2026-04-20",
            "currency": "HKD",
            "market_cap": 2500,
            "cash_and_equivalents": 300,
            "total_debt": 100,
            "revenue_ttm": 200,
            "source": "market-snapshot",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "valuation.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            snapshot = load_valuation_snapshot(path)

        metrics = calculate_valuation_metrics(snapshot)
        finding = valuation_finding(
            company="Example Biotech",
            snapshot=snapshot,
            metrics=metrics,
        )

        self.assertEqual(metrics.market_cap, 2500)
        self.assertEqual(metrics.enterprise_value, 2300)
        self.assertEqual(metrics.revenue_multiple, 11.5)
        self.assertFalse(metrics.needs_human_review)
        self.assertIn("11.5x revenue", finding.summary)

    def test_calculate_valuation_metrics_from_price_and_shares(self) -> None:
        payload = {
            "as_of_date": "2026-04-20",
            "currency": "HKD",
            "share_price": 10,
            "shares_outstanding": 200,
            "cash_and_equivalents": 300,
            "total_debt": 100,
            "revenue_ttm": 200,
        }

        snapshot = load_valuation_snapshot(_write_json(payload))
        metrics = calculate_valuation_metrics(snapshot)

        self.assertEqual(metrics.market_cap, 2000)
        self.assertEqual(metrics.market_cap_method, "share_price * shares_outstanding")

    def test_validate_valuation_snapshot_file_reports_warnings(self) -> None:
        payload = {
            "as_of_date": "2026-04-20",
            "currency": "HKD",
            "market_cap": 2500,
            "cash_and_equivalents": 300,
        }

        report = validate_valuation_snapshot_file(_write_json(payload))

        self.assertTrue(report.has_snapshot)
        self.assertIn(
            "revenue_ttm unavailable; revenue multiple not calculated",
            report.warnings,
        )
        self.assertIsNone(report.revenue_multiple)

    def test_valuation_template_can_be_written_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "valuation.json"
            written_path = write_valuation_snapshot_template(
                path=path,
                company="Example Biotech",
                ticker="9999.HK",
            )
            payload = json.loads(written_path.read_text())
            snapshot = load_valuation_snapshot(written_path)
            report = validate_valuation_snapshot_file(written_path)

        self.assertEqual(payload["company"], "Example Biotech")
        self.assertEqual(payload["ticker"], "9999.HK")
        self.assertEqual(snapshot.currency, "HKD")
        self.assertEqual(report.enterprise_value, 24100000000)
        self.assertIn("replace placeholder as_of_date", report.warnings)

    def test_valuation_template_refuses_to_overwrite_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "valuation.json"
            write_valuation_snapshot_template(path=path, company="Example Biotech")

            with self.assertRaises(FileExistsError):
                write_valuation_snapshot_template(
                    path=path,
                    company="Example Biotech",
                )

    def test_validate_valuation_snapshot_file_reports_invalid_contract(self) -> None:
        report = validate_valuation_snapshot_file(_write_json({"currency": "HKD"}))

        self.assertFalse(report.has_snapshot)
        self.assertTrue(report.errors)

    def test_valuation_snapshot_template_requires_company(self) -> None:
        with self.assertRaises(ValueError):
            valuation_snapshot_template(company=" ")


def _write_json(payload: dict[str, object]) -> Path:
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / "valuation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _TEMP_DIRS.append(directory)
    return path


_TEMP_DIRS: list[tempfile.TemporaryDirectory[str]] = []


if __name__ == "__main__":
    unittest.main()
