"""Financial snapshot loading and cash runway estimation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from biotech_alpha.models import AgentFinding, Evidence


@dataclass(frozen=True)
class FinancialSnapshot:
    """Minimal financial inputs needed for a first-pass runway estimate."""

    as_of_date: str
    currency: str
    cash_and_equivalents: float
    short_term_debt: float = 0.0
    quarterly_cash_burn: float | None = None
    operating_cash_flow_ttm: float | None = None
    source: str | None = None
    source_date: str | None = None


@dataclass(frozen=True)
class CashRunwayEstimate:
    """Derived cash runway estimate."""

    currency: str
    net_cash: float
    monthly_cash_burn: float | None
    runway_months: float | None
    method: str
    needs_human_review: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FinancialValidationReport:
    """Validation result for a financial snapshot file."""

    has_snapshot: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    runway_months: float | None = None


def load_financial_snapshot(path: str | Path) -> FinancialSnapshot:
    """Load a financial snapshot from JSON."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("financial snapshot must be a JSON object")
    return financial_snapshot_from_dict(payload)


def validate_financial_snapshot_file(path: str | Path) -> FinancialValidationReport:
    """Validate a financial snapshot file and estimate runway if possible."""

    try:
        snapshot = load_financial_snapshot(path)
        estimate = estimate_cash_runway(snapshot)
    except Exception as exc:  # noqa: BLE001 - return validation errors.
        return FinancialValidationReport(has_snapshot=False, errors=(str(exc),))

    warnings = [
        *estimate.warnings,
        *_financial_placeholder_warnings(snapshot),
    ]
    return FinancialValidationReport(
        has_snapshot=True,
        warnings=tuple(warnings),
        runway_months=estimate.runway_months,
    )


def financial_snapshot_template(
    company: str,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable starter template for financial inputs."""

    company = company.strip()
    if not company:
        raise ValueError("company must not be empty")
    return {
        "company": company,
        "ticker": ticker,
        "as_of_date": "YYYY-MM-DD",
        "currency": "HKD",
        "cash_and_equivalents": 1200000000,
        "short_term_debt": 300000000,
        "quarterly_cash_burn": 150000000,
        "operating_cash_flow_ttm": None,
        "source": "annual-report.pdf",
        "source_date": "YYYY-MM-DD",
    }


def write_financial_snapshot_template(
    *,
    path: str | Path,
    company: str,
    ticker: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write a financial snapshot template to disk."""

    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            financial_snapshot_template(company=company, ticker=ticker),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def financial_snapshot_from_dict(payload: dict[str, Any]) -> FinancialSnapshot:
    """Build a financial snapshot from a dictionary."""

    return FinancialSnapshot(
        as_of_date=_required_str(payload, "as_of_date"),
        currency=_required_str(payload, "currency"),
        cash_and_equivalents=_required_number(payload, "cash_and_equivalents"),
        short_term_debt=_optional_number(payload.get("short_term_debt")) or 0.0,
        quarterly_cash_burn=_optional_number(payload.get("quarterly_cash_burn")),
        operating_cash_flow_ttm=_optional_number(
            payload.get("operating_cash_flow_ttm")
        ),
        source=_optional_str(payload.get("source")),
        source_date=_optional_str(payload.get("source_date")),
    )


def estimate_cash_runway(snapshot: FinancialSnapshot) -> CashRunwayEstimate:
    """Estimate cash runway from a minimal financial snapshot."""

    warnings: list[str] = []
    net_cash = snapshot.cash_and_equivalents - snapshot.short_term_debt
    monthly_burn: float | None = None
    method = "不可用"

    if snapshot.quarterly_cash_burn is not None:
        monthly_burn = snapshot.quarterly_cash_burn / 3
        method = "季度现金消耗 / 3"
    elif snapshot.operating_cash_flow_ttm is not None:
        if snapshot.operating_cash_flow_ttm < 0:
            monthly_burn = abs(snapshot.operating_cash_flow_ttm) / 12
            method = "abs(过去十二个月经营现金流) / 12"
        else:
            warnings.append("过去十二个月经营现金流为非负值")
    else:
        warnings.append("缺少现金消耗输入")

    if net_cash <= 0:
        warnings.append("净现金为非正值")
    if monthly_burn is not None and monthly_burn <= 0:
        warnings.append("月度现金消耗为非正值")
        monthly_burn = None

    runway_months = None
    if monthly_burn:
        runway_months = net_cash / monthly_burn

    return CashRunwayEstimate(
        currency=snapshot.currency,
        net_cash=net_cash,
        monthly_cash_burn=monthly_burn,
        runway_months=runway_months,
        method=method,
        needs_human_review=bool(warnings) or runway_months is None,
        warnings=tuple(warnings),
    )


def cash_runway_finding(
    *,
    company: str,
    snapshot: FinancialSnapshot,
    estimate: CashRunwayEstimate,
) -> AgentFinding:
    """Convert a cash runway estimate into an agent finding."""

    runway_text = (
        f"{estimate.runway_months:.1f} 个月"
        if estimate.runway_months is not None
        else "不可用"
    )
    evidence = ()
    if snapshot.source:
        evidence = (
            Evidence(
                claim=(
                    f"{company} 披露货币资金 "
                    f"{snapshot.cash_and_equivalents:g} {snapshot.currency} "
                    f"（截至 {snapshot.as_of_date}）。"
                ),
                source=snapshot.source,
                source_date=snapshot.source_date,
                confidence=0.75,
            ),
        )

    return AgentFinding(
        agent_name="cash_runway_agent",
        summary=(
            f"{company} 估算的现金流可持续期为 {runway_text}，采用 "
            f"{estimate.method}."
        ),
        risks=estimate.warnings,
        evidence=evidence,
        confidence=0.55 if estimate.runway_months is not None else 0.2,
        needs_human_review=estimate.needs_human_review,
    )


def cash_runway_payload(
    snapshot: FinancialSnapshot,
    estimate: CashRunwayEstimate,
) -> dict[str, Any]:
    """Return a JSON-serializable cash runway payload."""

    return {
        "snapshot": asdict(snapshot),
        "estimate": asdict(estimate),
    }


def financial_validation_report_as_dict(
    report: FinancialValidationReport,
) -> dict[str, Any]:
    """Convert financial validation reports into JSON-serializable dictionaries."""

    return asdict(report)


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"financial field {key!r} must be a non-empty string")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional financial text fields must be strings")
    value = value.strip()
    return value or None


def _required_number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    number = _optional_number(value)
    if number is None:
        raise ValueError(f"financial field {key!r} must be a number")
    return number


def _optional_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("financial numeric fields must be numbers")
    return float(value)


def _financial_placeholder_warnings(
    snapshot: FinancialSnapshot,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if snapshot.as_of_date == "YYYY-MM-DD":
        warnings.append("replace placeholder as_of_date")
    if snapshot.source_date == "YYYY-MM-DD":
        warnings.append("replace placeholder source_date")
    if snapshot.source in {"annual-report.pdf", "report-or-presentation-file.pdf"}:
        warnings.append("replace placeholder source")
    return tuple(warnings)
