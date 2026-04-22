"""Concrete market-data providers for valuation auto-drafts.

These providers fetch a minimal source-backed quote for a company identity
and return a dict compatible with
:func:`biotech_alpha.market_data.normalize_hk_market_data`. Each provider is
intentionally defensive: any transport, parsing, or schema failure causes the
provider to return ``None`` so that the one-command flow in
``generate_auto_inputs`` can degrade to warnings rather than fail.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from biotech_alpha.company_report import CompanyIdentity


YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="

_DEFAULT_USER_AGENT = "Mozilla/5.0 biotech-alpha-lab/0.1"
_DEFAULT_FRESHNESS_DAYS = 3.0


def hk_public_quote_provider(
    identity: CompanyIdentity,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
    freshness_days: float = _DEFAULT_FRESHNESS_DAYS,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Fetch an HK quote from public sources with graceful fallback.

    Tries Tencent's ``qt.gtimg.cn`` feed first because it exposes shares
    outstanding and total market cap without authentication, then falls back
    to Yahoo Finance which currently requires a crumb for ``v7/finance/quote``
    but remains useful when that auth is available in the caller's session.
    Returns ``None`` when no source can supply a usable payload.
    """

    payload = tencent_hk_quote_provider(
        identity,
        session=session,
        timeout=timeout,
        freshness_days=freshness_days,
        now=now,
    )
    if payload is not None:
        return payload
    return yahoo_hk_quote_provider(
        identity, session=session, timeout=timeout
    )


def tencent_hk_quote_provider(
    identity: CompanyIdentity,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
    freshness_days: float = _DEFAULT_FRESHNESS_DAYS,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Fetch a minimal HK quote payload from Tencent's public ``qt.gtimg.cn``.

    Tencent's feed returns a semicolon-terminated JavaScript assignment with
    tilde-separated fields; the parser is defensive so any transport, decode,
    or schema failure causes the provider to return ``None``. Staleness,
    halted-market rows, and currency mismatches are surfaced on the returned
    payload's ``warnings`` list so callers can bubble them up through
    ``AutoInputArtifacts.warnings``.
    """

    if identity.market != "HK" or not identity.ticker:
        return None
    code = _tencent_hk_code(identity.ticker)
    if not code:
        return None

    owned = session is None
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", _DEFAULT_USER_AGENT)
    try:
        text = _fetch_tencent_quote_text(http, code, timeout=timeout)
    finally:
        if owned:
            http.close()
    if not text:
        return None
    return _parse_tencent_quote(
        text,
        code=code,
        identity=identity,
        freshness_days=freshness_days,
        now=now,
    )


def tencent_hk_code(ticker: str) -> str | None:
    """Return the zero-padded 5-digit HK code Tencent's feed expects."""

    return _tencent_hk_code(ticker)


def yahoo_hk_quote_provider(
    identity: CompanyIdentity,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Fetch a minimal HK quote payload from Yahoo Finance.

    Returns the normalized dict consumed by
    :func:`biotech_alpha.market_data.normalize_hk_market_data`, or ``None`` if
    the symbol is not HK, the network fetch fails, or the response lacks the
    fields needed to compute a valuation snapshot.
    """

    if identity.market != "HK" or not identity.ticker:
        return None
    symbol = yahoo_hk_symbol(identity.ticker)
    if not symbol:
        return None

    owned = session is None
    http = session or requests.Session()
    http.headers.setdefault("User-Agent", _DEFAULT_USER_AGENT)
    try:
        payload = _fetch_yahoo_quote_payload(http, symbol, timeout=timeout)
    finally:
        if owned:
            http.close()
    if payload is None:
        return None
    return payload


def yahoo_hk_symbol(ticker: str) -> str | None:
    """Return the Yahoo Finance HK symbol for a listed ticker."""

    match = re.match(r"^(\d+)\.HK$", ticker.strip().upper())
    if not match:
        return None
    code = match.group(1).lstrip("0") or "0"
    return f"{code.zfill(4)}.HK"


def _fetch_yahoo_quote_payload(
    session: requests.Session,
    symbol: str,
    *,
    timeout: float,
) -> dict[str, Any] | None:
    try:
        response = session.get(
            YAHOO_QUOTE_URL,
            params={"symbols": symbol},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    try:
        rows = response.json().get("quoteResponse", {}).get("result", [])
    except ValueError:
        return None
    if not rows:
        return None
    row = rows[0]

    market_cap = _as_number(row.get("marketCap"))
    share_price = _as_number(row.get("regularMarketPrice"))
    shares_outstanding = _as_number(row.get("sharesOutstanding"))
    currency = _as_currency(row.get("currency")) or "HKD"
    source_date = _iso_date_from_epoch(row.get("regularMarketTime"))

    if market_cap is None and (
        share_price is None or shares_outstanding is None
    ):
        return None

    return {
        "as_of_date": source_date,
        "currency": currency,
        "market_cap": market_cap,
        "share_price": share_price,
        "shares_outstanding": shares_outstanding,
        "source": f"{YAHOO_QUOTE_URL}?symbols={symbol}",
        "source_date": source_date,
    }


def _as_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _tencent_hk_code(ticker: str) -> str | None:
    match = re.match(r"^(\d+)\.HK$", ticker.strip().upper())
    if not match:
        return None
    digits = match.group(1).lstrip("0") or "0"
    if len(digits) > 5:
        return None
    return digits.zfill(5)


def _fetch_tencent_quote_text(
    session: requests.Session,
    code: str,
    *,
    timeout: float,
) -> str | None:
    try:
        response = session.get(
            f"{TENCENT_QUOTE_URL}hk{code}", timeout=timeout
        )
        response.raise_for_status()
    except requests.RequestException:
        return None
    raw = getattr(response, "content", None)
    if isinstance(raw, bytes):
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            try:
                return raw.decode("utf-8", errors="replace")
            except UnicodeDecodeError:
                return None
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    return None


_TENCENT_PAYLOAD_RE = re.compile(r'v_hk\d+="([^"]*)"')


def _parse_tencent_quote(
    text: str,
    *,
    code: str,
    identity: CompanyIdentity,
    freshness_days: float = _DEFAULT_FRESHNESS_DAYS,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    match = _TENCENT_PAYLOAD_RE.search(text)
    if not match:
        return None
    fields = match.group(1).split("~")
    # Need enough columns to reach shares outstanding + currency.
    if len(fields) < 76:
        return None

    share_price = _parse_float(fields[3])
    if share_price is None:
        share_price = _parse_float(fields[35])
    timestamp_text = fields[30].strip()
    market_cap_100m = _parse_float(fields[45])
    if market_cap_100m is None:
        market_cap_100m = _parse_float(fields[44])
    shares_outstanding = _parse_float(fields[70])
    if shares_outstanding is None:
        shares_outstanding = _parse_float(fields[69])
    currency = _as_currency(fields[75]) or "HKD"

    quote_datetime = _parse_tencent_datetime(timestamp_text)
    source_date = quote_datetime.strftime("%Y-%m-%d") if quote_datetime else None

    market_cap: float | None = None
    if market_cap_100m is not None and market_cap_100m > 0:
        # Tencent reports market cap in units of 1e8 (亿) base currency.
        market_cap = market_cap_100m * 1e8

    if share_price is not None and share_price <= 0:
        share_price = None
    if shares_outstanding is not None and shares_outstanding <= 0:
        shares_outstanding = None

    warnings: list[str] = []

    # Halted / suspended row detection: Tencent zeroes market cap and shares
    # outstanding when the stock is suspended or when the feed only has a
    # stale previous-close row.
    if market_cap is None and shares_outstanding is None:
        warnings.append(
            "halted or stale quote: no market cap or shares outstanding "
            f"reported on {source_date or 'unknown date'}"
        )

    # Staleness: compare the quote timestamp against the provided ``now``
    # (falls back to the local clock).
    if quote_datetime is not None:
        current = now or datetime.now()
        if current.tzinfo is not None:
            current = current.astimezone(timezone.utc).replace(tzinfo=None)
        age = current - quote_datetime
        if age > timedelta(days=freshness_days):
            warnings.append(
                f"quote timestamp {timestamp_text} is older than "
                f"{freshness_days:g} days (now {current.strftime('%Y-%m-%d %H:%M')})"
            )

    # Currency mismatch: HK identities must report HKD.
    if identity.market == "HK" and currency != "HKD":
        warnings.append(
            f"currency {currency} does not match expected HKD for HK ticker"
        )

    # Sanity check: reported total market cap should agree with
    # share_price * shares_outstanding; if not, drop shares_outstanding so
    # downstream math falls back to the reported market cap.
    if (
        share_price is not None
        and shares_outstanding is not None
        and market_cap is not None
    ):
        derived = share_price * shares_outstanding
        if derived > 0:
            ratio = market_cap / derived
            if ratio < 0.5 or ratio > 2.0:
                shares_outstanding = None
                warnings.append(
                    "reported market cap disagrees with share_price x "
                    "shares_outstanding; dropping shares_outstanding"
                )

    # Require at least one usable signal so the provider can meaningfully
    # inform the valuation draft, even if the snapshot itself may not be
    # writeable without both of market_cap or share_price+shares_outstanding.
    if share_price is None and market_cap is None and shares_outstanding is None:
        return None

    return {
        "as_of_date": source_date,
        "currency": currency,
        "market_cap": market_cap,
        "share_price": share_price,
        "shares_outstanding": shares_outstanding,
        "source": f"{TENCENT_QUOTE_URL}hk{code}",
        "source_date": source_date,
        "warnings": warnings,
    }


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        compact = value.replace(",", "").strip()
        if not compact:
            return None
        try:
            return float(compact)
        except ValueError:
            return None
    return None


def _parse_tencent_datetime(timestamp_text: str) -> datetime | None:
    """Return a naive datetime parsed from Tencent's ``YYYY/MM/DD HH:MM:SS``."""

    if not timestamp_text:
        return None
    try:
        return datetime.strptime(timestamp_text, "%Y/%m/%d %H:%M:%S")
    except ValueError:
        head = timestamp_text.split(" ", 1)[0]
        try:
            return datetime.strptime(head, "%Y/%m/%d")
        except ValueError:
            return None


def _as_currency(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    return text or None


def _iso_date_from_epoch(value: Any) -> str | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    try:
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
    return dt.strftime("%Y-%m-%d")
