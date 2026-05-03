from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from biotech_alpha.strategic_economics import (
    load_strategic_economics,
    validate_strategic_economics_file,
    write_strategic_economics_template,
)


class StrategicEconomicsInputTest(unittest.TestCase):
    def test_template_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "strategic.json"
            write_strategic_economics_template(
                path=path,
                company="Example Bio",
                ticker="9999.HK",
            )

            payload = load_strategic_economics(path)
            report = validate_strategic_economics_file(path)

            self.assertEqual(payload["company"], "Example Bio")
            self.assertEqual(report.retained_economics_count, 1)
            self.assertEqual(report.bd_event_count, 1)
            self.assertEqual(report.platform_evidence_count, 1)
            self.assertEqual(report.errors, ())

    def test_validate_warns_on_missing_economics_detail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "strategic.json"
            path.write_text(
                json.dumps(
                    {
                        "company": "DualityBio",
                        "ticker": "09606.HK",
                        "as_of_date": "2026-03-31",
                        "retained_economics": [
                            {
                                "asset": "DB-1303",
                                "region": "ex-China",
                                "partner": "BioNTech",
                                "rights_status": "partnered",
                                "economics_share": "unknown",
                                "economics_type": "royalty",
                                "evidence": [
                                    {
                                        "claim": "BioNTech partnership disclosed.",
                                        "source": "annual-report.pdf",
                                        "source_date": "2026-03-31",
                                        "confidence": 0.8,
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = validate_strategic_economics_file(path)

            self.assertEqual(report.errors, ())
            self.assertTrue(
                any("economics_share is unknown" in item for item in report.warnings)
            )


if __name__ == "__main__":
    unittest.main()
