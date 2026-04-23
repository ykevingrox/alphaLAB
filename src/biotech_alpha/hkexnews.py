"""HKEXnews RSS parsing and change tracking utilities."""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class HkexNewsItem:
    title: str
    link: str
    guid: str
    published_at: str | None
    category: str | None = None


def fetch_hkex_rss(url: str, *, timeout: int = 8) -> str:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - user-driven fetch utility
        return response.read().decode("utf-8", errors="replace")


def parse_hkex_rss(xml_text: str) -> tuple[HkexNewsItem, ...]:
    root = ET.fromstring(xml_text)
    items: list[HkexNewsItem] = []
    for node in root.findall("./channel/item"):
        title = _node_text(node, "title")
        link = _node_text(node, "link")
        guid = _node_text(node, "guid") or link or title
        published_raw = _node_text(node, "pubDate")
        items.append(
            HkexNewsItem(
                title=title,
                link=link,
                guid=guid,
                published_at=_normalize_pubdate(published_raw),
                category=_node_text(node, "category") or None,
            )
        )
    ordered = sorted(
        items,
        key=lambda row: row.published_at or "",
        reverse=True,
    )
    return tuple(ordered)


def track_hkex_news_updates(
    *,
    items: tuple[HkexNewsItem, ...],
    state_path: str | Path,
) -> dict[str, Any]:
    seen_ids = _load_seen_ids(state_path)
    new_items = [item for item in items if item.guid not in seen_ids]
    merged = set(seen_ids)
    merged.update(item.guid for item in items)
    _save_seen_ids(state_path, merged)
    return {
        "item_count": len(items),
        "new_count": len(new_items),
        "new_items": [asdict(item) for item in new_items],
        "typed_new_items": [typed_hkex_item_dict(item) for item in new_items],
        "state_path": str(state_path),
    }


def typed_hkex_item_dict(item: HkexNewsItem) -> dict[str, Any]:
    payload = asdict(item)
    payload["event_type"] = classify_hkex_item(item)
    payload["needs_human_review"] = True
    return payload


def classify_hkex_item(item: HkexNewsItem) -> str:
    text = f"{item.title} {item.category or ''}".casefold()
    if any(token in text for token in ("trial", "clinical", "phase", "asco", "esmo")):
        return "clinical"
    if any(token in text for token in ("ind", "nda", "bla", "approval", "accepted")):
        return "regulatory"
    if any(
        token in text
        for token in ("placing", "subscription", "convertible", "financing", "monthly return")
    ):
        return "financing"
    return "corporate"


def typed_items_to_catalyst_rows(
    typed_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in typed_items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        event_type = str(item.get("event_type") or "corporate")
        published = _date_part(item.get("published_at"))
        rows.append(
            {
                "title": f"HKEXnews: {title}",
                "category": _event_type_to_catalyst_category(event_type),
                "expected_date": published,
                "expected_window": "reported",
                "related_asset": None,
                "confidence": 0.25,
                "evidence_count": 1,
            }
        )
    return rows


def typed_items_to_event_impact_suggestions(
    typed_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for item in typed_items:
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        event_type = str(item.get("event_type") or "corporate")
        base = {
            "event_type": f"hkex_{event_type}",
            "asset_name": "to_verify",
            "probability_of_success_delta": 0.0,
            "peak_sales_delta_pct": 0.0,
            "launch_year_delta": 0,
            "discount_rate_delta": 0.0,
            "rationale": f"HKEXnews-derived suggestion: {title}",
            "needs_human_review": True,
        }
        text = f"{title} {item.get('category') or ''}".casefold()
        if event_type == "regulatory":
            base["probability_of_success_delta"] = 0.05
            base["discount_rate_delta"] = -0.01
        elif event_type == "clinical":
            base["probability_of_success_delta"] = 0.03
        elif event_type == "financing":
            base["discount_rate_delta"] = 0.01
        if any(
            token in text
            for token in ("license", "licence", "collaboration", "partnership")
        ):
            base["peak_sales_delta_pct"] = 0.05
            base["event_type"] = "hkex_license_bd"
        suggestions.append(base)
    return suggestions


def suggest_expected_dilution_pct(
    *,
    typed_items: list[dict[str, Any]],
    current_expected_dilution_pct: float | None,
) -> dict[str, Any]:
    financing_count = sum(
        1 for item in typed_items if str(item.get("event_type")) == "financing"
    )
    baseline = current_expected_dilution_pct or 0.0
    step_up = min(financing_count * 0.02, 0.1)
    suggested = round(max(baseline, baseline + step_up), 4)
    return {
        "current_expected_dilution_pct": baseline,
        "suggested_expected_dilution_pct": suggested,
        "financing_signal_count": financing_count,
        "needs_human_review": True,
        "rationale": (
            "HKEX financing-class announcements can imply additional equity "
            "issuance risk; suggestion is deterministic and conservative."
        ),
    }


def filter_hkex_items_by_ticker(
    items: tuple[HkexNewsItem, ...],
    *,
    ticker: str | None,
) -> tuple[HkexNewsItem, ...]:
    if not ticker:
        return items
    normalized = "".join(ch for ch in ticker if ch.isdigit())
    if not normalized:
        return items
    return tuple(
        item
        for item in items
        if normalized in item.title or normalized in item.link or normalized in item.guid
    )


def _event_type_to_catalyst_category(event_type: str) -> str:
    return {
        "clinical": "clinical",
        "regulatory": "regulatory",
        "financing": "financial",
        "corporate": "corporate",
    }.get(event_type, "corporate")


def _date_part(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        return None


def _node_text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return " ".join(child.text.split())


def _normalize_pubdate(value: str) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(value).isoformat()
        except ValueError:
            return None


def _load_seen_ids(path: str | Path) -> set[str]:
    state_path = Path(path)
    if not state_path.exists():
        return set()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    rows = payload.get("seen_guids")
    if not isinstance(rows, list):
        return set()
    return {row for row in rows if isinstance(row, str) and row.strip()}


def _save_seen_ids(path: str | Path, seen_ids: set[str]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"seen_guids": sorted(seen_ids)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
