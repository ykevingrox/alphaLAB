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
from typing import Any, Callable

import tempfile
from datetime import timedelta
from pathlib import Path

from biotech_alpha.macro_signals_providers import (
    CachingMacroSignalsProvider,
    FallbackMacroSignalsProvider,
    STOOQ_QUOTE_URL,
    YAHOO_CHART_URL,
    _parse_hsi_trend,
    _parse_spot_rate,
    hk_macro_signals_stooq,
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

    @property
    def text(self) -> str:
        if isinstance(self._payload, str):
            return self._payload
        return ""


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
        symbol = str((params or {}).get("s", "")).lower()
        for suffix, response in self._responses.items():
            if url.endswith(suffix):
                return response
            if suffix.lower() == symbol:
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


class HkMacroSignalsStooqTest(unittest.TestCase):
    def test_happy_path_returns_both_signals(self) -> None:
        hsi_csv = (
            "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "HSI,2026-04-22,17:35:00,25900,26200,25880,26163.24,0\n"
        )
        usdhkd_csv = (
            "Symbol,Date,Time,Open,High,Low,Close,Volume\n"
            "USDHKD,2026-04-22,17:35:00,7.83,7.84,7.82,7.8316,0\n"
        )
        stub = _StubSession(
            {
                "hsi": _StubResponse(hsi_csv),
                "usdhkd": _StubResponse(usdhkd_csv),
            }
        )
        out = hk_macro_signals_stooq("HK", session=stub)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["provider"], "stooq-hk")
        self.assertAlmostEqual(out["hsi"]["level"], 26163.24, places=2)
        self.assertAlmostEqual(out["hkd_usd"]["spot"], 7.8316, places=4)
        self.assertEqual(out["notes"], [])
        self.assertTrue(out["hsi"]["source"].startswith(STOOQ_QUOTE_URL))

    def test_returns_none_when_every_feed_fails(self) -> None:
        stub = _StubSession(
            {
                "hsi": _StubResponse(""),
                "usdhkd": _StubResponse(""),
            }
        )
        self.assertIsNone(hk_macro_signals_stooq("HK", session=stub))


class FallbackMacroSignalsProviderTest(unittest.TestCase):
    def test_uses_second_provider_after_first_fails(self) -> None:
        calls: list[str] = []

        def _none(market: str) -> dict[str, Any] | None:
            calls.append(f"none:{market}")
            return None

        def _ok(market: str) -> dict[str, Any] | None:
            calls.append(f"ok:{market}")
            return {
                "fetched_at": "2026-04-22T10:00:00+00:00",
                "provider": "stooq-hk",
                "hsi": {"symbol": "^HSI", "level": 26163.24},
                "hkd_usd": {"symbol": "USDHKD", "spot": 7.8316},
                "notes": [],
            }

        fallback = FallbackMacroSignalsProvider(
            providers=[("yahoo-hk", _none), ("stooq-hk", _ok)]
        )
        out = fallback("HK")
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(calls, ["none:HK", "ok:HK"])
        self.assertTrue(
            any("fallback: selected stooq-hk" in n for n in out["notes"])
        )

    def test_returns_none_when_all_providers_fail(self) -> None:
        fallback = FallbackMacroSignalsProvider(
            providers=[
                ("p1", lambda _m: None),
                ("p2", lambda _m: None),
            ]
        )
        self.assertIsNone(fallback("HK"))


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


class CachingMacroSignalsProviderTest(unittest.TestCase):
    """Exercise the disk cache wrapper with a controllable clock."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_dir = Path(self._tmp.name) / "macro_signals"
        self.calls: list[str] = []

        def _ok(market: str) -> dict[str, Any] | None:
            self.calls.append(market)
            return {
                "fetched_at": "2026-04-22T10:00:00+00:00",
                "provider": "yahoo-hk",
                "hsi": {"symbol": "^HSI", "level": 26163.24},
                "hkd_usd": {"symbol": "HKD=X", "spot": 7.83},
                "notes": [],
            }

        self.ok_provider = _ok

    def _make(
        self,
        *,
        inner: Callable[[str], Any],
        now_iso: str,
        ttl_hours: float = 6.0,
    ) -> CachingMacroSignalsProvider:
        clock = {"now": datetime.fromisoformat(now_iso)}

        def _now() -> datetime:
            return clock["now"]

        provider = CachingMacroSignalsProvider(
            inner=inner,
            provider_label="yahoo-hk",
            cache_dir=self.cache_dir,
            ttl=timedelta(hours=ttl_hours),
            now_fn=_now,
        )
        return provider, clock  # type: ignore[return-value]

    def test_miss_then_hit_within_ttl_only_calls_upstream_once(
        self,
    ) -> None:
        provider, clock = self._make(
            inner=self.ok_provider,
            now_iso="2026-04-22T10:00:00+00:00",
        )
        first = provider("HK")
        second = provider("HK")
        self.assertEqual(self.calls, ["HK"])
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertTrue(
            any("cache: miss" in note for note in first["notes"])
        )
        self.assertTrue(
            any("cache: hit" in note for note in second["notes"])
        )
        # Same-market request from a DIFFERENT company does not refetch.
        self.assertEqual(self.calls, ["HK"])

    def test_expired_entry_triggers_refetch(self) -> None:
        provider, clock = self._make(
            inner=self.ok_provider,
            now_iso="2026-04-22T10:00:00+00:00",
            ttl_hours=1.0,
        )
        provider("HK")
        clock["now"] = datetime.fromisoformat(
            "2026-04-22T12:00:00+00:00"
        )
        provider("HK")
        self.assertEqual(self.calls, ["HK", "HK"])

    def test_stale_if_error_serves_expired_cache(self) -> None:
        toggled: dict[str, bool] = {"fail": False}

        def _flaky(market: str) -> dict[str, Any] | None:
            self.calls.append(market)
            if toggled["fail"]:
                return None
            return {
                "fetched_at": "2026-04-22T10:00:00+00:00",
                "provider": "yahoo-hk",
                "hsi": {"symbol": "^HSI", "level": 26163.24},
                "hkd_usd": None,
                "notes": [],
            }

        provider, clock = self._make(
            inner=_flaky,
            now_iso="2026-04-22T10:00:00+00:00",
            ttl_hours=1.0,
        )
        # Prime the cache.
        provider("HK")
        # Expire the cache; upstream now fails.
        clock["now"] = datetime.fromisoformat(
            "2026-04-22T12:00:00+00:00"
        )
        toggled["fail"] = True
        served = provider("HK")
        self.assertIsNotNone(served)
        assert served is not None
        self.assertEqual(served["hsi"]["level"], 26163.24)
        self.assertTrue(
            any("cache: stale" in note for note in served["notes"])
        )

    def test_no_cache_and_upstream_failure_returns_none(self) -> None:
        def _fail(market: str) -> dict[str, Any] | None:
            self.calls.append(market)
            return None

        provider, _clock = self._make(
            inner=_fail,
            now_iso="2026-04-22T10:00:00+00:00",
        )
        self.assertIsNone(provider("HK"))

    def test_upstream_exception_is_swallowed(self) -> None:
        def _boom(market: str) -> dict[str, Any] | None:
            raise RuntimeError("network on fire")

        provider, _clock = self._make(
            inner=_boom,
            now_iso="2026-04-22T10:00:00+00:00",
        )
        self.assertIsNone(provider("HK"))

    def test_cache_keyed_by_market_and_provider(self) -> None:
        provider, _clock = self._make(
            inner=self.ok_provider,
            now_iso="2026-04-22T10:00:00+00:00",
        )
        provider("HK")
        provider("US")
        # Distinct markets should not share cache entries.
        self.assertEqual(self.calls, ["HK", "US"])
        self.assertTrue(
            (self.cache_dir / "HK_yahoo-hk.json").exists()
        )
        self.assertTrue(
            (self.cache_dir / "US_yahoo-hk.json").exists()
        )


class CliResolverCacheFlagsTest(unittest.TestCase):
    """Ensure the CLI resolver respects --no-macro-signals-cache and TTL."""

    def test_defaults_return_caching_wrapper(self) -> None:
        from biotech_alpha.cli import _resolve_macro_signals_provider
        from biotech_alpha.macro_signals_providers import (
            hk_macro_signals_stooq,
        )

        provider = _resolve_macro_signals_provider("yahoo-hk")
        self.assertIsInstance(provider, CachingMacroSignalsProvider)
        assert isinstance(provider, CachingMacroSignalsProvider)
        self.assertIsInstance(provider.inner, FallbackMacroSignalsProvider)
        fallback = provider.inner
        assert isinstance(fallback, FallbackMacroSignalsProvider)
        self.assertEqual(
            [label for label, _fn in fallback.providers],
            ["yahoo-hk", "stooq-hk"],
        )
        self.assertIs(fallback.providers[0][1], hk_macro_signals_yahoo)
        self.assertIs(fallback.providers[1][1], hk_macro_signals_stooq)
        self.assertEqual(provider.provider_label, "yahoo-hk+stooq-hk")
        self.assertEqual(provider.ttl, timedelta(hours=6.0))

    def test_disable_cache_returns_bare_callable(self) -> None:
        from biotech_alpha.cli import _resolve_macro_signals_provider

        provider = _resolve_macro_signals_provider(
            "yahoo-hk", disable_cache=True
        )
        self.assertIsInstance(provider, FallbackMacroSignalsProvider)

    def test_zero_ttl_returns_bare_callable(self) -> None:
        from biotech_alpha.cli import _resolve_macro_signals_provider

        provider = _resolve_macro_signals_provider(
            "yahoo-hk", cache_ttl_hours=0
        )
        self.assertIsInstance(provider, FallbackMacroSignalsProvider)

    def test_custom_ttl_is_preserved(self) -> None:
        from biotech_alpha.cli import _resolve_macro_signals_provider

        provider = _resolve_macro_signals_provider(
            "yahoo-hk", cache_ttl_hours=1.5
        )
        assert isinstance(provider, CachingMacroSignalsProvider)
        self.assertEqual(provider.ttl, timedelta(hours=1.5))

    def test_none_choice_still_returns_none(self) -> None:
        from biotech_alpha.cli import _resolve_macro_signals_provider

        self.assertIsNone(_resolve_macro_signals_provider("none"))


if __name__ == "__main__":
    unittest.main()
