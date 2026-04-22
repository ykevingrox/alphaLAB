"""Market-data normalization utilities for valuation inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NormalizedMarketData:
    """Provider-agnostic market data fields used by valuation inputs."""

    as_of_date: str | None
    currency: str
    market_cap: float | None
    share_price: float | None
    shares_outstanding: float | None
    source: str | None
    source_date: str | None
    warnings: tuple[str, ...] = ()


def normalize_hk_market_data(payload: dict[str, Any]) -> NormalizedMarketData:
    """Normalize a first-pass Hong Kong market-data payload."""

    warnings: list[str] = []
    provider_warnings = payload.get("warnings")
    if isinstance(provider_warnings, (list, tuple)):
        for item in provider_warnings:
            if isinstance(item, str) and item.strip():
                warnings.append(item.strip())

    as_of_date = _optional_text(payload.get("as_of_date"))
    source = _optional_text(payload.get("source"))
    source_date = _optional_text(payload.get("source_date")) or as_of_date
    currency = _optional_text(payload.get("currency")) or "HKD"
    market_cap = _optional_number(payload.get("market_cap"))
    share_price = _optional_number(payload.get("share_price"))
    shares_outstanding = _optional_number(payload.get("shares_outstanding"))

    if as_of_date is None:
        warnings.append("market data missing as_of_date")
    if source is None:
        warnings.append("market data missing source")
    if market_cap is None and (share_price is None or shares_outstanding is None):
        warnings.append(
            "market data missing market_cap and share_price/shares_outstanding pair"
        )

    return NormalizedMarketData(
        as_of_date=as_of_date,
        currency=currency,
        market_cap=market_cap,
        share_price=share_price,
        shares_outstanding=shares_outstanding,
        source=source,
        source_date=source_date,
        warnings=tuple(warnings),
    )


def valuation_snapshot_payload_from_market_data(
    *,
    company: str,
    ticker: str | None,
    normalized: NormalizedMarketData,
    cash_and_equivalents: float = 0.0,
    total_debt: float = 0.0,
    revenue_ttm: float | None = None,
) -> dict[str, Any]:
    """Build a valuation snapshot payload compatible with valuation validators."""

    return {
        "company": company,
        "ticker": ticker,
        "as_of_date": normalized.as_of_date or "YYYY-MM-DD",
        "currency": normalized.currency,
        "market_cap": normalized.market_cap,
        "share_price": normalized.share_price,
        "shares_outstanding": normalized.shares_outstanding,
        "cash_and_equivalents": cash_and_equivalents,
        "total_debt": total_debt,
        "revenue_ttm": revenue_ttm,
        "source": normalized.source or "market-data-snapshot",
        "source_date": normalized.source_date or "YYYY-MM-DD",
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _optional_number(value: Any) -> float | None:
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
