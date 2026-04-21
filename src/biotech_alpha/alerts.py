"""Local alerting over saved single-company research runs."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SavedCatalystRun:
    """A saved research run with a catalyst calendar artifact."""

    company: str
    ticker: str | None
    market: str | None
    run_id: str
    retrieved_at: str | None
    manifest_json: str
    catalyst_calendar_csv: str


@dataclass(frozen=True)
class CatalystRecord:
    """Comparable catalyst row from a saved catalyst calendar CSV."""

    title: str
    category: str
    expected_date: str | None
    expected_window: str | None
    related_asset: str | None


@dataclass(frozen=True)
class CatalystAlert:
    """A deterministic catalyst calendar change alert."""

    company: str
    ticker: str | None
    market: str | None
    previous_run_id: str
    current_run_id: str
    change_type: str
    catalyst_key: str
    title: str
    related_asset: str | None
    previous_expected_date: str | None
    current_expected_date: str | None
    previous_expected_window: str | None
    current_expected_window: str | None
    previous_manifest_json: str
    current_manifest_json: str


CATALYST_ALERT_CSV_FIELDS = (
    "company",
    "ticker",
    "market",
    "previous_run_id",
    "current_run_id",
    "change_type",
    "catalyst_key",
    "title",
    "related_asset",
    "previous_expected_date",
    "current_expected_date",
    "previous_expected_window",
    "current_expected_window",
    "previous_manifest_json",
    "current_manifest_json",
)


def load_catalyst_runs(
    processed_dir: str | Path = "data/processed/single_company",
) -> tuple[SavedCatalystRun, ...]:
    """Load saved runs that have catalyst calendar artifacts."""

    root = Path(processed_dir)
    if not root.exists():
        return ()

    runs: list[SavedCatalystRun] = []
    for manifest_path in sorted(root.glob("**/*_manifest.json")):
        run = _run_from_manifest(manifest_path)
        if run:
            runs.append(run)
    return tuple(runs)


def latest_catalyst_run_pairs(
    runs: tuple[SavedCatalystRun, ...],
) -> tuple[tuple[SavedCatalystRun, SavedCatalystRun], ...]:
    """Return previous/current run pairs using the newest two runs per company."""

    grouped: dict[str, list[SavedCatalystRun]] = {}
    for run in runs:
        grouped.setdefault(_company_identity(run), []).append(run)

    pairs: list[tuple[SavedCatalystRun, SavedCatalystRun]] = []
    for group in grouped.values():
        sorted_group = sorted(group, key=_run_sort_key)
        if len(sorted_group) >= 2:
            pairs.append((sorted_group[-2], sorted_group[-1]))
    return tuple(sorted(pairs, key=lambda pair: _run_sort_key(pair[1])))


def build_catalyst_alerts(
    processed_dir: str | Path = "data/processed/single_company",
) -> tuple[CatalystAlert, ...]:
    """Compare latest run pairs and return catalyst calendar change alerts."""

    runs = load_catalyst_runs(processed_dir)
    alerts: list[CatalystAlert] = []
    for previous_run, current_run in latest_catalyst_run_pairs(runs):
        alerts.extend(compare_catalyst_runs(previous_run, current_run))
    return tuple(sorted(alerts, key=_alert_sort_key))


def compare_catalyst_runs(
    previous_run: SavedCatalystRun,
    current_run: SavedCatalystRun,
) -> tuple[CatalystAlert, ...]:
    """Compare two saved catalyst calendars."""

    previous = _catalyst_records_by_key(Path(previous_run.catalyst_calendar_csv))
    current = _catalyst_records_by_key(Path(current_run.catalyst_calendar_csv))
    alerts: list[CatalystAlert] = []

    for key in sorted(current.keys() - previous.keys()):
        alerts.append(
            _alert_from_records(
                previous_run=previous_run,
                current_run=current_run,
                change_type="added",
                key=key,
                previous=None,
                current=current[key],
            )
        )
    for key in sorted(previous.keys() - current.keys()):
        alerts.append(
            _alert_from_records(
                previous_run=previous_run,
                current_run=current_run,
                change_type="removed",
                key=key,
                previous=previous[key],
                current=None,
            )
        )
    for key in sorted(previous.keys() & current.keys()):
        previous_record = previous[key]
        current_record = current[key]
        change_type = _timing_change_type(previous_record, current_record)
        if change_type:
            alerts.append(
                _alert_from_records(
                    previous_run=previous_run,
                    current_run=current_run,
                    change_type=change_type,
                    key=key,
                    previous=previous_record,
                    current=current_record,
                )
            )
    return tuple(alerts)


def catalyst_alerts_as_dicts(
    alerts: tuple[CatalystAlert, ...],
) -> list[dict[str, Any]]:
    """Return JSON-serializable catalyst alerts."""

    return [asdict(alert) for alert in alerts]


def catalyst_alerts_to_csv_text(
    alerts: tuple[CatalystAlert, ...],
) -> str:
    """Render catalyst alerts as CSV text."""

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CATALYST_ALERT_CSV_FIELDS)
    writer.writeheader()
    for alert in catalyst_alerts_as_dicts(alerts):
        writer.writerow(_csv_row(alert))
    return output.getvalue()


def write_catalyst_alerts_csv(
    path: str | Path,
    alerts: tuple[CatalystAlert, ...],
) -> Path:
    """Write catalyst alerts as a CSV file."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        catalyst_alerts_to_csv_text(alerts),
        encoding="utf-8",
    )
    return output_path


def _run_from_manifest(manifest_path: Path) -> SavedCatalystRun | None:
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        return None

    artifacts = _dict_value(manifest.get("artifacts"))
    catalyst_path = _artifact_path(manifest_path, artifacts, "catalyst_calendar_csv")
    if not catalyst_path or not catalyst_path.exists():
        return None

    return SavedCatalystRun(
        company=_str_or_empty(manifest.get("company")),
        ticker=_optional_str(manifest.get("ticker")),
        market=_optional_str(manifest.get("market")),
        run_id=_str_or_empty(manifest.get("run_id")),
        retrieved_at=_optional_str(manifest.get("retrieved_at")),
        manifest_json=str(manifest_path),
        catalyst_calendar_csv=str(catalyst_path),
    )


def _catalyst_records_by_key(path: Path) -> dict[str, CatalystRecord]:
    try:
        rows = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    records: dict[str, CatalystRecord] = {}
    for row in csv.DictReader(io.StringIO(rows)):
        title = _cell(row.get("title"))
        if not title:
            continue
        record = CatalystRecord(
            title=title,
            category=_cell(row.get("category")) or "unknown",
            expected_date=_cell(row.get("expected_date")),
            expected_window=_cell(row.get("expected_window")),
            related_asset=_cell(row.get("related_asset")),
        )
        records[_catalyst_key(record)] = record
    return records


def _alert_from_records(
    *,
    previous_run: SavedCatalystRun,
    current_run: SavedCatalystRun,
    change_type: str,
    key: str,
    previous: CatalystRecord | None,
    current: CatalystRecord | None,
) -> CatalystAlert:
    record = current or previous
    if record is None:
        raise ValueError("previous or current catalyst record is required")

    return CatalystAlert(
        company=current_run.company or previous_run.company,
        ticker=current_run.ticker or previous_run.ticker,
        market=current_run.market or previous_run.market,
        previous_run_id=previous_run.run_id,
        current_run_id=current_run.run_id,
        change_type=change_type,
        catalyst_key=key,
        title=record.title,
        related_asset=record.related_asset,
        previous_expected_date=previous.expected_date if previous else None,
        current_expected_date=current.expected_date if current else None,
        previous_expected_window=previous.expected_window if previous else None,
        current_expected_window=current.expected_window if current else None,
        previous_manifest_json=previous_run.manifest_json,
        current_manifest_json=current_run.manifest_json,
    )


def _timing_change_type(
    previous: CatalystRecord,
    current: CatalystRecord,
) -> str | None:
    date_changed = previous.expected_date != current.expected_date
    window_changed = previous.expected_window != current.expected_window
    if date_changed and window_changed:
        return "timing_changed"
    if date_changed:
        return "date_changed"
    if window_changed:
        return "window_changed"
    return None


def _catalyst_key(record: CatalystRecord) -> str:
    return "|".join(
        (
            _normalize_group_value(record.category),
            _normalize_group_value(record.related_asset or ""),
            _normalize_group_value(record.title),
        )
    )


def _alert_sort_key(alert: CatalystAlert) -> tuple[str, str, str, str]:
    return (
        _normalize_group_value(alert.company),
        alert.current_run_id,
        alert.change_type,
        alert.catalyst_key,
    )


def _company_identity(run: SavedCatalystRun) -> str:
    return _normalize_group_value(run.ticker or run.company)


def _run_sort_key(run: SavedCatalystRun) -> tuple[str, str, str]:
    return (run.retrieved_at or "", run.run_id, run.manifest_json)


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


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _csv_row(row: dict[str, Any]) -> dict[str, Any]:
    csv_row = dict(row)
    for key, value in list(csv_row.items()):
        if value is None:
            csv_row[key] = ""
    return csv_row


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _cell(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _normalize_group_value(value: str) -> str:
    return " ".join(value.casefold().split())
