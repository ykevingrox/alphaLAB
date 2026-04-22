from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from biotech_alpha.conference import (
    load_conference_catalysts,
    validate_conference_catalyst_file,
    write_conference_catalyst_template,
)


class ConferenceCatalystTest(unittest.TestCase):
    def test_template_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "conference.json"
            write_conference_catalyst_template(
                path=path,
                company="Example Bio",
                ticker="9999.HK",
            )
            report = validate_conference_catalyst_file(path)
            self.assertEqual(report.catalyst_count, 1)
            self.assertEqual(report.errors, ())

    def test_load_conference_catalysts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "conference.json"
            path.write_text(
                json.dumps(
                    {
                        "catalysts": [
                            {
                                "title": "ESMO oral presentation expected",
                                "category": "conference",
                                "expected_date": "2027-09-15",
                                "related_asset": "ABC-101",
                                "confidence": 0.6,
                                "evidence": [
                                    {
                                        "claim": "Accepted abstract listed.",
                                        "source": "https://example.com/abstract",
                                        "source_date": "2027-08-01",
                                        "confidence": 0.7,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            catalysts = load_conference_catalysts(path)
            self.assertEqual(len(catalysts), 1)
            self.assertEqual(catalysts[0].category, "conference")
            self.assertEqual(catalysts[0].title, "ESMO oral presentation expected")

    def test_validate_warns_for_non_conference_category(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "conference.json"
            path.write_text(
                json.dumps(
                    {
                        "catalysts": [
                            {
                                "title": "Clinical readout",
                                "category": "clinical",
                                "expected_window": "ASCO 2027",
                                "confidence": 0.4,
                                "evidence": [
                                    {
                                        "claim": "Accepted abstract listed.",
                                        "source": "https://example.com/abstract",
                                        "confidence": 0.6,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            report = validate_conference_catalyst_file(path)

            self.assertEqual(report.errors, ())
            self.assertTrue(
                any("category is 'clinical'" in item for item in report.warnings)
            )


if __name__ == "__main__":
    unittest.main()
