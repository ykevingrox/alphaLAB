"""Offline tests for macro_signals_providers.

The provider's network hop goes to Yahoo's public chart endpoint, which
we must not hit during unit tests. Instead we test:

* the parser functions (``_parse_hsi_trend`` / ``_parse_spot_rate``)
  against small hand-crafted chart payloads;
* the outer ``hk_macro_signals_yahoo`` function with an injected
  ``requests.Session`` stub so we can assert on URL/params, fetched_at
  stamping, and graceful degradation when one sub-feed fails.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from typing import Any

from biotech_alpha.macro_signals_providers import (
    YAHOO_CHART_URL,
    _parse_hsi_trend,
    _parse_spot_rate,
    hk_macro_signals_yahoo,
)


def _hsi_chart_payload(closes: list[float], timestamps: list[int]) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "^HSI",
                        "currency": "HKD",
                        "regularMarketPrice": closes[-1],
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [{"close": closes}],
                    },
                }
            ],
            "error": None,
        }
    }


def _hkd_chart_payload(close: float) -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "HKD=X",
                        "regularMarketPrice": close,
                    },
                    "timestamp": [1713744000],
                    "indicators": {
                        "quote": [{"close": [close]}],
                    },
                }
            ],
            "error": None,
        }
    }


class _StubResponse:
    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _StubSession:
    """Minimal stand-in for requests.Session.

    Only the bits used by the provider are modelled (headers dict-like
    with setdefault, ``get``, and ``close``).
    """

    def __init__(self, responses: dict[str, _StubResponse]) -> None:
        self._responses = responses
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict]] = []

    def get(
        self, url: str, *, params: dict | None = None, timeout: float
    ) -> _StubResponse:
        self.calls.append((url, params or {}))
        for suffix, response in self._responses.items():
            if url.endswith(suffix):
                return response
        raise AssertionError(f"unexpected URL: {url}")

    def close(self) -> None:
        pass


class ParseHsiTrendTest(unittest.TestCase):
    def test_computes_trend_pct_and_period(self) -> None:
        # 30 daily closes, roughly +10% from first to last.
        closes = [18000.0 + i * 10.0 for i in range(30)]
        start = int(datetime(2025, 3, 1, tzinfo=timezone.utc).timestamp())
        timestamps = [start + i * 86400 for i in range(30)]
        parsed = _parse_hsi_trend(_hsi_chart_payload(closes, timestamps))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["symbol"], "^HSI")
        self.assertEqual(parsed["currency"], "HKD")
        self.assertAlmostEqual(parsed["level"], 18290.0, places=2)
        self.assertAlmostEqual(
            parsed["trend_30d_pct"],
            (18290.0 - 18000.0) / 18000.0 * 100.0,
            places=3,
        )
        self.assertEqual(parsed["period_start"], "2025-03-01")
        self.assertEqual(parsed["period_end"], "2025-03-30")
        self.assertTrue(parsed["source"].startswith(YAHOO_CHART_URL))

    def test_returns_none_when_no_data(self) -> None:
        self.assertIsNone(_parse_hsi_trend({"chart": {"result": []}}))
        self.assertIsNone(_parse_hsi_trend({}))

    def test_tolerates_missing_closes(self) -> None:
        parsed = _parse_hsi_trend(
            {
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "symbol": "^HSI",
                                "regularMarketPrice": 17999.5,
                            },
                            "timestamp": [],
                            "indicators": {"quote": [{"close": []}]},
                        }
                    ]
                }
            }
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertAlmostEqual(parsed["level"], 17999.5, places=3)
        self.assertIsNone(parsed["trend_30d_pct"])
        self.assertIsNone(parsed["period_start"])


class ParseSpotRateTest(unittest.TestCase):
    def test_reads_spot_from_meta(self) -> None:
        parsed = _parse_spot_rate(_hkd_chart_payload(7.83))
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["symbol"], "HKD=X")
        self.assertAlmostEqual(parsed["spot"], 7.83, places=3)
        self.assertIn("USD_to_HKD", parsed["quote_convention"])

    def test_returns_none_when_missing(self) -> None:
        empty = {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "HKD=X"},
                        "timestamp": [],
                        "indicators": {"quote": [{"close": []}]},
                    }
                ]
            }
        }
        self.assertIsNone(_parse_spot_rate(empty))


class HkMacroSignalsYahooTest(unittest.TestCase):
    def test_returns_none_for_non_hk_market(self) -> None:
        calls: list[str] = []

        class _Fail:
            def get(self, *a: Any, **k: Any) -> Any:
                calls.append("get")
                raise AssertionError("should not be called")

            def close(self) -> None:
                pass

            headers: dict[str, str] = {}

        self.assertIsNone(hk_macro_signals_yahoo("US", session=_Fail()))
        self.assertEqual(calls, [])

    def test_happy_path_returns_both_signals(self) -> None:
        closes = [18000.0 + i * 10.0 for i in range(30)]
        start = int(datetime(2025, 3, 1, tzinfo=timezone.utc).timestamp())
        timestamps = [start + i * 86400 for i in range(30)]
        stub = _StubSession(
            {
                "^HSI": _StubResponse(
                    _hsi_chart_payload(closes, timestamps)
                ),
                "HKD=X": _StubResponse(_hkd_chart_payload(7.83)),
            }
        )
        frozen_now = datetime(2025, 4, 1, 12, tzinfo=timezone.utc)

        signals = hk_macro_signals_yahoo(
            "HK", session=stub, now=frozen_now
        )
        self.assertIsNotNone(signals)
        assert signals is not None
        self.assertEqual(signals["fetched_at"], frozen_now.isoformat())
        self.assertEqual(signals["provider"], "yahoo-hk")
        self.assertIsNotNone(signals["hsi"])
        self.assertIsNotNone(signals["hkd_usd"])
        self.assertEqual(signals["notes"], [])
        # Two requests were issued, one per symbol.
        self.assertEqual(len(stub.calls), 2)
        # User-Agent was injected on the session.
        self.assertIn("User-Agent", stub.headers)

    def test_degrades_gracefully_when_one_feed_fails(self) -> None:
        stub = _StubSession(
            {
                "^HSI": _StubResponse(ValueError("bad json")),
                "HKD=X": _StubResponse(_hkd_chart_payload(7.84)),
            }
        )
        signals = hk_macro_signals_yahoo("HK", session=stub)
        self.assertIsNotNone(signals)
        assert signals is not None
        self.assertIsNone(signals["hsi"])
        self.assertIsNotNone(signals["hkd_usd"])
        self.assertTrue(
            any("hsi" in note for note in signals["notes"]),
            signals["notes"],
        )

    def test_returns_none_when_every_feed_fails(self) -> None:
        stub = _StubSession(
            {
                "^HSI": _StubResponse(ValueError("bad json")),
                "HKD=X": _StubResponse(ValueError("bad json")),
            }
        )
        self.assertIsNone(hk_macro_signals_yahoo("HK", session=stub))


class MacroContextLiveSignalsIntegrationTest(unittest.TestCase):
    """Ensure _build_macro_context threads live_signals in and prunes gaps."""

    def test_live_signals_block_and_pruned_unknowns(self) -> None:
        from biotech_alpha.company_report import _build_macro_context

        class _Ctx:
            company = "Test Co"
            ticker = "09606.HK"
            market = "HK"
            as_of_date = "2025-03-31"

        class _Research:
            context = _Ctx()
            financial_snapshot = None

        fact = _build_macro_context(
            research_result=_Research(),  # type: ignore[arg-type]
            auto_input_artifacts=None,
            live_signals={
                "fetched_at": "2025-04-01T12:00:00+00:00",
                "provider": "yahoo-hk",
                "hsi": {"symbol": "^HSI", "level": 18290.0,
                        "trend_30d_pct": 1.61},
                "hkd_usd": {"symbol": "HKD=X", "spot": 7.83},
                "notes": [],
            },
        )
        self.assertIsNotNone(fact)
        assert fact is not None
        self.assertEqual(fact["live_signals"]["provider"], "yahoo-hk")
        joined = "\n".join(fact["known_unknowns"])
        self.assertNotIn("HSI", joined)
        self.assertNotIn("USD/HKD", joined)
        # Non-covered unknowns remain.
        self.assertIn("news", joined)

    def test_no_live_signals_keeps_full_unknowns(self) -> None:
        from biotech_alpha.company_report import _build_macro_context

        class _Ctx:
            company = "Test Co"
            ticker = "09606.HK"
            market = "HK"
            as_of_date = "2025-03-31"

        class _Research:
            context = _Ctx()
            financial_snapshot = None

        fact = _build_macro_context(
            research_result=_Research(),  # type: ignore[arg-type]
            auto_input_artifacts=None,
            live_signals=None,
        )
        self.assertIsNotNone(fact)
        assert fact is not None
        self.assertIsNone(fact["live_signals"])
        joined = "\n".join(fact["known_unknowns"])
        self.assertIn("HSI", joined)
        self.assertIn("USD/HKD", joined)


if __name__ == "__main__":
    unittest.main()
