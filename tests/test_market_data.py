from __future__ import annotations

import unittest

from biotech_alpha.market_data import (
    normalize_hk_market_data,
    valuation_snapshot_payload_from_market_data,
)
from biotech_alpha.valuation import valuation_snapshot_from_dict


class MarketDataTest(unittest.TestCase):
    def test_normalize_hk_market_data_to_valuation_payload(self) -> None:
        fixture_payload = {
            "as_of_date": "2026-04-22",
            "currency": "HKD",
            "market_cap": "25,000,000,000",
            "share_price": "35.2",
            "shares_outstanding": "710000000",
            "source": "https://example.com/hk/09606-quote",
            "source_date": "2026-04-22",
        }

        normalized = normalize_hk_market_data(fixture_payload)
        snapshot_payload = valuation_snapshot_payload_from_market_data(
            company="DualityBio",
            ticker="09606.HK",
            normalized=normalized,
            cash_and_equivalents=1_200_000_000,
            total_debt=300_000_000,
            revenue_ttm=1_500_000_000,
        )
        snapshot = valuation_snapshot_from_dict(snapshot_payload)

        self.assertEqual(normalized.warnings, ())
        self.assertEqual(snapshot.market_cap, 25_000_000_000)
        self.assertEqual(snapshot.source, "https://example.com/hk/09606-quote")
        self.assertEqual(snapshot.currency, "HKD")

    def test_normalize_hk_market_data_degrades_with_warnings(self) -> None:
        fixture_payload = {
            "currency": "HKD",
            "share_price": None,
            "shares_outstanding": "not-a-number",
        }

        normalized = normalize_hk_market_data(fixture_payload)
        snapshot_payload = valuation_snapshot_payload_from_market_data(
            company="DualityBio",
            ticker="09606.HK",
            normalized=normalized,
        )
        snapshot = valuation_snapshot_from_dict(snapshot_payload)

        self.assertIn("market data missing as_of_date", normalized.warnings)
        self.assertIn("market data missing source", normalized.warnings)
        self.assertIn(
            "market data missing market_cap and share_price/shares_outstanding pair",
            normalized.warnings,
        )
        self.assertEqual(snapshot.as_of_date, "YYYY-MM-DD")
        self.assertEqual(snapshot.source, "market-data-snapshot")
        self.assertIsNone(snapshot.market_cap)
        self.assertIsNone(snapshot.share_price)
        self.assertIsNone(snapshot.shares_outstanding)


if __name__ == "__main__":
    unittest.main()
