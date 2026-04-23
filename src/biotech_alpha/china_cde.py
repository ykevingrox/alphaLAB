"""China CDE feed parsing and change tracking utilities."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class CdeItem:
    title: str
    link: str
    guid: str
    published_at: str | None
    category: str | None = None


def fetch_cde_feed(url: str, *, timeout: int = 8) -> str:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def parse_cde_feed(xml_text: str) -> tuple[CdeItem, ...]:
    root = ET.fromstring(xml_text)
    items: list[CdeItem] = []
    for node in root.findall(".//item"):
        title = _node_text(node, "title")
        link = _node_text(node, "link")
        guid = _node_text(node, "guid") or link or title
        published_raw = _node_text(node, "pubDate")
        items.append(
            CdeItem(
                title=title,
                link=link,
                guid=guid,
                published_at=_normalize_pubdate(published_raw),
                category=_node_text(node, "category") or None,
            )
        )
    ordered = sorted(items, key=lambda row: row.published_at or "", reverse=True)
    return tuple(ordered)


def filter_cde_items(
    items: tuple[CdeItem, ...],
    *,
    query: str | None,
) -> tuple[CdeItem, ...]:
    if not query:
        return items
    text = query.casefold().strip()
    if not text:
        return items
    return tuple(
        item
        for item in items
        if text in item.title.casefold()
        or text in item.link.casefold()
        or text in item.guid.casefold()
    )


def classify_cde_item(item: CdeItem) -> str:
    text = f"{item.title} {item.category or ''}".casefold()
    if any(token in text for token in ("临床", "clinical", "phase", "试验")):
        return "clinical"
    if any(token in text for token in ("受理", "批准", "审批", "nda", "bla", "ind")):
        return "regulatory"
    if any(token in text for token in ("补充", "问询", "整改", "核查")):
        return "review"
    return "other"


def track_cde_updates(
    *,
    items: tuple[CdeItem, ...],
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
        "typed_new_items": [typed_cde_item_dict(item) for item in new_items],
        "state_path": str(state_path),
    }


def typed_cde_item_dict(item: CdeItem) -> dict[str, Any]:
    payload = asdict(item)
    payload["event_type"] = classify_cde_item(item)
    payload["needs_human_review"] = True
    return payload


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
