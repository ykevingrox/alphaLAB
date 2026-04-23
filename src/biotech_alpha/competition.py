"""Competitive landscape inputs and deterministic matching."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from biotech_alpha.models import (
    AgentFinding,
    CompetitiveMatch,
    CompetitorAsset,
    Evidence,
    PipelineAsset,
)


@dataclass(frozen=True)
class CompetitionValidationReport:
    """Validation result for a curated competitor asset file."""

    competitor_count: int
    evidence_count: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def load_competitor_assets(path: str | Path) -> tuple[CompetitorAsset, ...]:
    """Load competitor assets from a local JSON file."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("competitors") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("competitor file must contain a list or competitors list")
    return tuple(_competitor_asset_from_dict(row) for row in rows)


def validate_competitor_file(path: str | Path) -> CompetitionValidationReport:
    """Validate a curated competitor asset file."""

    try:
        competitors = load_competitor_assets(path)
    except Exception as exc:  # noqa: BLE001 - report validation failures.
        return CompetitionValidationReport(
            competitor_count=0,
            evidence_count=0,
            errors=(str(exc),),
        )

    warnings: list[str] = []
    evidence_count = 0
    seen: set[tuple[str, str]] = set()
    for competitor in competitors:
        key = (
            _normalize_for_match(competitor.company),
            _normalize_for_match(competitor.asset_name),
        )
        if key in seen:
            warnings.append(
                f"{competitor.company} {competitor.asset_name}: duplicate competitor"
            )
        seen.add(key)
        if _looks_like_placeholder(competitor.company):
            warnings.append(f"{competitor.asset_name}: replace placeholder company")
        if _looks_like_placeholder(competitor.asset_name):
            warnings.append(f"{competitor.asset_name}: replace placeholder asset")
        if not competitor.target and not competitor.mechanism:
            warnings.append(f"{competitor.asset_name}: missing target or mechanism")
        if not competitor.indication:
            warnings.append(f"{competitor.asset_name}: missing indication")
        if not competitor.phase:
            warnings.append(f"{competitor.asset_name}: missing phase")
        if not competitor.evidence:
            warnings.append(f"{competitor.asset_name}: missing evidence")
        evidence_count += len(competitor.evidence)
        for evidence in competitor.evidence:
            if _looks_like_placeholder(evidence.source):
                warnings.append(
                    f"{competitor.asset_name}: replace placeholder evidence source"
                )
            if evidence.source_date == "YYYY-MM-DD":
                warnings.append(
                    f"{competitor.asset_name}: replace placeholder evidence date"
                )

    return CompetitionValidationReport(
        competitor_count=len(competitors),
        evidence_count=evidence_count,
        warnings=tuple(warnings),
    )


def competitor_template(company: str, ticker: str | None = None) -> dict[str, Any]:
    """Return a starter template for curated competitive landscape inputs."""

    company = company.strip()
    if not company:
        raise ValueError("company must not be empty")
    return {
        "company": company,
        "ticker": ticker,
        "competitors": [
            {
                "company": "Example competitor company",
                "asset_name": "Example competitor asset",
                "aliases": ["Example competitor code"],
                "target": "Example target",
                "mechanism": "Example mechanism",
                "indication": "Example indication",
                "phase": "Example phase",
                "geography": "Example geography",
                "differentiation": "Example differentiation note",
                "evidence": [
                    {
                        "claim": "Short source-backed competitor claim.",
                        "source": "competitor-source.pdf",
                        "source_date": "YYYY-MM-DD",
                        "confidence": 0.7,
                    }
                ],
            }
        ],
    }


def write_competitor_template(
    *,
    path: str | Path,
    company: str,
    ticker: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write a competitor input template to disk."""

    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            competitor_template(company=company, ticker=ticker),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def match_competitors_to_pipeline(
    assets: tuple[PipelineAsset, ...],
    competitors: tuple[CompetitorAsset, ...],
) -> tuple[CompetitiveMatch, ...]:
    """Match competitor assets to company assets by target and indication."""

    matches: list[CompetitiveMatch] = []
    for asset in assets:
        for competitor in competitors:
            match = _match_competitor(asset, competitor)
            if match:
                matches.append(match)
    return tuple(matches)


def competitive_landscape_finding(
    *,
    company: str,
    assets: tuple[PipelineAsset, ...],
    competitors: tuple[CompetitorAsset, ...],
    matches: tuple[CompetitiveMatch, ...],
) -> AgentFinding:
    """Convert competitive matches into an agent finding."""

    matched_assets = {match.asset_name for match in matches}
    crowded_assets = tuple(
        asset.name
        for asset in assets
        if sum(1 for match in matches if match.asset_name == asset.name) >= 3
    )
    risks = []
    if crowded_assets:
        risks.append("竞争拥挤领域：" + ", ".join(crowded_assets))
    if competitors and not matches:
        risks.append("竞品输入未与披露管线资产形成匹配")

    return AgentFinding(
        agent_name="competitive_landscape_agent",
        summary=(
            f"{company} 当前输入含 {len(competitors)} 条结构化竞品资产；"
            f"{len(matched_assets)} 条公司资产与 {len(matches)} 条竞品记录"
            "在靶点或适应症维度形成匹配。"
        ),
        risks=tuple(risks),
        evidence=tuple(
            Evidence(
                claim=(
                    f"{match.asset_name} 与竞品 {match.competitor_company} "
                    f"{match.competitor_asset} 在 {match.match_scope} 维度匹配。"
                ),
                source="curated_competitor_input",
                confidence=match.confidence,
                is_inferred=True,
            )
            for match in matches
        ),
        confidence=0.55 if matches else 0.25,
        needs_human_review=bool(risks) or bool(competitors),
    )


def competition_validation_report_as_dict(
    report: CompetitionValidationReport,
) -> dict[str, Any]:
    """Convert validation reports into JSON-serializable dictionaries."""

    return asdict(report)


def _match_competitor(
    asset: PipelineAsset,
    competitor: CompetitorAsset,
) -> CompetitiveMatch | None:
    target_match = _same_text(asset.target, competitor.target)
    indication_match = _same_text(asset.indication, competitor.indication)
    if target_match and indication_match:
        return CompetitiveMatch(
            asset_name=asset.name,
            competitor_company=competitor.company,
            competitor_asset=competitor.asset_name,
            match_scope="target_indication",
            confidence=0.8,
        )
    if target_match:
        return CompetitiveMatch(
            asset_name=asset.name,
            competitor_company=competitor.company,
            competitor_asset=competitor.asset_name,
            match_scope="target",
            confidence=0.55,
        )
    if indication_match:
        return CompetitiveMatch(
            asset_name=asset.name,
            competitor_company=competitor.company,
            competitor_asset=competitor.asset_name,
            match_scope="indication",
            confidence=0.4,
        )
    return None


def _competitor_asset_from_dict(row: Any) -> CompetitorAsset:
    if not isinstance(row, dict):
        raise ValueError("each competitor asset must be an object")
    return CompetitorAsset(
        company=_required_str(row, "company"),
        asset_name=_required_str(row, "asset_name"),
        aliases=_str_tuple(row.get("aliases")),
        target=_optional_str(row.get("target")),
        mechanism=_optional_str(row.get("mechanism")),
        indication=_optional_str(row.get("indication")),
        phase=_optional_str(row.get("phase")),
        geography=_optional_str(row.get("geography")),
        differentiation=_optional_str(row.get("differentiation")),
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


def _same_text(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return _normalize_for_match(left) == _normalize_for_match(right)


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
        or normalized == "competitor-source.pdf"
    )


def _required_str(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"competitor field {key!r} must be a non-empty string")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional competitor fields must be strings when set")
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
