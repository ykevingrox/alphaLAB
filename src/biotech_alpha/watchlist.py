"""Local watchlist ranking over saved single-company research runs."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WatchlistEntry:
    """One ranked row loaded from a saved research run."""

    company: str
    ticker: str | None
    market: str | None
    run_id: str
    retrieved_at: str | None
    watchlist_score: float
    watchlist_bucket: str
    needs_human_review: bool
    input_warning_count: int
    trial_count: int
    pipeline_asset_count: int
    asset_trial_match_count: int
    competitor_asset_count: int
    competitive_match_count: int
    catalyst_count: int
    cash_runway_months: float | None
    enterprise_value: float | None
    revenue_multiple: float | None
    targets: tuple[str, ...]
    indications: tuple[str, ...]
    monitoring_rules: tuple[str, ...]
    memo_markdown: str | None
    manifest_json: str


@dataclass(frozen=True)
class PortfolioGuardrail:
    """Conservative research-only position and concentration guardrail."""

    sizing_tier: str
    research_position_limit_pct: float
    company_concentration_count: int
    market_concentration_count: int
    target_concentration_count: int
    indication_concentration_count: int
    guardrail_flags: tuple[str, ...]


WATCHLIST_CSV_FIELDS = (
    "rank",
    "company",
    "ticker",
    "market",
    "run_id",
    "retrieved_at",
    "watchlist_score",
    "watchlist_bucket",
    "sizing_tier",
    "research_position_limit_pct",
    "needs_human_review",
    "input_warning_count",
    "trial_count",
    "pipeline_asset_count",
    "asset_trial_match_count",
    "competitor_asset_count",
    "competitive_match_count",
    "catalyst_count",
    "cash_runway_months",
    "enterprise_value",
    "revenue_multiple",
    "company_concentration_count",
    "market_concentration_count",
    "target_concentration_count",
    "indication_concentration_count",
    "targets",
    "indications",
    "guardrail_flags",
    "monitoring_rules",
    "memo_markdown",
    "manifest_json",
)


def load_watchlist_entries(
    processed_dir: str | Path = "data/processed/single_company",
) -> tuple[WatchlistEntry, ...]:
    """Load watchlist entries from saved single-company run manifests."""

    root = Path(processed_dir)
    if not root.exists():
        return ()

    entries: list[WatchlistEntry] = []
    for manifest_path in sorted(root.glob("**/*_manifest.json")):
        entry = _entry_from_manifest(manifest_path)
        if entry:
            entries.append(entry)
    return tuple(entries)


def rank_watchlist_entries(
    entries: tuple[WatchlistEntry, ...],
) -> tuple[WatchlistEntry, ...]:
    """Sort watchlist entries by descending score and stable tie breakers."""

    return tuple(
        sorted(
            entries,
            key=lambda entry: (
                -entry.watchlist_score,
                entry.company.casefold(),
                entry.run_id,
            ),
        )
    )


def latest_watchlist_entries(
    entries: tuple[WatchlistEntry, ...],
) -> tuple[WatchlistEntry, ...]:
    """Keep the newest saved run for each company or ticker identity."""

    latest_by_identity: dict[str, WatchlistEntry] = {}
    for entry in entries:
        identity = _company_identity(entry)
        current = latest_by_identity.get(identity)
        if current is None or _run_sort_key(entry) > _run_sort_key(current):
            latest_by_identity[identity] = entry
    return tuple(latest_by_identity.values())


def watchlist_entries_as_dicts(
    entries: tuple[WatchlistEntry, ...],
) -> list[dict[str, Any]]:
    """Return JSON-serializable ranked watchlist rows."""

    company_counts = _company_counts(entries)
    market_counts = _optional_value_counts(entry.market for entry in entries)
    target_counts = _concentration_counts(entries, "targets")
    indication_counts = _concentration_counts(entries, "indications")
    return [
        {
            "rank": index,
            **asdict(entry),
            **asdict(
                build_portfolio_guardrail(
                    entry,
                    company_counts=company_counts,
                    market_counts=market_counts,
                    target_counts=target_counts,
                    indication_counts=indication_counts,
                )
            ),
            "targets": list(entry.targets),
            "indications": list(entry.indications),
            "monitoring_rules": list(entry.monitoring_rules),
        }
        for index, entry in enumerate(entries, start=1)
    ]


def build_portfolio_guardrail(
    entry: WatchlistEntry,
    *,
    company_counts: dict[str, int] | None = None,
    market_counts: dict[str, int] | None = None,
    target_counts: dict[str, int] | None = None,
    indication_counts: dict[str, int] | None = None,
) -> PortfolioGuardrail:
    """Build conservative research-only position and concentration guardrails."""

    limit = _base_position_limit(entry.watchlist_score)
    flags: list[str] = []

    if entry.needs_human_review:
        limit = min(limit, 0.5)
        flags.append("human_review_required")
    if entry.input_warning_count:
        limit = min(limit, 0.5)
        flags.append("input_validation_warnings")
    if entry.trial_count == 0:
        limit = 0.0
        flags.append("no_registry_trials")
    if entry.pipeline_asset_count == 0:
        limit = 0.0
        flags.append("no_curated_pipeline")
    if entry.competitor_asset_count == 0:
        limit = min(limit, 0.5)
        flags.append("competitor_set_missing")
    if entry.cash_runway_months is None:
        limit = min(limit, 0.5)
        flags.append("cash_runway_missing")
    elif entry.cash_runway_months < 12:
        limit = 0.0
        flags.append("cash_runway_below_12_months")
    elif entry.cash_runway_months < 24:
        limit = min(limit, 0.5)
        flags.append("cash_runway_below_24_months")
    if entry.revenue_multiple is None:
        limit = min(limit, 1.0)
        flags.append("valuation_multiple_missing")
    elif entry.revenue_multiple > 20:
        limit = min(limit, 0.5)
        flags.append("high_revenue_multiple")

    company_count = (company_counts or {}).get(_company_identity(entry), 0)
    market_count = 0
    if entry.market:
        market_count = (market_counts or {}).get(
            _normalize_group_value(entry.market),
            0,
        )
    if company_count >= 2:
        limit = min(limit, 1.0)
        flags.append("multiple_company_runs")
    if market_count >= 5:
        limit = min(limit, 1.0)
        flags.append("market_concentration")

    target_count = _max_group_count(entry.targets, target_counts or {})
    indication_count = _max_group_count(entry.indications, indication_counts or {})
    if target_count >= 3:
        limit = min(limit, 1.0)
        flags.append("target_concentration")
    if indication_count >= 3:
        limit = min(limit, 1.0)
        flags.append("indication_concentration")

    return PortfolioGuardrail(
        sizing_tier=_sizing_tier(limit),
        research_position_limit_pct=round(limit, 2),
        company_concentration_count=company_count,
        market_concentration_count=market_count,
        target_concentration_count=target_count,
        indication_concentration_count=indication_count,
        guardrail_flags=tuple(flags),
    )


def watchlist_entries_to_csv_text(
    entries: tuple[WatchlistEntry, ...],
) -> str:
    """Render ranked watchlist rows as CSV text."""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=WATCHLIST_CSV_FIELDS)
    writer.writeheader()
    for row in watchlist_entries_as_dicts(entries):
        writer.writerow(_csv_row(row))
    return output.getvalue()


def write_watchlist_csv(
    path: str | Path,
    entries: tuple[WatchlistEntry, ...],
) -> Path:
    """Write ranked watchlist rows as a CSV file."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        watchlist_entries_to_csv_text(entries),
        encoding="utf-8",
    )
    return output_path


def _entry_from_manifest(manifest_path: Path) -> WatchlistEntry | None:
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        return None

    artifacts = _dict_value(manifest.get("artifacts"))
    scorecard_path = _artifact_path(manifest_path, artifacts, "scorecard")
    if not scorecard_path:
        return None
    scorecard = _read_json(scorecard_path)
    if not isinstance(scorecard, dict):
        return None

    score = _number_or_none(scorecard.get("total_score"))
    bucket = scorecard.get("bucket")
    if score is None or not isinstance(bucket, str):
        return None

    counts = _dict_value(manifest.get("counts"))
    cash_payload = _read_optional_artifact(manifest_path, artifacts, "cash_runway")
    pipeline_payload = _read_optional_artifact(
        manifest_path,
        artifacts,
        "pipeline_assets",
    )
    valuation_payload = _read_optional_artifact(manifest_path, artifacts, "valuation")

    return WatchlistEntry(
        company=_str_or_empty(manifest.get("company")),
        ticker=_optional_str(manifest.get("ticker")),
        market=_optional_str(manifest.get("market")),
        run_id=_str_or_empty(manifest.get("run_id")),
        retrieved_at=_optional_str(manifest.get("retrieved_at")),
        watchlist_score=score,
        watchlist_bucket=bucket,
        needs_human_review=bool(scorecard.get("needs_human_review")),
        input_warning_count=_input_warning_count(manifest.get("input_validation")),
        trial_count=_int_count(counts, "trials"),
        pipeline_asset_count=_int_count(counts, "pipeline_assets"),
        asset_trial_match_count=_int_count(counts, "asset_trial_matches"),
        competitor_asset_count=_int_count(counts, "competitor_assets"),
        competitive_match_count=_int_count(counts, "competitive_matches"),
        catalyst_count=_int_count(counts, "catalysts"),
        cash_runway_months=_nested_number(cash_payload, "estimate", "runway_months"),
        enterprise_value=_nested_number(
            valuation_payload,
            "metrics",
            "enterprise_value",
        ),
        revenue_multiple=_nested_number(
            valuation_payload,
            "metrics",
            "revenue_multiple",
        ),
        targets=_asset_field_values(pipeline_payload, "target"),
        indications=_asset_field_values(pipeline_payload, "indication"),
        monitoring_rules=_string_tuple(scorecard.get("monitoring_rules")),
        memo_markdown=_artifact_str(manifest_path, artifacts, "memo_markdown"),
        manifest_json=str(manifest_path),
    )


def _artifact_path(
    manifest_path: Path,
    artifacts: dict[str, Any],
    key: str,
) -> Path | None:
    value = artifacts.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value)
    if path.is_absolute() or path.exists():
        return path

    sibling = manifest_path.parent / path.name
    if sibling.exists():
        return sibling

    nearby = manifest_path.parent / path
    if nearby.exists():
        return nearby
    return path


def _artifact_str(
    manifest_path: Path,
    artifacts: dict[str, Any],
    key: str,
) -> str | None:
    path = _artifact_path(manifest_path, artifacts, key)
    return str(path) if path else None


def _read_optional_artifact(
    manifest_path: Path,
    artifacts: dict[str, Any],
    key: str,
) -> dict[str, Any] | None:
    path = _artifact_path(manifest_path, artifacts, key)
    if not path or not path.exists():
        return None
    payload = _read_json(path)
    return payload if isinstance(payload, dict) else None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _csv_row(row: dict[str, Any]) -> dict[str, Any]:
    csv_row = dict(row)
    csv_row["monitoring_rules"] = "; ".join(row.get("monitoring_rules") or [])
    csv_row["guardrail_flags"] = "; ".join(row.get("guardrail_flags") or [])
    csv_row["targets"] = "; ".join(row.get("targets") or [])
    csv_row["indications"] = "; ".join(row.get("indications") or [])
    for key, value in list(csv_row.items()):
        if value is None:
            csv_row[key] = ""
    return csv_row


def _company_counts(entries: tuple[WatchlistEntry, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        identity = _company_identity(entry)
        counts[identity] = counts.get(identity, 0) + 1
    return counts


def _company_identity(entry: WatchlistEntry) -> str:
    value = entry.ticker or entry.company
    return _normalize_group_value(value)


def _run_sort_key(entry: WatchlistEntry) -> tuple[str, str, str]:
    return (entry.retrieved_at or "", entry.run_id, entry.manifest_json)


def _base_position_limit(score: float) -> float:
    if score >= 75:
        return 2.0
    if score >= 55:
        return 1.0
    if score >= 35:
        return 0.5
    return 0.0


def _sizing_tier(limit: float) -> str:
    if limit >= 2:
        return "deep_dive_cap"
    if limit >= 1:
        return "watchlist_cap"
    if limit > 0:
        return "starter_cap"
    return "research_only"


def _concentration_counts(
    entries: tuple[WatchlistEntry, ...],
    field_name: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        values = getattr(entry, field_name)
        for value in set(values):
            key = _normalize_group_value(value)
            if key:
                counts[key] = counts.get(key, 0) + 1
    return counts


def _optional_value_counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        key = _normalize_group_value(value)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _max_group_count(values: tuple[str, ...], counts: dict[str, int]) -> int:
    max_count = 0
    for value in values:
        key = _normalize_group_value(value)
        max_count = max(max_count, counts.get(key, 0))
    return max_count


def _asset_field_values(
    payload: dict[str, Any] | None,
    field_name: str,
) -> tuple[str, ...]:
    if not isinstance(payload, dict):
        return ()
    assets = payload.get("assets")
    if not isinstance(assets, list):
        return ()

    values: list[str] = []
    seen: set[str] = set()
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        value = asset.get(field_name)
        if not isinstance(value, str) or not value.strip():
            continue
        normalized = _normalize_group_value(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            values.append(value.strip())
    return tuple(values)


def _normalize_group_value(value: str) -> str:
    return " ".join(value.casefold().split())


def _input_warning_count(input_validation: Any) -> int:
    reports = _dict_value(input_validation)
    count = 0
    for report in reports.values():
        warnings = report.get("warnings", []) if isinstance(report, dict) else []
        count += len(warnings) if isinstance(warnings, list) else 0
    return count


def _nested_number(
    payload: dict[str, Any] | None,
    section: str,
    key: str,
) -> float | None:
    if not isinstance(payload, dict):
        return None
    section_payload = payload.get(section)
    if not isinstance(section_payload, dict):
        return None
    return _number_or_none(section_payload.get(key))


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _int_count(counts: dict[str, Any], key: str) -> int:
    value = counts.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))
