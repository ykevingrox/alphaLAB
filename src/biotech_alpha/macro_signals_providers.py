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

import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
STOOQ_QUOTE_URL = "https://stooq.com/q/l/"
HKMA_HIBOR_URL = (
    "https://api.hkma.gov.hk/public/market-data-and-statistics/"
    "daily-monetary-statistics/interbank-ir"
)

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
        hsbio_payload = _fetch_first_chart_payload(
            http,
            symbols=("^HSHKBIO", "^HSBI"),
            interval="1d",
            range_="1mo",
            timeout=timeout,
        )
        hkd_payload = _fetch_chart_payload(
            http, symbol="HKD=X", interval="1d", range_="5d", timeout=timeout
        )
        hibor = _fetch_hkma_hibor_snapshot(http, timeout=timeout)
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

    hsbio = (
        _parse_hsbio_trend(hsbio_payload)
        if hsbio_payload is not None
        else None
    )
    if hsbio is None:
        notes.append("hsbio: unavailable (chart fetch failed or empty)")
    if hibor is None:
        notes.append("hibor: unavailable (hkma feed failed or empty)")

    if hsi is None and hkd_usd is None and hsbio is None and hibor is None:
        return None

    as_of = (now or datetime.now(tz=timezone.utc)).isoformat()
    return {
        "fetched_at": as_of,
        "provider": "yahoo-hk",
        "hsi": hsi,
        "hsbio": hsbio,
        "hkd_usd": hkd_usd,
        "hibor": hibor,
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


def _fetch_first_chart_payload(
    session: requests.Session,
    *,
    symbols: tuple[str, ...],
    interval: str,
    range_: str,
    timeout: float,
) -> dict[str, Any] | None:
    for symbol in symbols:
        payload = _fetch_chart_payload(
            session,
            symbol=symbol,
            interval=interval,
            range_=range_,
            timeout=timeout,
        )
        if payload is not None:
            return payload
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


def _parse_hsbio_trend(payload: dict[str, Any]) -> dict[str, Any] | None:
    parsed = _parse_hsi_trend(payload)
    if parsed is None:
        return None
    symbol = str(parsed.get("symbol") or "").upper()
    if "HSBI" not in symbol and "HKBIO" not in symbol:
        parsed["symbol"] = "^HSBIO"
    return parsed


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


DEFAULT_CACHE_DIR = Path("data/cache/macro_signals")
DEFAULT_CACHE_TTL = timedelta(hours=6)


@dataclass
class CachingMacroSignalsProvider:
    """Disk-backed TTL cache wrapping any :data:`MacroSignalsProvider`.

    Macro signals are shared across every company sitting in the same
    market (all HK biotech names see the same HSI level and USD/HKD
    spot), so a single successful fetch should serve every run in the
    same research session. This wrapper turns that property into:

    * **Cache hit** (fresh): the cached dict is returned with a note
      ``cache: hit (fetched_at=<iso>)`` added to ``notes``. The upstream
      provider is not called; no network hop is made.
    * **Cache miss or expired**: the upstream provider is called; on
      success the result is written to disk and returned with a note
      ``cache: miss (stored)``.
    * **Upstream failure with expired cache present** ("stale-if-
      error"): the expired cache is returned with
      ``cache: stale (served on upstream failure)``. This converts a
      transient Yahoo 429 into a slightly-stale regime read instead of
      losing the live feed entirely.
    * **Upstream failure with no cache**: ``None`` is returned, matching
      the pre-cache behaviour.

    Cache keys are keyed on ``(market, provider_label)`` so a later
    ``hk-tencent`` provider would not collide with ``yahoo-hk``.
    """

    inner: MacroSignalsProvider
    provider_label: str
    cache_dir: Path = DEFAULT_CACHE_DIR
    ttl: timedelta = DEFAULT_CACHE_TTL
    now_fn: Callable[[], datetime] = lambda: datetime.now(tz=timezone.utc)

    def __call__(self, market: str) -> dict[str, Any] | None:
        if not market:
            return None
        cache_path = self._cache_path(market)
        now = self.now_fn()
        cached = _read_cache_entry(cache_path)

        if cached is not None:
            cached_at = _parse_iso(cached.get("cached_at"))
            if cached_at is not None and now - cached_at <= self.ttl:
                return _attach_note(
                    cached.get("payload"),
                    f"cache: hit (cached_at={cached_at.isoformat()})",
                )

        try:
            fresh = self.inner(market)
        except Exception:  # noqa: BLE001 - defensive: never propagate
            fresh = None

        if fresh is not None:
            try:
                _write_cache_entry(cache_path, now=now, payload=fresh)
            except OSError:
                # Disk write failure must not corrupt the caller's result.
                pass
            return _attach_note(fresh, "cache: miss (stored)")

        if cached is not None:
            cached_at = _parse_iso(cached.get("cached_at"))
            stamp = cached_at.isoformat() if cached_at else "unknown"
            return _attach_note(
                cached.get("payload"),
                f"cache: stale (served on upstream failure, "
                f"cached_at={stamp})",
            )

        return None

    def _cache_path(self, market: str) -> Path:
        safe_market = "".join(
            ch if ch.isalnum() or ch in "-_" else "_" for ch in market
        )
        safe_provider = "".join(
            ch if ch.isalnum() or ch in "-_" else "_"
            for ch in self.provider_label
        )
        return self.cache_dir / f"{safe_market}_{safe_provider}.json"


@dataclass
class FallbackMacroSignalsProvider:
    """Try multiple providers in order until one returns usable payload.

    Each provider is a ``(label, callable)`` pair. The first non-``None``
    payload wins. Failures are treated as soft and summarized in ``notes``.
    """

    providers: list[tuple[str, MacroSignalsProvider]]

    def __call__(self, market: str) -> dict[str, Any] | None:
        failures: list[str] = []
        for label, provider in self.providers:
            try:
                payload = provider(market)
            except Exception:  # noqa: BLE001 - keep one-command resilient
                payload = None
            if payload is None:
                failures.append(label)
                continue
            if failures:
                failure_chain = " -> ".join(failures + [label])
                return _attach_note(
                    payload,
                    (
                        "fallback: selected "
                        f"{label} after failures in {failure_chain}"
                    ),
                )
            return payload
        return None


def hk_macro_signals_stooq(
    market: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Stooq-backed fallback provider for HK macro signals.

    Stooq acts as a public, no-key fallback when Yahoo is unavailable.
    Returns the same shape keys (`hsi`, `hkd_usd`, `notes`) so downstream
    prompt contracts remain unchanged.
    """

    if market != "HK":
        return None

    owned = session is None
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", _DEFAULT_USER_AGENT)
    notes: list[str] = []
    try:
        # Stooq symbols are lowercase and usually no caret in query.
        hsi_latest = _fetch_stooq_latest_row(
            http, symbol="hsi", timeout=timeout
        )
        hsbio_latest = _fetch_stooq_latest_row(
            http, symbol="hsbi", timeout=timeout
        )
        # USD/HKD spot proxy from Stooq FX symbol.
        hkd_latest = _fetch_stooq_latest_row(
            http, symbol="usdhkd", timeout=timeout
        )
        hibor = _fetch_hkma_hibor_snapshot(http, timeout=timeout)
    finally:
        if owned:
            http.close()

    hsi = _stooq_hsi_payload(hsi_latest)
    if hsi is None:
        notes.append("hsi: unavailable (stooq fetch failed or empty)")
    hkd_usd = _stooq_hkd_payload(hkd_latest)
    if hkd_usd is None:
        notes.append("hkd_usd: unavailable (stooq fetch failed or empty)")
    hsbio = _stooq_hsbio_payload(hsbio_latest)
    if hsbio is None:
        notes.append("hsbio: unavailable (stooq fetch failed or empty)")
    if hibor is None:
        notes.append("hibor: unavailable (hkma feed failed or empty)")

    if hsi is None and hkd_usd is None and hsbio is None and hibor is None:
        return None

    as_of = (now or datetime.now(tz=timezone.utc)).isoformat()
    return {
        "fetched_at": as_of,
        "provider": "stooq-hk",
        "hsi": hsi,
        "hsbio": hsbio,
        "hkd_usd": hkd_usd,
        "hibor": hibor,
        "notes": notes,
    }


def _read_cache_entry(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("payload"), dict):
        return None
    return data


def _write_cache_entry(
    path: Path, *, now: datetime, payload: dict[str, Any]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"cached_at": now.isoformat(), "payload": payload}
    # Atomic write: tempfile in the same directory, then rename, so a
    # crash mid-flush cannot leave a partial JSON blob for the next run.
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
        suffix=".tmp",
    ) as handle:
        json.dump(entry, handle, ensure_ascii=False, indent=2)
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _attach_note(
    payload: dict[str, Any] | None, note: str
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload
    cloned = dict(payload)
    notes = list(cloned.get("notes") or [])
    notes.append(note)
    cloned["notes"] = notes
    return cloned


def _fetch_stooq_latest_row(
    session: requests.Session,
    *,
    symbol: str,
    timeout: float,
) -> dict[str, str] | None:
    try:
        response = session.get(
            STOOQ_QUOTE_URL,
            params={
                "s": symbol,
                "i": "d",
                "f": "sd2t2ohlcv",
                "e": "csv",
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    text = response.text.strip()
    if not text:
        return None
    lines = text.splitlines()
    if len(lines) < 2:
        return None
    headers = [h.strip().lower() for h in lines[0].split(",")]
    values = [v.strip() for v in lines[1].split(",")]
    if len(values) != len(headers):
        return None
    row = dict(zip(headers, values))
    if row.get("close") in {None, "", "N/D"}:
        return None
    return row


def _stooq_hsi_payload(row: dict[str, str] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    close = _as_float(row.get("close"))
    if close is None:
        return None
    date_value = row.get("date")
    return {
        "symbol": "^HSI",
        "currency": "HKD",
        "level": close,
        "trend_30d_pct": None,
        "period_start": None,
        "period_end": date_value,
        "source": f"{STOOQ_QUOTE_URL}?s=hsi&i=d&e=csv",
    }


def _stooq_hkd_payload(row: dict[str, str] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    close = _as_float(row.get("close"))
    if close is None:
        return None
    return {
        "symbol": "USDHKD",
        "spot": close,
        "quote_convention": "USD_to_HKD_stooq_usdhkd",
        "source": f"{STOOQ_QUOTE_URL}?s=usdhkd&i=d&e=csv",
    }


def _stooq_hsbio_payload(row: dict[str, str] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    close = _as_float(row.get("close"))
    if close is None:
        return None
    date_value = row.get("date")
    return {
        "symbol": "^HSBIO",
        "currency": "HKD",
        "level": close,
        "trend_30d_pct": None,
        "period_start": None,
        "period_end": date_value,
        "source": f"{STOOQ_QUOTE_URL}?s=hsbi&i=d&e=csv",
    }


def _fetch_hkma_hibor_snapshot(
    session: requests.Session, *, timeout: float
) -> dict[str, Any] | None:
    try:
        response = session.get(
            HKMA_HIBOR_URL,
            params={"format": "json"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    try:
        payload = response.json()
    except ValueError:
        return None
    return _parse_hkma_hibor_payload(payload)


def _parse_hkma_hibor_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    records = result.get("records")
    if not isinstance(records, list) or not records:
        return None
    record = records[0]
    if not isinstance(record, dict):
        return None
    overnight = _as_float(
        _pick_first(
            record,
            ("hibor_overnight", "ir_overnight", "overnight"),
        )
    )
    one_month = _as_float(
        _pick_first(
            record,
            ("hibor_1m", "hibor_1_month", "ir_1_month", "1_month"),
        )
    )
    three_month = _as_float(
        _pick_first(
            record,
            ("hibor_3m", "hibor_3_month", "ir_3_month", "3_month"),
        )
    )
    if overnight is None and one_month is None and three_month is None:
        return None
    as_of_date = _pick_first(record, ("end_of_day", "date", "as_of_date"))
    return {
        "overnight_pct": overnight,
        "one_month_pct": one_month,
        "three_month_pct": three_month,
        "as_of_date": str(as_of_date) if as_of_date is not None else None,
        "source": f"{HKMA_HIBOR_URL}?format=json",
    }


def _pick_first(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in record and record.get(key) not in (None, "", "N/A"):
            return record.get(key)
    return None
