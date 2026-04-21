from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from biotech_alpha.alerts import (
    build_catalyst_alerts,
    catalyst_alerts_as_dicts,
    catalyst_alerts_to_csv_text,
    latest_catalyst_run_pairs,
    load_catalyst_runs,
)


class CatalystAlertsTest(unittest.TestCase):
    def test_build_catalyst_alerts_from_latest_run_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "single_company"
            self._write_run(
                root=root,
                run_id="20260420T010000Z",
                rows=[
                    {
                        "title": "Phase 2 primary completion",
                        "category": "clinical",
                        "expected_date": "2026-12-01",
                        "expected_window": "",
                        "related_asset": "Drug A",
                    },
                    {
                        "title": "Old milestone",
                        "category": "clinical",
                        "expected_date": "",
                        "expected_window": "2026 H2",
                        "related_asset": "Drug B",
                    },
                    {
                        "title": "Window milestone",
                        "category": "clinical",
                        "expected_date": "",
                        "expected_window": "2026 H1",
                        "related_asset": "Drug C",
                    },
                ],
            )
            self._write_run(
                root=root,
                run_id="20260421T010000Z",
                rows=[
                    {
                        "title": "Phase 2 primary completion",
                        "category": "clinical",
                        "expected_date": "2027-01-15",
                        "expected_window": "",
                        "related_asset": "Drug A",
                    },
                    {
                        "title": "New milestone",
                        "category": "clinical",
                        "expected_date": "",
                        "expected_window": "2027 H1",
                        "related_asset": "Drug D",
                    },
                    {
                        "title": "Window milestone",
                        "category": "clinical",
                        "expected_date": "",
                        "expected_window": "2026 H2",
                        "related_asset": "Drug C",
                    },
                ],
            )

            runs = load_catalyst_runs(root)
            pairs = latest_catalyst_run_pairs(runs)
            alerts = build_catalyst_alerts(root)
            rows = catalyst_alerts_as_dicts(alerts)

            self.assertEqual(len(runs), 2)
            self.assertEqual(len(pairs), 1)
            self.assertEqual(
                {row["change_type"] for row in rows},
                {"added", "date_changed", "removed", "window_changed"},
            )
            date_alert = next(
                row for row in rows if row["change_type"] == "date_changed"
            )
            self.assertEqual(date_alert["previous_expected_date"], "2026-12-01")
            self.assertEqual(date_alert["current_expected_date"], "2027-01-15")
            self.assertEqual(date_alert["company"], "Alpha Bio")
            self.assertEqual(date_alert["market"], "HK")

    def test_catalyst_alerts_csv_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "single_company"
            self._write_run(
                root=root,
                run_id="20260420T010000Z",
                rows=[],
            )
            self._write_run(
                root=root,
                run_id="20260421T010000Z",
                rows=[
                    {
                        "title": "New milestone",
                        "category": "clinical",
                        "expected_date": "2027-01-15",
                        "expected_window": "",
                        "related_asset": "Drug A",
                    }
                ],
            )

            text = catalyst_alerts_to_csv_text(build_catalyst_alerts(root))

            self.assertIn("company,ticker,market,previous_run_id", text)
            self.assertIn("added", text)
            self.assertIn("New milestone", text)

    def _write_run(
        self,
        *,
        root: Path,
        run_id: str,
        rows: list[dict[str, str]],
    ) -> None:
        run_dir = root / "alpha"
        run_dir.mkdir(parents=True, exist_ok=True)
        catalyst_path = run_dir / f"{run_id}_catalyst_calendar.csv"
        manifest_path = run_dir / f"{run_id}_manifest.json"

        with catalyst_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "title",
                    "category",
                    "expected_date",
                    "expected_window",
                    "related_asset",
                    "confidence",
                    "evidence_count",
                ],
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({**row, "confidence": "0.5", "evidence_count": "1"})

        manifest_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "company": "Alpha Bio",
                    "ticker": "1111.HK",
                    "market": "HK",
                    "retrieved_at": run_id,
                    "artifacts": {
                        "catalyst_calendar_csv": str(catalyst_path),
                    },
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
