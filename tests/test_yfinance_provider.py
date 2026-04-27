import unittest
from datetime import date, timedelta

from biotech_alpha.company_report import CompanyIdentity
from biotech_alpha.yfinance_provider import (
    yfinance_history_rows,
    yfinance_symbol_for_identity,
    yfinance_technical_feature_payload,
    yfinance_technical_feature_payload_for_identity,
)


class YFinanceProviderTest(unittest.TestCase):
    def test_symbol_for_hk_identity_uses_yahoo_hk_format(self) -> None:
        symbol = yfinance_symbol_for_identity(
            CompanyIdentity(company="DualityBio", ticker="09606.HK")
        )

        self.assertEqual(symbol, "9606.HK")

    def test_symbol_for_non_hk_identity_uppercases_ticker(self) -> None:
        symbol = yfinance_symbol_for_identity(
            CompanyIdentity(company="Apple", ticker="aapl", market="US")
        )

        self.assertEqual(symbol, "AAPL")

    def test_history_rows_parse_dataframe_like_object(self) -> None:
        yf = _FakeYFinance(
            {
                "9606.HK": _Frame(
                    [
                        (
                            date(2026, 4, 1),
                            {
                                "Open": 10,
                                "High": 11,
                                "Low": 9,
                                "Close": 10.5,
                                "Volume": 1000,
                            },
                        ),
                        (
                            date(2026, 4, 2),
                            {
                                "Open": 10.5,
                                "High": 12,
                                "Low": 10,
                                "Close": 11,
                                "Volume": 1100,
                            },
                        ),
                    ]
                )
            }
        )

        rows = yfinance_history_rows("9606.HK", yf_module=yf)

        self.assertIsNotNone(rows)
        assert rows is not None
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].date, "2026-04-01")
        self.assertEqual(rows[0].close, 10.5)
        self.assertEqual(rows[1].volume, 1100.0)

    def test_technical_payload_uses_main_and_benchmark_history(self) -> None:
        yf = _FakeYFinance(
            {
                "9606.HK": _Frame(_history_rows(260, close_step=1.0)),
                "^HSI": _Frame(_history_rows(260, close_step=0.1)),
            }
        )

        payload = yfinance_technical_feature_payload(
            "9606.HK",
            benchmark_symbol="^HSI",
            retrieved_at="2026-04-27T00:00:00+00:00",
            yf_module=yf,
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["provider"], "yfinance")
        self.assertEqual(payload["source"], "yfinance:9606.HK")
        self.assertEqual(
            payload["relative_strength"]["state"], "outperforming"
        )
        self.assertEqual(payload["warnings"], ())
        self.assertEqual(
            yf.calls,
            [
                ("9606.HK", "1y", "1d", False),
                ("^HSI", "1y", "1d", False),
            ],
        )

    def test_technical_payload_degrades_when_benchmark_missing(self) -> None:
        yf = _FakeYFinance({"9606.HK": _Frame(_history_rows(260))})

        payload = yfinance_technical_feature_payload(
            "9606.HK",
            benchmark_symbol="^HSI",
            retrieved_at="2026-04-27T00:00:00+00:00",
            yf_module=yf,
        )

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIsNone(payload["relative_strength"])
        self.assertIn(
            "benchmark ^HSI: yfinance history unavailable",
            payload["warnings"],
        )

    def test_for_identity_returns_none_when_symbol_cannot_be_resolved(self) -> None:
        payload = yfinance_technical_feature_payload_for_identity(
            CompanyIdentity(company="Unknown", ticker=None),
            yf_module=_FakeYFinance({}),
        )

        self.assertIsNone(payload)

    def test_history_rows_return_none_on_fetch_exception(self) -> None:
        rows = yfinance_history_rows(
            "9606.HK",
            yf_module=_FakeYFinance({}, raise_on_history=True),
        )

        self.assertIsNone(rows)


def _history_rows(
    count: int,
    *,
    close_start: float = 100.0,
    close_step: float = 1.0,
) -> list[tuple[date, dict[str, float]]]:
    rows: list[tuple[date, dict[str, float]]] = []
    start_date = date(2025, 1, 1)
    for idx in range(count):
        close = close_start + idx * close_step
        rows.append(
            (
                start_date + timedelta(days=idx),
                {
                    "Open": close - 0.1,
                    "High": close + 0.5,
                    "Low": close - 0.5,
                    "Close": close,
                    "Volume": 1000 + idx,
                },
            )
        )
    return rows


class _FakeYFinance:
    def __init__(
        self,
        frames: dict[str, "_Frame"],
        *,
        raise_on_history: bool = False,
    ) -> None:
        self.frames = frames
        self.raise_on_history = raise_on_history
        self.calls: list[tuple[str, str, str, bool]] = []

    def Ticker(self, symbol: str) -> "_Ticker":
        return _Ticker(symbol=symbol, owner=self)


class _Ticker:
    def __init__(self, *, symbol: str, owner: _FakeYFinance) -> None:
        self.symbol = symbol
        self.owner = owner

    def history(
        self,
        *,
        period: str,
        interval: str,
        auto_adjust: bool,
    ) -> "_Frame":
        self.owner.calls.append(
            (self.symbol, period, interval, auto_adjust)
        )
        if self.owner.raise_on_history:
            raise RuntimeError("offline")
        return self.owner.frames.get(self.symbol, _Frame([]))


class _Frame:
    def __init__(self, rows: list[tuple[date, dict[str, float]]]) -> None:
        self._rows = rows
        self.empty = len(rows) == 0

    def iterrows(self):
        yield from self._rows


if __name__ == "__main__":
    unittest.main()
