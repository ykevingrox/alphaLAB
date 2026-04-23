"""Valuation snapshot loading and first-pass context metrics."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from biotech_alpha.models import AgentFinding, Evidence


@dataclass(frozen=True)
class ValuationSnapshot:
    """Minimal market inputs for first-pass valuation context."""

    as_of_date: str
    currency: str
    market_cap: float | None = None
    share_price: float | None = None
    shares_outstanding: float | None = None
    cash_and_equivalents: float = 0.0
    total_debt: float = 0.0
    revenue_ttm: float | None = None
    source: str | None = None
    source_date: str | None = None


@dataclass(frozen=True)
class ValuationMetrics:
    """Derived valuation context metrics."""

    currency: str
    market_cap: float
    enterprise_value: float
    revenue_multiple: float | None
    market_cap_method: str
    needs_human_review: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValuationValidationReport:
    """Validation result for a valuation snapshot file."""

    has_snapshot: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    market_cap: float | None = None
    enterprise_value: float | None = None
    revenue_multiple: float | None = None


def load_valuation_snapshot(path: str | Path) -> ValuationSnapshot:
    """Load a valuation snapshot from JSON."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("valuation snapshot must be a JSON object")
    return valuation_snapshot_from_dict(payload)


def validate_valuation_snapshot_file(path: str | Path) -> ValuationValidationReport:
    """Validate a valuation snapshot and calculate context metrics."""

    try:
        snapshot = load_valuation_snapshot(path)
        metrics = calculate_valuation_metrics(snapshot)
    except Exception as exc:  # noqa: BLE001 - return validation errors.
        return ValuationValidationReport(has_snapshot=False, errors=(str(exc),))

    warnings = [
        *metrics.warnings,
        *_valuation_placeholder_warnings(snapshot),
    ]
    return ValuationValidationReport(
        has_snapshot=True,
        warnings=tuple(warnings),
        market_cap=metrics.market_cap,
        enterprise_value=metrics.enterprise_value,
        revenue_multiple=metrics.revenue_multiple,
    )


def valuation_snapshot_template(
    company: str,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Return a starter template for market valuation inputs."""

    company = company.strip()
    if not company:
        raise ValueError("company must not be empty")
    return {
        "company": company,
        "ticker": ticker,
        "as_of_date": "YYYY-MM-DD",
        "currency": "HKD",
        "market_cap": 25000000000,
        "share_price": None,
        "shares_outstanding": None,
        "cash_and_equivalents": 1200000000,
        "total_debt": 300000000,
        "revenue_ttm": 1500000000,
        "source": "market-data-snapshot",
        "source_date": "YYYY-MM-DD",
    }


def write_valuation_snapshot_template(
    *,
    path: str | Path,
    company: str,
    ticker: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write a valuation snapshot template to disk."""

    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            valuation_snapshot_template(company=company, ticker=ticker),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def valuation_snapshot_from_dict(payload: dict[str, Any]) -> ValuationSnapshot:
    """Build a valuation snapshot from a dictionary."""

    return ValuationSnapshot(
        as_of_date=_required_str(payload, "as_of_date"),
        currency=_required_str(payload, "currency"),
        market_cap=_optional_number(payload.get("market_cap")),
        share_price=_optional_number(payload.get("share_price")),
        shares_outstanding=_optional_number(payload.get("shares_outstanding")),
        cash_and_equivalents=_optional_number(
            payload.get("cash_and_equivalents")
        )
        or 0.0,
        total_debt=_optional_number(payload.get("total_debt")) or 0.0,
        revenue_ttm=_optional_number(payload.get("revenue_ttm")),
        source=_optional_str(payload.get("source")),
        source_date=_optional_str(payload.get("source_date")),
    )


def calculate_valuation_metrics(snapshot: ValuationSnapshot) -> ValuationMetrics:
    """Calculate market cap, enterprise value, and revenue multiple."""

    warnings: list[str] = []
    market_cap = snapshot.market_cap
    market_cap_method = "market_cap"
    if market_cap is None:
        if snapshot.share_price is None or snapshot.shares_outstanding is None:
            raise ValueError(
                "valuation snapshot requires market_cap or share_price and "
                "shares_outstanding"
            )
        market_cap = snapshot.share_price * snapshot.shares_outstanding
        market_cap_method = "share_price * shares_outstanding"

    enterprise_value = (
        market_cap + snapshot.total_debt - snapshot.cash_and_equivalents
    )
    if enterprise_value < 0:
        warnings.append("enterprise value is negative")

    revenue_multiple = None
    if snapshot.revenue_ttm is None:
        warnings.append("revenue_ttm unavailable; revenue multiple not calculated")
    elif snapshot.revenue_ttm <= 0:
        warnings.append("revenue_ttm is non-positive")
    else:
        revenue_multiple = enterprise_value / snapshot.revenue_ttm

    return ValuationMetrics(
        currency=snapshot.currency,
        market_cap=market_cap,
        enterprise_value=enterprise_value,
        revenue_multiple=revenue_multiple,
        market_cap_method=market_cap_method,
        needs_human_review=bool(warnings),
        warnings=tuple(warnings),
    )


def valuation_finding(
    *,
    company: str,
    snapshot: ValuationSnapshot,
    metrics: ValuationMetrics,
) -> AgentFinding:
    """Convert valuation metrics into an agent finding."""

    multiple_text = (
        f"营收倍数 {metrics.revenue_multiple:.1f}x"
        if metrics.revenue_multiple is not None
        else "营收倍数不可用"
    )
    evidence = ()
    if snapshot.source:
        evidence = (
            Evidence(
                claim=(
                    f"{company} 估值快照使用市值 "
                    f"{metrics.market_cap:g} {metrics.currency} as of "
                    f"{snapshot.as_of_date}。"
                ),
                source=snapshot.source,
                source_date=snapshot.source_date,
                confidence=0.7,
            ),
        )

    return AgentFinding(
        agent_name="valuation_agent",
        summary=(
            f"{company} 企业价值约为 {metrics.enterprise_value:g} "
            f"{metrics.currency}；估值上下文为 {multiple_text}。"
        ),
        risks=metrics.warnings,
        evidence=evidence,
        confidence=0.55,
        needs_human_review=metrics.needs_human_review,
    )


def valuation_payload(
    snapshot: ValuationSnapshot,
    metrics: ValuationMetrics,
) -> dict[str, Any]:
    """Return a JSON-serializable valuation payload."""

    return {
        "snapshot": asdict(snapshot),
        "metrics": asdict(metrics),
    }


def valuation_validation_report_as_dict(
    report: ValuationValidationReport,
) -> dict[str, Any]:
    """Convert valuation validation reports into JSON dictionaries."""

    return asdict(report)


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"valuation field {key!r} must be a non-empty string")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional valuation text fields must be strings")
    value = value.strip()
    return value or None


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("valuation numeric fields must be numbers")
    return float(value)


def _valuation_placeholder_warnings(
    snapshot: ValuationSnapshot,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if snapshot.as_of_date == "YYYY-MM-DD":
        warnings.append("replace placeholder as_of_date")
    if snapshot.source_date == "YYYY-MM-DD":
        warnings.append("replace placeholder source_date")
    if snapshot.source == "market-data-snapshot":
        warnings.append("replace placeholder source")
    return tuple(warnings)
