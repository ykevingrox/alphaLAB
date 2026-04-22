"""Macro-signal providers for the MacroContextLLMAgent.

These providers produce a small, source-tagged dict that the
``MacroContextLLMAgent`` can feed on instead of having to return
``macro_regime = "insufficient_data"`` by default. Each provider is
intentionally defensive: any transport, decode, or schema failure causes
the sub-signal to degrade to ``None`` and to add a human-readable note on
the returned ``notes`` list, rather than raising and breaking the
one-command report.

Today only a Hong Kong provider is shipped. It pulls:

* Hang Seng Index (``^HSI``) current level and 30-day return from
  Yahoo's public ``v8/finance/chart`` endpoint.
* USD/HKD spot rate (``HKD=X``) from the same endpoint.

HIBOR tenor rates are not publicly queryable without a paid feed and are
left for the caller's ``known_unknowns`` list. When a caller adds a real
HIBOR provider, wire it into the same return shape.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import requests


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

# Yahoo's public chart endpoint aggressively 429s low-volume /
# bot-flavoured User-Agents. A browser-class string reduces the
# rate-limit rate noticeably; failures still degrade gracefully to a
# ``None`` sub-signal plus a note, never an exception.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0 Safari/537.36"
)


MacroSignalsProvider = Callable[[str], dict[str, Any] | None]
"""Callable shape: ``provider(market)`` returns a macro-signals dict or None.

The input is the market label used elsewhere in the project (``"HK"``,
``"US"``, ``"CN"``). Provider implementations should return ``None`` when
the market is out of scope for that provider, not raise.
"""


def hk_macro_signals_yahoo(
    market: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Yahoo-chart-backed macro-signals provider for HK biotech.

    Returns a dict with ``fetched_at``, per-signal sub-dicts (``hsi``,
    ``hkd_usd``), and a ``notes`` list describing any degraded fields.
    Returns ``None`` when the market is not HK, or when every requested
    signal fails so the caller cannot attach anything useful.
    """

    if market != "HK":
        return None

    owned = session is None
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", _DEFAULT_USER_AGENT)
    notes: list[str] = []
    try:
        hsi_payload = _fetch_chart_payload(
            http, symbol="^HSI", interval="1d", range_="1mo", timeout=timeout
        )
        hkd_payload = _fetch_chart_payload(
            http, symbol="HKD=X", interval="1d", range_="5d", timeout=timeout
        )
    finally:
        if owned:
            http.close()

    hsi = _parse_hsi_trend(hsi_payload) if hsi_payload is not None else None
    if hsi is None:
        notes.append("hsi: unavailable (chart fetch failed or empty)")

    hkd_usd = (
        _parse_spot_rate(hkd_payload) if hkd_payload is not None else None
    )
    if hkd_usd is None:
        notes.append("hkd_usd: unavailable (chart fetch failed or empty)")

    if hsi is None and hkd_usd is None:
        return None

    as_of = (now or datetime.now(tz=timezone.utc)).isoformat()
    return {
        "fetched_at": as_of,
        "provider": "yahoo-hk",
        "hsi": hsi,
        "hkd_usd": hkd_usd,
        "notes": notes,
    }


def _fetch_chart_payload(
    session: requests.Session,
    *,
    symbol: str,
    interval: str,
    range_: str,
    timeout: float,
) -> dict[str, Any] | None:
    url = f"{YAHOO_CHART_URL}/{symbol}"
    try:
        response = session.get(
            url,
            params={"interval": interval, "range": range_},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _parse_hsi_trend(payload: dict[str, Any]) -> dict[str, Any] | None:
    result = _first_chart_result(payload)
    if result is None:
        return None
    meta = result.get("meta") or {}
    symbol = meta.get("symbol") or "^HSI"
    currency = meta.get("currency") or "HKD"

    level = _as_float(meta.get("regularMarketPrice"))
    closes = _close_series(result)
    timestamps = result.get("timestamp") or []
    if level is None and closes:
        level = _as_float(closes[-1])

    trend_pct: float | None = None
    period_start: str | None = None
    period_end: str | None = None
    if closes and timestamps and len(closes) == len(timestamps):
        first = _as_float(closes[0])
        last = _as_float(closes[-1])
        if first and last and first != 0:
            trend_pct = round((last - first) / first * 100.0, 3)
        period_start = _iso_date_from_epoch(timestamps[0])
        period_end = _iso_date_from_epoch(timestamps[-1])

    if level is None and trend_pct is None:
        return None

    return {
        "symbol": symbol,
        "currency": currency,
        "level": level,
        "trend_30d_pct": trend_pct,
        "period_start": period_start,
        "period_end": period_end,
        "source": f"{YAHOO_CHART_URL}/{symbol}",
    }


def _parse_spot_rate(payload: dict[str, Any]) -> dict[str, Any] | None:
    result = _first_chart_result(payload)
    if result is None:
        return None
    meta = result.get("meta") or {}
    symbol = meta.get("symbol") or "HKD=X"
    spot = _as_float(meta.get("regularMarketPrice"))
    closes = _close_series(result)
    if spot is None and closes:
        spot = _as_float(closes[-1])
    if spot is None:
        return None
    return {
        "symbol": symbol,
        "spot": spot,
        "quote_convention": "USD_to_HKD_when_symbol_is_HKD=X",
        "source": f"{YAHOO_CHART_URL}/{symbol}",
    }


def _first_chart_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    chart = payload.get("chart") if isinstance(payload, dict) else None
    if not isinstance(chart, dict):
        return None
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        return None
    first = results[0]
    return first if isinstance(first, dict) else None


def _close_series(result: dict[str, Any]) -> list[Any]:
    indicators = result.get("indicators") or {}
    quotes = indicators.get("quote")
    if not isinstance(quotes, list) or not quotes:
        return []
    first = quotes[0]
    closes = first.get("close") if isinstance(first, dict) else None
    if not isinstance(closes, list):
        return []
    return [c for c in closes if c is not None]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_date_from_epoch(value: Any) -> str | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return (
        datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
    )
