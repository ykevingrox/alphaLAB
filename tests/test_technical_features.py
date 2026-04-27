import tempfile
import unittest
from pathlib import Path

from biotech_alpha.technical_features import (
    OhlcvBar,
    load_ohlcv_csv,
    technical_feature_payload,
    technical_feature_payload_from_csv,
)


def _bars(
    count: int,
    *,
    start: float = 100.0,
    step: float = 1.0,
    volume_start: float = 1000.0,
) -> list[OhlcvBar]:
    return [
        OhlcvBar(
            date=f"2025-01-{idx + 1:03d}",
            open=start + idx * step - 0.2,
            high=start + idx * step + 0.5,
            low=start + idx * step - 0.5,
            close=start + idx * step,
            volume=volume_start + idx,
        )
        for idx in range(count)
    ]


class TechnicalFeaturePayloadTest(unittest.TestCase):
    def test_payload_emits_stage_b_feature_contract(self) -> None:
        payload = technical_feature_payload(
            _bars(260, step=1.0),
            symbol="09606.HK",
            provider="unit-test",
            source="mock://09606",
            retrieved_at="2026-04-27T00:00:00+00:00",
            benchmark_rows=_bars(260, step=0.1),
            benchmark_symbol="^HSI",
        )

        self.assertEqual(payload["symbol"], "09606.HK")
        self.assertEqual(payload["provider"], "unit-test")
        self.assertEqual(payload["window"]["row_count"], 260)
        self.assertGreater(payload["returns"]["1m_pct"], 0)
        self.assertGreater(payload["returns"]["12m_pct"], 0)
        self.assertEqual(payload["drawdown_from_52w_high_pct"], 0.0)
        self.assertEqual(payload["moving_average_state"]["state"], "uptrend")
        self.assertEqual(payload["technical_state"], "constructive")
        self.assertEqual(
            payload["relative_strength"]["state"], "outperforming"
        )
        self.assertEqual(payload["guidance_type"], "research_only")
        self.assertEqual(payload["warnings"], ())

    def test_payload_degrades_with_short_but_valid_history(self) -> None:
        payload = technical_feature_payload(_bars(30), symbol="SHORT.HK")

        self.assertIsNone(payload["returns"]["3m_pct"])
        self.assertEqual(payload["volume_trend"]["state"], "insufficient_data")
        self.assertIn(
            "insufficient history for 3m return", payload["warnings"]
        )
        self.assertIn(
            "52w drawdown uses available history below 252 rows",
            payload["warnings"],
        )
        self.assertEqual(payload["confidence"], 0.4)

    def test_payload_requires_minimum_valid_close_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be >= 20"):
            technical_feature_payload(_bars(19))

    def test_csv_loader_and_payload_skip_invalid_close_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ohlcv.csv"
            lines = ["date,open,high,low,close,volume"]
            lines.append("2025-01-01,1,1,1,not-a-number,100")
            for idx in range(25):
                lines.append(
                    f"2025-01-{idx + 2:02d},1,1,1,{10 + idx},1000"
                )
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            rows = load_ohlcv_csv(path)
            payload = technical_feature_payload_from_csv(
                path,
                symbol="CSV.HK",
                retrieved_at="2026-04-27T00:00:00+00:00",
            )

            self.assertEqual(len(rows), 25)
            self.assertEqual(payload["symbol"], "CSV.HK")
            self.assertEqual(payload["source"], str(path))
            self.assertEqual(payload["window"]["row_count"], 25)


if __name__ == "__main__":
    unittest.main()
