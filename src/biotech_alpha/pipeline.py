"""Pipeline asset loading and deterministic trial matching."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from biotech_alpha.models import (
    ClinicalDataPoint,
    Evidence,
    PipelineAsset,
    TrialAssetMatch,
    TrialSummary,
)


@dataclass(frozen=True)
class PipelineValidationReport:
    """Validation result for a curated pipeline asset file."""

    asset_count: int
    evidence_count: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def load_pipeline_assets(path: str | Path) -> tuple[PipelineAsset, ...]:
    """Load disclosed pipeline assets from a local JSON file.

    The accepted shape is either a list of asset objects or an object with an
    ``assets`` list. This keeps manual curation and future document extraction
    on the same contract.
    """

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("assets") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("pipeline asset file must contain a list or an assets list")
    return tuple(_pipeline_asset_from_dict(row) for row in rows)


def validate_pipeline_asset_file(path: str | Path) -> PipelineValidationReport:
    """Validate a pipeline asset file and return actionable warnings."""

    try:
        assets = load_pipeline_assets(path)
    except Exception as exc:  # noqa: BLE001 - report validation failures.
        return PipelineValidationReport(
            asset_count=0,
            evidence_count=0,
            errors=(str(exc),),
        )

    warnings: list[str] = []
    seen_terms: dict[str, str] = {}
    evidence_count = 0
    for asset in assets:
        if _looks_like_placeholder(asset.name):
            warnings.append(f"{asset.name}: replace template placeholder asset name")
        if not asset.evidence:
            warnings.append(f"{asset.name}: missing evidence")
        evidence_count += len(asset.evidence)
        for term in asset.aliases:
            if _looks_like_placeholder(term):
                warnings.append(f"{asset.name}: replace template placeholder {term!r}")
            normalized = _normalize_for_match(term)
            if not normalized:
                continue
            existing = seen_terms.get(normalized)
            if existing and existing != asset.name:
                warnings.append(
                    f"{asset.name}: duplicate name or alias {term!r} also used by "
                    f"{existing}"
                )
            else:
                seen_terms[normalized] = asset.name
        normalized_name = _normalize_for_match(asset.name)
        if normalized_name:
            existing = seen_terms.get(normalized_name)
            if existing:
                warnings.append(
                    f"{asset.name}: duplicate name or alias {asset.name!r} also "
                    f"used by {existing}"
                )
            else:
                seen_terms[normalized_name] = asset.name
        if not asset.target and not asset.mechanism:
            warnings.append(f"{asset.name}: missing target or mechanism")
        if not asset.indication:
            warnings.append(f"{asset.name}: missing indication")
        if not asset.phase:
            warnings.append(f"{asset.name}: missing phase")
        if asset.next_milestone:
            if "\n" in asset.next_milestone or "\r" in asset.next_milestone:
                warnings.append(
                    f"{asset.name}: next_milestone contains newline/control "
                    "characters; normalize to one-line text"
                )
            if _looks_like_stale_year(
                asset.next_milestone,
                source_year=_max_evidence_year(asset.evidence),
            ):
                warnings.append(
                    f"{asset.name}: next_milestone year looks stale vs "
                    "evidence dates; verify historical leakage"
                )
        for evidence in asset.evidence:
            if _looks_like_placeholder(evidence.source):
                warnings.append(f"{asset.name}: replace placeholder evidence source")
            if evidence.source_date == "YYYY-MM-DD":
                warnings.append(f"{asset.name}: replace placeholder evidence date")
            if evidence.confidence <= 0:
                warnings.append(
                    f"{asset.name}: evidence confidence is non-positive; "
                    "set a realistic confidence score"
                )
            if evidence.is_inferred and not evidence.source_date:
                warnings.append(
                    f"{asset.name}: inferred evidence missing source_date; "
                    "add publication date for auditability"
                )

    return PipelineValidationReport(
        asset_count=len(assets),
        evidence_count=evidence_count,
        warnings=tuple(warnings),
    )


def pipeline_asset_template(company: str, ticker: str | None = None) -> dict[str, Any]:
    """Return a JSON-serializable starter template for manual asset curation."""

    company = company.strip()
    if not company:
        raise ValueError("company must not be empty")
    return {
        "company": company,
        "ticker": ticker,
        "assets": [
            {
                "name": "Example asset name",
                "aliases": ["Example asset code"],
                "target": "Example target",
                "modality": "Example modality",
                "mechanism": "Example mechanism",
                "indication": "Example indication",
                "phase": "Example phase",
                "geography": "Example geography",
                "rights": "Example rights",
                "partner": "Example partner",
                "regulatory_pathway": "BLA under review for 3L+ EP-NEC in China",
                "next_binary_event": "BLA acceptance/update expected in 2026",
                "next_milestone": "Example expected milestone window",
                "clinical_data": [
                    {
                        "metric": "ORR",
                        "value": "42",
                        "unit": "%",
                        "sample_size": 58,
                        "context": "relapsed setting interim cutoff",
                    }
                ],
                "evidence": [
                    {
                        "claim": "Short source-backed claim for this asset.",
                        "source": "report-or-presentation-file.pdf",
                        "source_date": "YYYY-MM-DD",
                        "confidence": 0.7,
                    }
                ],
            }
        ],
    }


def write_pipeline_asset_template(
    *,
    path: str | Path,
    company: str,
    ticker: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write a pipeline asset template to disk."""

    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            pipeline_asset_template(company=company, ticker=ticker),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def validation_report_as_dict(report: PipelineValidationReport) -> dict[str, Any]:
    """Convert validation reports into JSON-serializable dictionaries."""

    return asdict(report)


def match_pipeline_assets_to_trials(
    assets: tuple[PipelineAsset, ...],
    trials: tuple[TrialSummary, ...],
) -> tuple[TrialAssetMatch, ...]:
    """Match assets to registry trials using asset names and aliases."""

    matches: list[TrialAssetMatch] = []
    for asset in assets:
        for trial in trials:
            match = _match_asset_to_trial(asset, trial)
            if match:
                matches.append(match)
    return tuple(matches)


def _pipeline_asset_from_dict(row: Any) -> PipelineAsset:
    if not isinstance(row, dict):
        raise ValueError("each pipeline asset must be an object")
    name = _required_str(row, "name")
    return PipelineAsset(
        name=name,
        aliases=_str_tuple(row.get("aliases")),
        target=_optional_str(row.get("target")),
        modality=_optional_str(row.get("modality")),
        mechanism=_optional_str(row.get("mechanism")),
        indication=_optional_str(row.get("indication")),
        phase=_optional_str(row.get("phase")),
        geography=_optional_str(row.get("geography")),
        rights=_optional_str(row.get("rights")),
        partner=_optional_str(row.get("partner")),
        regulatory_pathway=_optional_str(row.get("regulatory_pathway")),
        next_binary_event=_optional_str(row.get("next_binary_event")),
        next_milestone=_optional_str(row.get("next_milestone")),
        clinical_data=_clinical_data_tuple(row.get("clinical_data")),
        evidence=tuple(_evidence_from_dict(item) for item in row.get("evidence", [])),
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


def _match_asset_to_trial(
    asset: PipelineAsset,
    trial: TrialSummary,
) -> TrialAssetMatch | None:
    terms = _asset_terms(asset)
    for term in terms:
        for intervention in trial.interventions:
            if _contains_term(intervention, term):
                return TrialAssetMatch(
                    asset_name=asset.name,
                    registry_id=trial.registry_id,
                    match_reason="intervention",
                    matched_text=intervention,
                    confidence=0.9,
                )
    for term in terms:
        if _contains_term(trial.title, term):
            return TrialAssetMatch(
                asset_name=asset.name,
                registry_id=trial.registry_id,
                match_reason="title",
                matched_text=trial.title,
                confidence=0.75,
            )
    return None


def _asset_terms(asset: PipelineAsset) -> tuple[str, ...]:
    seen: set[str] = set()
    terms: list[str] = []
    for term in (asset.name, *asset.aliases):
        normalized = _normalize_for_match(term)
        if len(normalized) < 3 or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
    return tuple(sorted(terms, key=len, reverse=True))


def _contains_term(value: str, term: str) -> bool:
    return _normalize_for_match(term) in _normalize_for_match(value)


def _normalize_for_match(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _looks_like_placeholder(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().casefold()
    return (
        normalized.startswith("example ")
        or normalized == "yyyy-mm-dd"
        or normalized in {"report-or-presentation-file.pdf", "annual-report.pdf"}
    )


def _max_evidence_year(evidence_items: tuple[Evidence, ...]) -> int | None:
    years = [
        year
        for year in (_year_from_text(item.source_date) for item in evidence_items)
        if year is not None
    ]
    return max(years) if years else None


def _year_from_text(value: str | None) -> int | None:
    if not value:
        return None
    match = re.match(r"^(\d{4})", value.strip())
    if not match:
        return None
    return int(match.group(1))


def _looks_like_stale_year(text: str, *, source_year: int | None) -> bool:
    if source_year is None:
        return False
    match = re.search(r"(?:in|during)\s+(20\d{2})", text)
    if not match:
        return False
    year = int(match.group(1))
    return year < source_year - 1


def _required_str(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"pipeline asset field {key!r} must be a non-empty string")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional pipeline asset fields must be strings when set")
    value = value.strip()
    return value or None


def _str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, list):
        raise ValueError("aliases must be a string or list of strings")
    aliases: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("aliases must only contain strings")
        item = item.strip()
        if item:
            aliases.append(item)
    return tuple(aliases)


def _clinical_data_tuple(value: Any) -> tuple[ClinicalDataPoint, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        points: list[ClinicalDataPoint] = []
        for item in value:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    points.append(ClinicalDataPoint(metric="note", context=text))
                continue
            if not isinstance(item, dict):
                raise ValueError("clinical_data items must be strings or objects")
            metric = _required_str(item, "metric")
            sample_size = item.get("sample_size")
            if sample_size is not None and not isinstance(sample_size, int):
                raise ValueError("clinical_data.sample_size must be an integer")
            points.append(
                ClinicalDataPoint(
                    metric=metric,
                    value=_optional_str(item.get("value")),
                    unit=_optional_str(item.get("unit")),
                    sample_size=sample_size,
                    context=_optional_str(item.get("context")),
                )
            )
        return tuple(points)
    raise ValueError("clinical_data must be a list when set")
