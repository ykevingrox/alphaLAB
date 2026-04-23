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
        "state_path": str(state_path),
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
