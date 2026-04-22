"""Conference catalyst input loading and validation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from biotech_alpha.models import Catalyst, Evidence

ConferenceSourceType = Literal[
    "conference_abstract",
    "conference_oral",
    "conference_poster",
    "company_disclosure",
    "official_registry",
    "other",
]

CONFERENCE_CATALYST_CATEGORIES = {
    "clinical",
    "regulatory",
    "commercial",
    "financial",
    "conference",
    "corporate",
    "unknown",
}


@dataclass(frozen=True)
class ConferenceCatalystValidationReport:
    """Validation result for curated conference catalyst inputs."""

    catalyst_count: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def load_conference_catalysts(path: str | Path) -> tuple[Catalyst, ...]:
    """Load curated conference catalysts from JSON."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("catalysts") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("conference catalyst file must contain a catalysts list")
    return tuple(_conference_catalyst_from_dict(row) for row in rows)


def validate_conference_catalyst_file(
    path: str | Path,
) -> ConferenceCatalystValidationReport:
    """Validate a conference catalyst file and return warnings."""

    try:
        catalysts = load_conference_catalysts(path)
    except Exception as exc:  # noqa: BLE001 - return validation errors.
        return ConferenceCatalystValidationReport(catalyst_count=0, errors=(str(exc),))

    warnings: list[str] = []
    for catalyst in catalysts:
        if catalyst.category != "conference":
            warnings.append(
                f"{catalyst.title}: category is {catalyst.category!r}; "
                "conference inputs should use category conference"
            )
        if catalyst.expected_date is None and not catalyst.expected_window:
            warnings.append(
                f"{catalyst.title}: expected_date or expected_window should be provided"
            )
        if catalyst.confidence <= 0:
            warnings.append(f"{catalyst.title}: confidence should be greater than 0")
        if not catalyst.evidence:
            warnings.append(f"{catalyst.title}: missing evidence")
        for evidence in catalyst.evidence:
            if _looks_like_placeholder(evidence.source):
                warnings.append(
                    f"{catalyst.title}: replace placeholder evidence source"
                )
            if evidence.source_date == "YYYY-MM-DD":
                warnings.append(f"{catalyst.title}: replace placeholder evidence date")
    return ConferenceCatalystValidationReport(
        catalyst_count=len(catalysts),
        warnings=tuple(warnings),
    )


def conference_catalyst_template(
    company: str,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Return a starter template for conference catalyst curation."""

    company = company.strip()
    if not company:
        raise ValueError("company must not be empty")
    return {
        "company": company,
        "ticker": ticker,
        "catalysts": [
            {
                "title": "ASCO oral presentation expected",
                "category": "conference",
                "expected_date": "YYYY-MM-DD",
                "expected_window": "ASCO 2027",
                "related_asset": "Example asset name",
                "confidence": 0.45,
                "source_type": "conference_abstract",
                "evidence": [
                    {
                        "claim": "Abstract accepted for conference presentation.",
                        "source": "conference-abstract-link-or-id",
                        "source_date": "YYYY-MM-DD",
                        "confidence": 0.6,
                    }
                ],
            }
        ],
    }


def write_conference_catalyst_template(
    *,
    path: str | Path,
    company: str,
    ticker: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write a conference catalyst template to disk."""

    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            conference_catalyst_template(company=company, ticker=ticker),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def conference_validation_report_as_dict(
    report: ConferenceCatalystValidationReport,
) -> dict[str, Any]:
    """Convert conference validation reports into JSON-serializable dictionaries."""

    return asdict(report)


def _conference_catalyst_from_dict(row: Any) -> Catalyst:
    if not isinstance(row, dict):
        raise ValueError("each conference catalyst must be an object")
    source_type = _optional_str(row.get("source_type"))
    evidence = tuple(_evidence_from_dict(item) for item in row.get("evidence", []))
    if source_type:
        evidence = (
            *evidence,
            Evidence(
                claim=f"Conference source type: {source_type}.",
                source="conference_source_type",
                confidence=0.5,
                is_inferred=True,
            ),
        )
    return Catalyst(
        title=_required_str(row, "title"),
        category=_optional_category(row.get("category")),
        expected_date=_optional_date(row.get("expected_date")),
        expected_window=_optional_str(row.get("expected_window")),
        related_asset=_optional_str(row.get("related_asset")),
        confidence=_optional_confidence(row.get("confidence")),
        evidence=evidence,
    )


def _evidence_from_dict(row: Any) -> Evidence:
    if not isinstance(row, dict):
        raise ValueError("each evidence entry must be an object")
    return Evidence(
        claim=_required_str(row, "claim"),
        source=_required_str(row, "source"),
        source_date=_optional_str(row.get("source_date")),
        retrieved_at=_optional_str(row.get("retrieved_at")),
        confidence=float(row.get("confidence", 0.0)),
        is_inferred=bool(row.get("is_inferred", False)),
    )


def _optional_date(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected_date must be YYYY-MM-DD when set")
    value = value.strip()
    if value == "YYYY-MM-DD":
        return None
    from datetime import date

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("expected_date must be YYYY-MM-DD when set") from exc


def _optional_confidence(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("confidence must be a number")
    return float(value)


def _optional_category(value: Any) -> Any:
    if value is None:
        return "conference"
    if not isinstance(value, str) or not value.strip():
        raise ValueError("category must be a non-empty string when set")
    category = value.strip()
    if category not in CONFERENCE_CATALYST_CATEGORIES:
        allowed = ", ".join(sorted(CONFERENCE_CATALYST_CATEGORIES))
        raise ValueError(f"category must be one of: {allowed}")
    return category


def _required_str(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"conference catalyst field {key!r} must be a non-empty string"
        )
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional conference catalyst fields must be strings")
    value = value.strip()
    return value or None


def _looks_like_placeholder(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().casefold()
    return normalized in {
        "conference-abstract-link-or-id",
        "report-or-presentation-file.pdf",
    }
