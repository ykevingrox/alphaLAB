"""Deterministic market technical features for Stage B agents.

The functions in this module are provider-neutral. They consume normalized
OHLCV rows from any adapter and emit a source-backed payload that future market
expectations and regime/timing agents can read without fetching data directly.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TRADING_DAYS_1M = 21
TRADING_DAYS_3M = 63
TRADING_DAYS_6M = 126
TRADING_DAYS_12M = 252


@dataclass(frozen=True)
class OhlcvBar:
    """Provider-neutral daily OHLCV row."""

    date: str | None
    close: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None


def technical_feature_payload(
    rows: Iterable[OhlcvBar | dict[str, Any]],
    *,
    symbol: str | None = None,
    provider: str | None = None,
    source: str | None = None,
    retrieved_at: str | None = None,
    benchmark_rows: Iterable[OhlcvBar | dict[str, Any]] | None = None,
    benchmark_symbol: str | None = None,
    initial_warnings: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a deterministic technical feature payload from OHLCV rows."""

    bars = _normalize_rows(rows)
    if len(bars) < 20:
        raise ValueError("OHLCV rows with valid close price must be >= 20")

    warnings: list[str] = [
        text.strip()
        for text in initial_warnings
        if isinstance(text, str) and text.strip()
    ]
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars if bar.volume is not None]
    latest = bars[-1]

    returns = {
        "1m_pct": _period_return(closes, TRADING_DAYS_1M, warnings, "1m"),
        "3m_pct": _period_return(closes, TRADING_DAYS_3M, warnings, "3m"),
        "6m_pct": _period_return(closes, TRADING_DAYS_6M, warnings, "6m"),
        "12m_pct": _period_return(closes, TRADING_DAYS_12M, warnings, "12m"),
    }
    ma_state = _moving_average_state(closes)
    vol_state = _volatility_state(closes)
    volume_trend = _volume_trend(volumes, warnings)
    drawdown = _drawdown_from_52w_high(closes, warnings)
    relative_strength = _relative_strength_payload(
        bars=bars,
        benchmark_rows=benchmark_rows,
        benchmark_symbol=benchmark_symbol,
        warnings=warnings,
    )

    support = min(closes[-20:])
    resistance = max(closes[-20:])
    rsi14 = _rsi(closes, 14)

    payload = {
        "symbol": symbol,
        "provider": provider,
        "source": source,
        "retrieved_at": retrieved_at
        or datetime.now(tz=timezone.utc).isoformat(),
        "window": {
            "start_date": bars[0].date,
            "end_date": latest.date,
            "row_count": len(bars),
        },
        "latest_close": round(latest.close, 4),
        "returns": returns,
        "drawdown_from_52w_high_pct": drawdown,
        "volume_trend": volume_trend,
        "moving_average_state": ma_state,
        "volatility_state": vol_state,
        "relative_strength": relative_strength,
        "support": round(support, 4),
        "resistance": round(resistance, 4),
        "rsi14": _rounded_or_none(rsi14),
        "technical_state": _technical_state(ma_state, returns, drawdown),
        "confidence": _confidence(len(bars), warnings),
        "needs_human_review": True,
        "guidance_type": "research_only",
        "warnings": tuple(dict.fromkeys(warnings)),
        "notes": (
            "Deterministic technical feature baseline from OHLCV.",
            "Use as research support only; not a trading instruction.",
        ),
    }
    payload.update(_legacy_timing_fields(payload))
    return payload


def technical_feature_payload_from_csv(
    path: str | Path,
    *,
    symbol: str | None = None,
    provider: str | None = "csv",
    source: str | None = None,
    retrieved_at: str | None = None,
    benchmark_path: str | Path | None = None,
    benchmark_symbol: str | None = None,
) -> dict[str, Any]:
    """Load OHLCV CSV rows and build a technical feature payload."""

    benchmark_rows = (
        load_ohlcv_csv(benchmark_path) if benchmark_path is not None else None
    )
    return technical_feature_payload(
        load_ohlcv_csv(path),
        symbol=symbol,
        provider=provider,
        source=source or str(path),
        retrieved_at=retrieved_at,
        benchmark_rows=benchmark_rows,
        benchmark_symbol=benchmark_symbol,
    )


def load_ohlcv_csv(path: str | Path) -> list[OhlcvBar]:
    """Load provider-neutral OHLCV rows from a CSV file."""

    rows: list[OhlcvBar] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            close = _num(raw.get("close"))
            if close is None or close <= 0:
                continue
            rows.append(
                OhlcvBar(
                    date=_text(raw.get("date")),
                    open=_num(raw.get("open")),
                    high=_num(raw.get("high")),
                    low=_num(raw.get("low")),
                    close=close,
                    volume=_num(raw.get("volume")),
                )
            )
    return rows


def _normalize_rows(rows: Iterable[OhlcvBar | dict[str, Any]]) -> list[OhlcvBar]:
    normalized: list[OhlcvBar] = []
    for row in rows:
        if isinstance(row, OhlcvBar):
            if row.close > 0 and math.isfinite(row.close):
                normalized.append(row)
            continue
        close = _num(row.get("close"))
        if close is None or close <= 0:
            continue
        normalized.append(
            OhlcvBar(
                date=_text(row.get("date")),
                open=_num(row.get("open")),
                high=_num(row.get("high")),
                low=_num(row.get("low")),
                close=close,
                volume=_num(row.get("volume")),
            )
        )
    return normalized


def _period_return(
    closes: list[float],
    days: int,
    warnings: list[str],
    label: str,
) -> float | None:
    if len(closes) <= days:
        warnings.append(f"insufficient history for {label} return")
        return None
    start = closes[-days - 1]
    end = closes[-1]
    if start <= 0:
        warnings.append(f"invalid start price for {label} return")
        return None
    return round((end / start - 1.0) * 100.0, 4)


def _moving_average_state(closes: list[float]) -> dict[str, Any]:
    sma20 = _sma(closes, 20)
    sma60 = _sma(closes, 60)
    sma120 = _sma(closes, 120)
    latest = closes[-1]
    state = "insufficient_data"
    if sma20 is not None and sma60 is not None:
        if latest > sma20 > sma60:
            state = "uptrend"
        elif latest < sma20 < sma60:
            state = "downtrend"
        else:
            state = "sideways"
    return {
        "state": state,
        "latest_vs_sma20_pct": _spread_pct(latest, sma20),
        "sma20_vs_sma60_pct": _spread_pct(sma20, sma60),
        "sma60_vs_sma120_pct": _spread_pct(sma60, sma120),
        "sma20": _rounded_or_none(sma20),
        "sma60": _rounded_or_none(sma60),
        "sma120": _rounded_or_none(sma120),
    }


def _drawdown_from_52w_high(
    closes: list[float], warnings: list[str]
) -> float | None:
    window = closes[-TRADING_DAYS_12M:]
    if len(closes) < TRADING_DAYS_12M:
        warnings.append("52w drawdown uses available history below 252 rows")
    high = max(window)
    if high <= 0:
        return None
    return round((closes[-1] / high - 1.0) * 100.0, 4)


def _volume_trend(
    volumes: list[float],
    warnings: list[str],
) -> dict[str, Any]:
    if len(volumes) < 40:
        warnings.append("insufficient volume history for 20d trend")
        return {"state": "insufficient_data", "last20_vs_prior20_pct": None}
    recent = sum(volumes[-20:]) / 20
    prior = sum(volumes[-40:-20]) / 20
    pct = _spread_pct(recent, prior)
    state = "flat"
    if pct is not None and pct >= 20.0:
        state = "rising"
    elif pct is not None and pct <= -20.0:
        state = "falling"
    return {
        "state": state,
        "last20_avg_volume": round(recent, 4),
        "prior20_avg_volume": round(prior, 4),
        "last20_vs_prior20_pct": pct,
    }


def _volatility_state(closes: list[float]) -> dict[str, Any]:
    daily = _volatility(closes, 20)
    annualized = daily * math.sqrt(252) if daily is not None else None
    state = "insufficient_data"
    if annualized is not None:
        if annualized < 0.35:
            state = "low"
        elif annualized > 0.75:
            state = "high"
        else:
            state = "normal"
    return {
        "state": state,
        "daily_volatility20": _rounded_or_none(daily),
        "annualized_volatility20": _rounded_or_none(annualized),
    }


def _relative_strength_payload(
    *,
    bars: list[OhlcvBar],
    benchmark_rows: Iterable[OhlcvBar | dict[str, Any]] | None,
    benchmark_symbol: str | None,
    warnings: list[str],
) -> dict[str, Any] | None:
    if benchmark_rows is None:
        return None
    benchmark = _normalize_rows(benchmark_rows)
    if len(benchmark) < 20:
        warnings.append("insufficient benchmark history for relative strength")
        return {
            "benchmark_symbol": benchmark_symbol,
            "state": "insufficient_data",
        }
    stock_closes = [bar.close for bar in bars]
    benchmark_closes = [bar.close for bar in benchmark]
    spreads: dict[str, float | None] = {}
    for label, days in (
        ("1m_spread_pct", TRADING_DAYS_1M),
        ("3m_spread_pct", TRADING_DAYS_3M),
        ("6m_spread_pct", TRADING_DAYS_6M),
        ("12m_spread_pct", TRADING_DAYS_12M),
    ):
        stock_return = _return_or_none(stock_closes, days)
        benchmark_return = _return_or_none(benchmark_closes, days)
        spreads[label] = (
            round(stock_return - benchmark_return, 4)
            if stock_return is not None and benchmark_return is not None
            else None
        )
    state = "insufficient_data"
    pivot = spreads.get("3m_spread_pct")
    if pivot is None:
        pivot = spreads.get("1m_spread_pct")
    if pivot is not None:
        if pivot >= 5.0:
            state = "outperforming"
        elif pivot <= -5.0:
            state = "underperforming"
        else:
            state = "in_line"
    return {
        "benchmark_symbol": benchmark_symbol,
        "state": state,
        **spreads,
    }


def _technical_state(
    ma_state: dict[str, Any],
    returns: dict[str, float | None],
    drawdown: float | None,
) -> str:
    ma = ma_state.get("state")
    ret_3m = returns.get("3m_pct")
    if drawdown is not None and drawdown <= -45.0:
        return "deep_drawdown"
    if ma == "uptrend" and ret_3m is not None and ret_3m > 0:
        return "constructive"
    if ma == "downtrend" and ret_3m is not None and ret_3m < 0:
        return "weak"
    if ma == "insufficient_data":
        return "insufficient_data"
    return "mixed"


def _legacy_timing_fields(payload: dict[str, Any]) -> dict[str, Any]:
    ma = payload["moving_average_state"]
    vol = payload["volatility_state"]
    return {
        "trend_state": ma["state"],
        "sma20": ma["sma20"],
        "sma60": ma["sma60"],
        "volatility20": vol["daily_volatility20"],
    }


def _confidence(row_count: int, warnings: list[str]) -> float:
    if row_count >= TRADING_DAYS_12M and not warnings:
        return 0.75
    if row_count >= TRADING_DAYS_6M:
        return 0.6
    return 0.4


def _return_or_none(closes: list[float], days: int) -> float | None:
    if len(closes) <= days:
        return None
    start = closes[-days - 1]
    if start <= 0:
        return None
    return (closes[-1] / start - 1.0) * 100.0


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def _rsi(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    gains = 0.0
    losses = 0.0
    for idx in range(len(values) - period, len(values)):
        diff = values[idx] - values[idx - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - (100 / (1 + rs))


def _volatility(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    returns: list[float] = []
    start = len(values) - period
    for idx in range(start, len(values)):
        prev = values[idx - 1]
        if prev <= 0:
            continue
        returns.append((values[idx] / prev) - 1)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return variance**0.5


def _spread_pct(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return round((current / base - 1.0) * 100.0, 4)


def _rounded_or_none(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
