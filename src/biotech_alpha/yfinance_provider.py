"""Optional yfinance adapter for historical market features.

This module deliberately keeps ``yfinance`` behind a graceful import. The core
package must keep working when the optional dependency is absent, rate-limited,
or returns an unexpected dataframe shape.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from importlib import import_module
from typing import Any

from biotech_alpha.company_report import CompanyIdentity
from biotech_alpha.market_data_providers import yahoo_hk_symbol
from biotech_alpha.technical_features import OhlcvBar, technical_feature_payload


YFINANCE_PROVIDER_LABEL = "yfinance"
DEFAULT_HISTORY_PERIOD = "1y"
DEFAULT_HISTORY_INTERVAL = "1d"


def yfinance_symbol_for_identity(identity: CompanyIdentity) -> str | None:
    """Return the Yahoo/yfinance symbol for a company identity."""

    if not identity.ticker:
        return None
    ticker = identity.ticker.strip().upper()
    if identity.market == "HK" or ticker.endswith(".HK"):
        return yahoo_hk_symbol(ticker)
    return ticker or None


def yfinance_history_rows(
    symbol: str,
    *,
    period: str = DEFAULT_HISTORY_PERIOD,
    interval: str = DEFAULT_HISTORY_INTERVAL,
    yf_module: Any | None = None,
) -> tuple[OhlcvBar, ...] | None:
    """Fetch yfinance history rows as provider-neutral OHLCV bars."""

    yf = yf_module if yf_module is not None else _import_yfinance()
    if yf is None:
        return None
    try:
        frame = yf.Ticker(symbol).history(
            period=period,
            interval=interval,
            auto_adjust=False,
        )
    except Exception:
        return None
    rows = _ohlcv_rows_from_history(frame)
    return rows or None


def yfinance_technical_feature_payload(
    symbol: str,
    *,
    period: str = DEFAULT_HISTORY_PERIOD,
    interval: str = DEFAULT_HISTORY_INTERVAL,
    benchmark_symbol: str | None = None,
    retrieved_at: str | None = None,
    yf_module: Any | None = None,
) -> dict[str, Any] | None:
    """Fetch history via yfinance and build a technical feature payload."""

    yf = yf_module if yf_module is not None else _import_yfinance()
    if yf is None:
        return None

    rows = yfinance_history_rows(
        symbol,
        period=period,
        interval=interval,
        yf_module=yf,
    )
    if not rows:
        return None

    warnings: list[str] = []
    benchmark_rows = None
    if benchmark_symbol:
        benchmark_rows = yfinance_history_rows(
            benchmark_symbol,
            period=period,
            interval=interval,
            yf_module=yf,
        )
        if not benchmark_rows:
            warnings.append(
                f"benchmark {benchmark_symbol}: yfinance history unavailable"
            )

    try:
        return technical_feature_payload(
            rows,
            symbol=symbol,
            provider=YFINANCE_PROVIDER_LABEL,
            source=f"yfinance:{symbol}",
            retrieved_at=retrieved_at
            or datetime.now(tz=timezone.utc).isoformat(),
            benchmark_rows=benchmark_rows,
            benchmark_symbol=benchmark_symbol,
            initial_warnings=warnings,
        )
    except ValueError:
        return None


def yfinance_technical_feature_payload_for_identity(
    identity: CompanyIdentity,
    *,
    period: str = DEFAULT_HISTORY_PERIOD,
    interval: str = DEFAULT_HISTORY_INTERVAL,
    benchmark_symbol: str | None = None,
    retrieved_at: str | None = None,
    yf_module: Any | None = None,
) -> dict[str, Any] | None:
    """Resolve an identity to a yfinance symbol and build technical features."""

    symbol = yfinance_symbol_for_identity(identity)
    if symbol is None:
        return None
    return yfinance_technical_feature_payload(
        symbol,
        period=period,
        interval=interval,
        benchmark_symbol=benchmark_symbol,
        retrieved_at=retrieved_at,
        yf_module=yf_module,
    )


def _import_yfinance() -> Any | None:
    try:
        return import_module("yfinance")
    except Exception:
        return None


def _ohlcv_rows_from_history(frame: Any) -> tuple[OhlcvBar, ...]:
    if frame is None or bool(getattr(frame, "empty", False)):
        return ()
    iterrows = getattr(frame, "iterrows", None)
    if not callable(iterrows):
        return ()

    rows: list[OhlcvBar] = []
    for index, row in iterrows():
        close = _row_number(row, "Close", "close")
        if close is None or close <= 0:
            continue
        rows.append(
            OhlcvBar(
                date=_index_date(index),
                open=_row_number(row, "Open", "open"),
                high=_row_number(row, "High", "high"),
                low=_row_number(row, "Low", "low"),
                close=close,
                volume=_row_number(row, "Volume", "volume"),
            )
        )
    return tuple(rows)


def _row_number(row: Any, *keys: str) -> float | None:
    getter = getattr(row, "get", None)
    for key in keys:
        value = getter(key) if callable(getter) else None
        parsed = _as_float(value)
        if parsed is not None:
            return parsed
    return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _index_date(value: Any) -> str | None:
    if value is None:
        return None
    date_fn = getattr(value, "date", None)
    if callable(date_fn):
        value = date_fn()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())[:10]
    text = str(value).strip()
    return text[:10] if text else None
