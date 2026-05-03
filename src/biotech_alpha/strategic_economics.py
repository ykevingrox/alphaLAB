"""Curated strategic-economics input loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StrategicEconomicsValidationReport:
    """Validation result for curated strategic-economics inputs."""

    retained_economics_count: int
    bd_event_count: int
    platform_evidence_count: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def strategic_economics_template(
    company: str,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Return a starter template for BD and retained-economics curation."""

    company = company.strip()
    if not company:
        raise ValueError("company must not be empty")
    return {
        "company": company,
        "ticker": ticker,
        "as_of_date": "YYYY-MM-DD",
        "retained_economics": [
            {
                "asset": "Example asset name",
                "region": "China / ex-China / global / unknown",
                "partner": "Example partner or null",
                "rights_status": "retained / partnered / out_licensed / unknown",
                "economics_share": "disclosed / inferred / unknown",
                "economics_type": "profit_share / royalty / milestone / self_commercial / unknown",
                "evidence": [
                    {
                        "claim": "Company retains China rights while partner leads ex-China development.",
                        "source": "annual-report-or-announcement-url",
                        "source_date": "YYYY-MM-DD",
                        "confidence": 0.6,
                    }
                ],
            }
        ],
        "bd_events": [
            {
                "asset": "Example asset name",
                "event_type": "license / collaboration / option / newco / other",
                "partner": "Example partner",
                "summary": "Short source-backed BD event summary.",
                "economics_terms": "Upfront / milestone / royalty terms if disclosed; otherwise state not disclosed.",
                "source": "announcement-url",
                "source_date": "YYYY-MM-DD",
                "confidence": 0.6,
            }
        ],
        "platform_evidence": [
            {
                "claim": "Platform repeatability claim, only if company-specific evidence exists.",
                "scope": "asset class / target class / discovery engine / unknown",
                "source": "source-url",
                "source_date": "YYYY-MM-DD",
                "confidence": 0.4,
            }
        ],
    }


def write_strategic_economics_template(
    *,
    path: str | Path,
    company: str,
    ticker: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write a starter strategic-economics JSON file."""

    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            strategic_economics_template(company=company, ticker=ticker),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def load_strategic_economics(path: str | Path) -> dict[str, Any]:
    """Load a curated strategic-economics input file as a plain payload."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("strategic economics file must contain a JSON object")
    return _normalized_payload(payload)


def validate_strategic_economics_file(
    path: str | Path,
) -> StrategicEconomicsValidationReport:
    """Validate a curated strategic-economics file."""

    try:
        payload = load_strategic_economics(path)
    except Exception as exc:  # noqa: BLE001 - return validation errors.
        return StrategicEconomicsValidationReport(
            retained_economics_count=0,
            bd_event_count=0,
            platform_evidence_count=0,
            errors=(str(exc),),
        )

    warnings: list[str] = []
    if payload.get("as_of_date") == "YYYY-MM-DD":
        warnings.append("replace placeholder as_of_date")
    retained = _list(payload.get("retained_economics"))
    bd_events = _list(payload.get("bd_events"))
    platform = _list(payload.get("platform_evidence"))
    if not retained and not bd_events and not platform:
        warnings.append(
            "provide at least one retained_economics, bd_events, or platform_evidence row"
        )
    for index, row in enumerate(retained, start=1):
        prefix = f"retained_economics[{index}]"
        _warn_missing(row, prefix, ("asset", "region", "rights_status"), warnings)
        _warn_placeholder(row.get("asset"), f"{prefix}.asset", warnings)
        _warn_evidence(row.get("evidence"), prefix, warnings)
        if str(row.get("economics_share") or "").casefold() in {"", "unknown"}:
            warnings.append(f"{prefix}: economics_share is unknown")
    for index, row in enumerate(bd_events, start=1):
        prefix = f"bd_events[{index}]"
        _warn_missing(row, prefix, ("summary", "partner", "source"), warnings)
        _warn_placeholder(row.get("summary"), f"{prefix}.summary", warnings)
        if row.get("economics_terms") in (None, "", "not disclosed"):
            warnings.append(f"{prefix}: economics_terms are not disclosed")
    for index, row in enumerate(platform, start=1):
        prefix = f"platform_evidence[{index}]"
        _warn_missing(row, prefix, ("claim", "scope", "source"), warnings)
        _warn_placeholder(row.get("claim"), f"{prefix}.claim", warnings)

    return StrategicEconomicsValidationReport(
        retained_economics_count=len(retained),
        bd_event_count=len(bd_events),
        platform_evidence_count=len(platform),
        warnings=tuple(warnings),
    )


def strategic_economics_validation_report_as_dict(
    report: StrategicEconomicsValidationReport,
) -> dict[str, Any]:
    """Return a JSON-serializable validation report."""

    return {
        "retained_economics_count": report.retained_economics_count,
        "bd_event_count": report.bd_event_count,
        "platform_evidence_count": report.platform_evidence_count,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
        "status": "error" if report.errors else "ok",
    }


def _normalized_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "company": _optional_str(payload.get("company")),
        "ticker": _optional_str(payload.get("ticker")),
        "as_of_date": _optional_str(payload.get("as_of_date")),
        "retained_economics": _list(payload.get("retained_economics")),
        "bd_events": _list(payload.get("bd_events")),
        "platform_evidence": _list(payload.get("platform_evidence")),
    }


def _list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("strategic economics list fields must be arrays")
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("strategic economics rows must be objects")
        rows.append(dict(item))
    return rows


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("strategic economics metadata fields must be strings")
    return value.strip() or None


def _warn_missing(
    row: dict[str, Any],
    prefix: str,
    keys: tuple[str, ...],
    warnings: list[str],
) -> None:
    for key in keys:
        if not str(row.get(key) or "").strip():
            warnings.append(f"{prefix}: missing {key}")


def _warn_placeholder(value: Any, field: str, warnings: list[str]) -> None:
    text = str(value or "").casefold()
    if "example" in text or "placeholder" in text:
        warnings.append(f"{field}: replace placeholder text")


def _warn_evidence(value: Any, prefix: str, warnings: list[str]) -> None:
    evidence_rows = value if isinstance(value, list) else []
    if not evidence_rows:
        warnings.append(f"{prefix}: missing evidence")
        return
    for index, evidence in enumerate(evidence_rows, start=1):
        if not isinstance(evidence, dict):
            warnings.append(f"{prefix}.evidence[{index}]: evidence must be object")
            continue
        if not str(evidence.get("source") or "").strip():
            warnings.append(f"{prefix}.evidence[{index}]: missing source")
        if evidence.get("source_date") == "YYYY-MM-DD":
            warnings.append(f"{prefix}.evidence[{index}]: replace source_date")
