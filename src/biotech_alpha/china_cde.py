"""China CDE feed parsing and change tracking utilities."""

from __future__ import annotations

import json
import re
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


@dataclass(frozen=True)
class CdeTrialRecord:
    title: str
    company: str | None
    application_no: str | None
    phase: str | None
    indication: str | None
    status: str
    event_type: str
    source_link: str
    published_at: str | None
    confidence: float
    needs_human_review: bool = True


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
        "normalized_new_records": [
            asdict(record)
            for record in normalize_cde_trial_records(
                [typed_cde_item_dict(item) for item in new_items]
            )
        ],
        "state_path": str(state_path),
    }


def typed_cde_item_dict(item: CdeItem) -> dict[str, Any]:
    payload = asdict(item)
    payload["event_type"] = classify_cde_item(item)
    payload["needs_human_review"] = True
    return payload


def normalize_cde_trial_records(
    typed_items: list[dict[str, Any]],
) -> tuple[CdeTrialRecord, ...]:
    rows: list[CdeTrialRecord] = []
    for row in typed_items:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        status = _status_from_text(title)
        event_type = str(row.get("event_type") or "other")
        app_no = _application_no(title)
        company = _company_from_title(title)
        phase = _phase_from_text(title)
        indication = _indication_from_text(title)
        confidence = 0.4
        if app_no:
            confidence += 0.2
        if phase:
            confidence += 0.1
        if indication:
            confidence += 0.1
        rows.append(
            CdeTrialRecord(
                title=title,
                company=company,
                application_no=app_no,
                phase=phase,
                indication=indication,
                status=status,
                event_type=event_type,
                source_link=str(row.get("link") or ""),
                published_at=row.get("published_at"),
                confidence=min(confidence, 0.85),
            )
        )
    return tuple(rows)


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


def _application_no(text: str) -> str | None:
    match = re.search(r"\b(CX[HS][A-Z]?\d{5,})\b", text, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def _phase_from_text(text: str) -> str | None:
    lowered = text.casefold()
    if "iii" in lowered or "phase 3" in lowered or "Ⅲ期" in text:
        return "Phase 3"
    if "ii" in lowered or "phase 2" in lowered or "Ⅱ期" in text:
        return "Phase 2"
    if "phase 1" in lowered or "i期" in text or "Ⅰ期" in text:
        return "Phase 1"
    return None


def _indication_from_text(text: str) -> str | None:
    match = re.search(r"(用于|治疗|适应症为)([^，。;；]{2,30})", text)
    if not match:
        return None
    return match.group(2).strip()


def _company_from_title(text: str) -> str | None:
    cleaned = text.strip()
    if not cleaned:
        return None
    parts = re.split(r"[：: \-]", cleaned, maxsplit=1)
    first = parts[0].strip()
    return first if len(first) >= 2 else None


def _status_from_text(text: str) -> str:
    if "受理" in text:
        return "accepted"
    if "批准" in text:
        return "approved"
    if any(token in text for token in ("补充", "问询", "核查", "整改")):
        return "under_review"
    return "other"
