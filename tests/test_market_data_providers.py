from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import requests

from biotech_alpha.company_report import CompanyIdentity
from biotech_alpha.market_data import normalize_hk_market_data
from biotech_alpha.market_data_providers import (
    TENCENT_QUOTE_URL,
    YAHOO_QUOTE_URL,
    hk_public_quote_provider,
    tencent_hk_code,
    tencent_hk_quote_provider,
    yahoo_hk_quote_provider,
    yahoo_hk_symbol,
)
from biotech_alpha.valuation import (
    valuation_snapshot_from_dict,
    validate_valuation_snapshot_file,
)


class YahooSymbolTest(unittest.TestCase):
    def test_pads_five_digit_hk_tickers_to_four(self) -> None:
        self.assertEqual(yahoo_hk_symbol("09606.HK"), "9606.HK")

    def test_pads_short_hk_tickers_to_four(self) -> None:
        self.assertEqual(yahoo_hk_symbol("700.HK"), "0700.HK")

    def test_rejects_non_hk_tickers(self) -> None:
        self.assertIsNone(yahoo_hk_symbol("AAPL"))
        self.assertIsNone(yahoo_hk_symbol("600001.SS"))
        self.assertIsNone(yahoo_hk_symbol(""))


class YahooHkQuoteProviderTest(unittest.TestCase):
    def test_fixture_payload_parses_into_valuation_snapshot(self) -> None:
        epoch = int(datetime(2026, 4, 22, tzinfo=timezone.utc).timestamp())
        fake_response = _FakeResponse(
            {
                "quoteResponse": {
                    "result": [
                        {
                            "symbol": "9606.HK",
                            "regularMarketPrice": 35.2,
                            "sharesOutstanding": 710_000_000,
                            "marketCap": 25_000_000_000,
                            "currency": "hkd",
                            "regularMarketTime": epoch,
                        }
                    ]
                }
            }
        )
        session = MagicMock(spec=requests.Session)
        session.headers = {}
        session.get.return_value = fake_response

        payload = yahoo_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
        )

        self.assertIsNotNone(payload)
        session.get.assert_called_once_with(
            YAHOO_QUOTE_URL,
            params={"symbols": "9606.HK"},
            timeout=10.0,
        )
        self.assertEqual(payload["market_cap"], 25_000_000_000)
        self.assertEqual(payload["currency"], "HKD")
        self.assertEqual(payload["as_of_date"], "2026-04-22")
        self.assertEqual(payload["source_date"], "2026-04-22")
        self.assertTrue(payload["source"].startswith(YAHOO_QUOTE_URL))

        normalized = normalize_hk_market_data(payload)
        self.assertEqual(normalized.warnings, ())
        snapshot = valuation_snapshot_from_dict(
            {
                "as_of_date": normalized.as_of_date,
                "currency": normalized.currency,
                "market_cap": normalized.market_cap,
                "share_price": normalized.share_price,
                "shares_outstanding": normalized.shares_outstanding,
                "cash_and_equivalents": 0,
                "total_debt": 0,
                "revenue_ttm": None,
                "source": normalized.source,
                "source_date": normalized.source_date,
            }
        )
        self.assertEqual(snapshot.currency, "HKD")

    def test_returns_none_when_response_is_empty(self) -> None:
        fake_response = _FakeResponse({"quoteResponse": {"result": []}})
        session = MagicMock(spec=requests.Session)
        session.headers = {}
        session.get.return_value = fake_response

        payload = yahoo_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
        )

        self.assertIsNone(payload)

    def test_returns_none_when_required_fields_missing(self) -> None:
        fake_response = _FakeResponse(
            {
                "quoteResponse": {
                    "result": [{"symbol": "9606.HK", "currency": "HKD"}]
                }
            }
        )
        session = MagicMock(spec=requests.Session)
        session.headers = {}
        session.get.return_value = fake_response

        payload = yahoo_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
        )

        self.assertIsNone(payload)

    def test_returns_none_on_request_exception(self) -> None:
        session = MagicMock(spec=requests.Session)
        session.headers = {}
        session.get.side_effect = requests.ConnectionError("offline")

        payload = yahoo_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
        )

        self.assertIsNone(payload)

    def test_skips_non_hk_market_identities(self) -> None:
        session = MagicMock(spec=requests.Session)

        payload = yahoo_hk_quote_provider(
            CompanyIdentity(company="Acme", ticker="AAPL", market="US"),
            session=session,
        )

        self.assertIsNone(payload)
        session.get.assert_not_called()

    def test_writes_valuation_file_passing_validation(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        epoch = int(datetime(2026, 4, 22, tzinfo=timezone.utc).timestamp())
        fake_response = _FakeResponse(
            {
                "quoteResponse": {
                    "result": [
                        {
                            "symbol": "9606.HK",
                            "marketCap": 25_000_000_000,
                            "regularMarketPrice": 35.2,
                            "sharesOutstanding": 710_000_000,
                            "currency": "HKD",
                            "regularMarketTime": epoch,
                        }
                    ]
                }
            }
        )
        session = MagicMock(spec=requests.Session)
        session.headers = {}
        session.get.return_value = fake_response

        payload = yahoo_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
        )
        self.assertIsNotNone(payload)
        snapshot_payload = {
            "company": "DualityBio",
            "ticker": "09606.HK",
            "as_of_date": payload["as_of_date"],
            "currency": payload["currency"],
            "market_cap": payload["market_cap"],
            "share_price": payload["share_price"],
            "shares_outstanding": payload["shares_outstanding"],
            "cash_and_equivalents": 0,
            "total_debt": 0,
            "revenue_ttm": None,
            "source": payload["source"],
            "source_date": payload["source_date"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "valuation.json"
            path.write_text(json.dumps(snapshot_payload), encoding="utf-8")
            report = validate_valuation_snapshot_file(path)

        self.assertTrue(report.has_snapshot)
        self.assertFalse(report.errors)
        for warning in report.warnings:
            self.assertNotIn("placeholder", warning)


@unittest.skipUnless(
    os.environ.get("BIOTECH_ALPHA_ONLINE_TESTS") == "1",
    "online provider test requires BIOTECH_ALPHA_ONLINE_TESTS=1",
)
class YahooHkQuoteProviderOnlineTest(unittest.TestCase):
    def test_live_fetch_returns_usable_payload(self) -> None:
        payload = yahoo_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
        )
        if payload is None:
            self.skipTest("Yahoo quote endpoint returned no usable payload")
        self.assertIn("source", payload)
        self.assertTrue(payload["source"].startswith(YAHOO_QUOTE_URL))
        normalized = normalize_hk_market_data(payload)
        self.assertEqual(normalized.warnings, ())


@unittest.skipUnless(
    os.environ.get("BIOTECH_ALPHA_ONLINE_TESTS") == "1",
    "online provider test requires BIOTECH_ALPHA_ONLINE_TESTS=1",
)
class TencentHkQuoteProviderOnlineTest(unittest.TestCase):
    def test_live_fetch_returns_usable_payload(self) -> None:
        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
        )
        if payload is None:
            self.skipTest("Tencent quote feed returned no usable payload")
        self.assertTrue(
            payload["source"].startswith(TENCENT_QUOTE_URL),
            msg=f"unexpected source: {payload['source']!r}",
        )
        normalized = normalize_hk_market_data(payload)
        self.assertEqual(normalized.warnings, ())


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class TencentHkCodeTest(unittest.TestCase):
    def test_pads_four_digit_hk_tickers_to_five(self) -> None:
        self.assertEqual(tencent_hk_code("700.HK"), "00700")

    def test_preserves_five_digit_hk_tickers(self) -> None:
        self.assertEqual(tencent_hk_code("09606.HK"), "09606")
        self.assertEqual(tencent_hk_code("02142.hk"), "02142")

    def test_rejects_non_hk_tickers(self) -> None:
        self.assertIsNone(tencent_hk_code("AAPL"))
        self.assertIsNone(tencent_hk_code(""))
        self.assertIsNone(tencent_hk_code("123456.HK"))


_TENCENT_DUALITY_PAYLOAD = (
    'v_hk09606="100~映恩生物-B~09606~310.200~311.800~311.800~378524.0'
    "~0~0~310.200~0~0~0~0~0~0~0~0~0~310.200~0~0~0~0~0~0~0~0~0~378524.0"
    "~2026/04/22 14:58:37~-1.600~-0.51~318.200~306.000~310.200~378524.0"
    "~117655265.400~0~-9.74~~0~0~3.91~279.9183~279.9183~DUALITYBIO-B"
    "~0.00~563.500~165.500~0.62~-12.73~0~0~0~0~0~-9.74~10.42~0.42~100"
    "~4.02~-2.39~GP~-106.93~-66.66~-0.19~10.71~-10.71~90238014.00"
    '~90238014.00~-9.74~0.000~310.826~-13.88~HKD~1~30";\n'
)


class TencentHkQuoteProviderTest(unittest.TestCase):
    def _fake_session(self, payload: str) -> MagicMock:
        session = MagicMock(spec=requests.Session)
        session.headers = {}
        response = MagicMock()
        response.content = payload.encode("gbk")
        response.raise_for_status.return_value = None
        session.get.return_value = response
        return session

    def test_parses_public_fixture_into_valuation_payload(self) -> None:
        session = self._fake_session(_TENCENT_DUALITY_PAYLOAD)

        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
            now=datetime(2026, 4, 22, 16, 0),
        )

        self.assertIsNotNone(payload)
        session.get.assert_called_once_with(
            f"{TENCENT_QUOTE_URL}hk09606", timeout=10.0
        )
        self.assertEqual(payload["currency"], "HKD")
        self.assertEqual(payload["share_price"], 310.200)
        self.assertEqual(payload["shares_outstanding"], 90_238_014.0)
        self.assertAlmostEqual(
            payload["market_cap"], 279.9183 * 1e8, places=2
        )
        self.assertEqual(payload["as_of_date"], "2026-04-22")
        self.assertEqual(payload["source_date"], "2026-04-22")
        self.assertEqual(
            payload["source"], f"{TENCENT_QUOTE_URL}hk09606"
        )
        self.assertEqual(payload["warnings"], [])

        normalized = normalize_hk_market_data(payload)
        self.assertEqual(normalized.warnings, ())

    def test_writes_valuation_file_passing_validation(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        session = self._fake_session(_TENCENT_DUALITY_PAYLOAD)
        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
            now=datetime(2026, 4, 22, 16, 0),
        )
        self.assertIsNotNone(payload)
        snapshot_payload = {
            "company": "DualityBio",
            "ticker": "09606.HK",
            "as_of_date": payload["as_of_date"],
            "currency": payload["currency"],
            "market_cap": payload["market_cap"],
            "share_price": payload["share_price"],
            "shares_outstanding": payload["shares_outstanding"],
            "cash_and_equivalents": 0,
            "total_debt": 0,
            "revenue_ttm": None,
            "source": payload["source"],
            "source_date": payload["source_date"],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "valuation.json"
            path.write_text(
                json.dumps(snapshot_payload), encoding="utf-8"
            )
            report = validate_valuation_snapshot_file(path)

        self.assertTrue(report.has_snapshot)
        self.assertFalse(report.errors)
        for warning in report.warnings:
            self.assertNotIn("placeholder", warning)

    def test_returns_none_when_payload_is_empty(self) -> None:
        session = self._fake_session('v_hkunknown="";\n')
        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="Nowhere", ticker="09606.HK"),
            session=session,
        )
        self.assertIsNone(payload)

    def test_flags_halted_row_with_warning_and_no_market_cap(self) -> None:
        halted = _TENCENT_DUALITY_PAYLOAD.replace(
            "~279.9183~279.9183~", "~0~0~"
        ).replace("~90238014.00~90238014.00~", "~0~0~")
        session = self._fake_session(halted)

        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
            now=datetime(2026, 4, 22, 15, 30),
        )

        self.assertIsNotNone(payload)
        self.assertIsNone(payload["market_cap"])
        self.assertIsNone(payload["shares_outstanding"])
        self.assertEqual(payload["share_price"], 310.200)
        self.assertTrue(
            any("halted" in w for w in payload["warnings"]),
            msg=f"unexpected warnings: {payload['warnings']}",
        )

    def test_flags_stale_quote_with_freshness_warning(self) -> None:
        session = self._fake_session(_TENCENT_DUALITY_PAYLOAD)

        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
            now=datetime(2026, 4, 28, 9, 0),
            freshness_days=3.0,
        )

        self.assertIsNotNone(payload)
        self.assertTrue(
            any("older than" in w for w in payload["warnings"]),
            msg=f"expected stale warning, got {payload['warnings']}",
        )

    def test_does_not_flag_fresh_quote(self) -> None:
        session = self._fake_session(_TENCENT_DUALITY_PAYLOAD)

        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
            now=datetime(2026, 4, 22, 16, 0),
            freshness_days=3.0,
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["warnings"], [])

    def test_flags_currency_mismatch_for_hk_identity(self) -> None:
        # Swap the trailing currency field from HKD to USD.
        mismatched = _TENCENT_DUALITY_PAYLOAD.replace("~HKD~", "~USD~")
        session = self._fake_session(mismatched)

        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
            now=datetime(2026, 4, 22, 16, 0),
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["currency"], "USD")
        self.assertTrue(
            any("currency" in w.lower() for w in payload["warnings"]),
            msg=f"expected currency warning, got {payload['warnings']}",
        )

    def test_returns_none_on_request_exception(self) -> None:
        session = MagicMock(spec=requests.Session)
        session.headers = {}
        session.get.side_effect = requests.ConnectionError("offline")

        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
        )
        self.assertIsNone(payload)

    def test_skips_non_hk_market_identities(self) -> None:
        session = MagicMock(spec=requests.Session)
        payload = tencent_hk_quote_provider(
            CompanyIdentity(company="Acme", ticker="AAPL", market="US"),
            session=session,
        )
        self.assertIsNone(payload)
        session.get.assert_not_called()


class HkPublicQuoteProviderCompositeTest(unittest.TestCase):
    def test_returns_tencent_payload_when_available(self) -> None:
        session = MagicMock(spec=requests.Session)
        session.headers = {}
        response = MagicMock()
        response.content = _TENCENT_DUALITY_PAYLOAD.encode("gbk")
        response.raise_for_status.return_value = None
        session.get.return_value = response

        payload = hk_public_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
            now=datetime(2026, 4, 22, 16, 0),
        )

        self.assertIsNotNone(payload)
        self.assertIn("qt.gtimg.cn", payload["source"])
        # Yahoo fallback must not have been invoked.
        session.get.assert_called_once()

    def test_falls_back_to_yahoo_when_tencent_fails(self) -> None:
        session = MagicMock(spec=requests.Session)
        session.headers = {}

        yahoo_response = _FakeResponse(
            {
                "quoteResponse": {
                    "result": [
                        {
                            "symbol": "9606.HK",
                            "regularMarketPrice": 35.2,
                            "sharesOutstanding": 710_000_000,
                            "marketCap": 25_000_000_000,
                            "currency": "HKD",
                            "regularMarketTime": int(
                                datetime(
                                    2026, 4, 22, tzinfo=timezone.utc
                                ).timestamp()
                            ),
                        }
                    ]
                }
            }
        )

        def fake_get(url: str, *args: Any, **kwargs: Any):
            if url.startswith(TENCENT_QUOTE_URL):
                raise requests.ConnectionError("offline")
            if url == YAHOO_QUOTE_URL:
                return yahoo_response
            raise AssertionError(f"unexpected url {url}")

        session.get.side_effect = fake_get

        payload = hk_public_quote_provider(
            CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            session=session,
        )

        self.assertIsNotNone(payload)
        self.assertTrue(payload["source"].startswith(YAHOO_QUOTE_URL))


class ResolveMarketDataProviderCliTest(unittest.TestCase):
    def test_hk_public_returns_composite_provider(self) -> None:
        from biotech_alpha.cli import _resolve_market_data_provider

        provider = _resolve_market_data_provider("hk-public")
        self.assertIs(provider, hk_public_quote_provider)

    def test_none_returns_none(self) -> None:
        from biotech_alpha.cli import _resolve_market_data_provider

        self.assertIsNone(_resolve_market_data_provider("none"))


if __name__ == "__main__":
    unittest.main()
