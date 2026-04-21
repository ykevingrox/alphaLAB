from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from biotech_alpha.cli import main


class CliTest(unittest.TestCase):
    def test_pipeline_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "assets.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "pipeline-template",
                        "--company",
                        "Example Biotech",
                        "--ticker",
                        "9999.HK",
                        "--output",
                        str(path),
                    ]
                )

            self.assertEqual(template_exit, 0)
            self.assertEqual(json.loads(template_stdout.getvalue())["path"], str(path))
            self.assertTrue(path.exists())

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["pipeline-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertEqual(report["asset_count"], 1)
            self.assertEqual(report["errors"], [])

    def test_pipeline_validate_returns_nonzero_for_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "assets.json"
            path.write_text(json.dumps({"assets": [{"aliases": ["NO-NAME"]}]}))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["pipeline-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 1)
            self.assertTrue(report["errors"])

    def test_financial_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "financials.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "financial-template",
                        "--company",
                        "Example Biotech",
                        "--ticker",
                        "9999.HK",
                        "--output",
                        str(path),
                    ]
                )

            self.assertEqual(template_exit, 0)
            self.assertEqual(json.loads(template_stdout.getvalue())["path"], str(path))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["financial-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertTrue(report["has_snapshot"])

    def test_financial_validate_returns_nonzero_for_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "financials.json"
            path.write_text(json.dumps({"currency": "HKD"}))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["financial-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 1)
            self.assertTrue(report["errors"])

    def test_competitor_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "competitors.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "competitor-template",
                        "--company",
                        "Example Biotech",
                        "--ticker",
                        "9999.HK",
                        "--output",
                        str(path),
                    ]
                )

            self.assertEqual(template_exit, 0)
            self.assertEqual(json.loads(template_stdout.getvalue())["path"], str(path))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["competitor-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertEqual(report["competitor_count"], 1)

    def test_competitor_validate_returns_nonzero_for_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "competitors.json"
            path.write_text(json.dumps({"competitors": [{"company": "No Asset"}]}))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["competitor-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 1)
            self.assertTrue(report["errors"])

    def test_valuation_template_and_validate_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "input" / "valuation.json"

            template_stdout = io.StringIO()
            with redirect_stdout(template_stdout):
                template_exit = main(
                    [
                        "valuation-template",
                        "--company",
                        "Example Biotech",
                        "--ticker",
                        "9999.HK",
                        "--output",
                        str(path),
                    ]
                )

            self.assertEqual(template_exit, 0)
            self.assertEqual(json.loads(template_stdout.getvalue())["path"], str(path))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["valuation-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 0)
            self.assertTrue(report["has_snapshot"])

    def test_valuation_validate_returns_nonzero_for_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "valuation.json"
            path.write_text(json.dumps({"currency": "HKD"}))

            validate_stdout = io.StringIO()
            with redirect_stdout(validate_stdout):
                validate_exit = main(["valuation-validate", str(path)])

            report = json.loads(validate_stdout.getvalue())
            self.assertEqual(validate_exit, 1)
            self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
