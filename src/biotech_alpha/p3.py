"""Sprint-3 strategic utilities (deterministic baseline)."""

from __future__ import annotations

import csv
import difflib
import html
import json
import math
from pathlib import Path
from typing import Any


def technical_timing_from_ohlcv(path: str | Path) -> dict[str, Any]:
    rows = _load_ohlcv_rows(path)
    closes = [row["close"] for row in rows]
    sma20 = _sma(closes, 20)
    sma60 = _sma(closes, 60)
    rsi14 = _rsi(closes, 14)
    volatility20 = _volatility(closes, 20)
    trend = "sideways"
    if sma20 is not None and sma60 is not None:
        if sma20 > sma60:
            trend = "uptrend"
        elif sma20 < sma60:
            trend = "downtrend"
    support = min(closes[-20:]) if len(closes) >= 20 else min(closes)
    resistance = max(closes[-20:]) if len(closes) >= 20 else max(closes)
    return {
        "trend_state": trend,
        "support": round(support, 4),
        "resistance": round(resistance, 4),
        "sma20": _rounded_or_none(sma20),
        "sma60": _rounded_or_none(sma60),
        "rsi14": _rounded_or_none(rsi14),
        "volatility20": _rounded_or_none(volatility20),
        "confidence": 0.35,
        "needs_human_review": True,
        "guidance_type": "research_only",
        "notes": (
            "Deterministic technical timing baseline from OHLCV.",
            "Use as research support only; not a trading instruction.",
        ),
    }


def historical_memo_diff(previous_path: str | Path, current_path: str | Path) -> dict[str, Any]:
    previous = Path(previous_path).read_text(encoding="utf-8").splitlines()
    current = Path(current_path).read_text(encoding="utf-8").splitlines()
    diff_lines = list(
        difflib.unified_diff(
            previous,
            current,
            fromfile=str(previous_path),
            tofile=str(current_path),
            lineterm="",
        )
    )
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    return {
        "previous_path": str(previous_path),
        "current_path": str(current_path),
        "line_added": added,
        "line_removed": removed,
        "has_changes": bool(added or removed),
        "diff": diff_lines,
        "needs_human_review": True,
    }


def bilingual_memo_markdown(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    zh_lines = [_translate_line(line) for line in lines]
    return "\n".join(
        [
            "## Bilingual Memo",
            "",
            "### English",
            "",
            markdown_text.rstrip(),
            "",
            "### 中文（机器草稿，需人工复核）",
            "",
            "\n".join(zh_lines).rstrip(),
            "",
        ]
    )


def memo_markdown_to_html(
    markdown_text: str,
    *,
    title: str = "Biotech Alpha Memo",
    pipeline_assets_path: str | Path | None = None,
    catalyst_csv_path: str | Path | None = None,
    target_price_json_path: str | Path | None = None,
) -> str:
    body: list[str] = []
    for raw in markdown_text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if line.startswith("### "):
            body.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("- "):
            body.append(f"<li>{html.escape(line[2:])}</li>")
        else:
            body.append(f"<p>{html.escape(line)}</p>")
    joined = "\n".join(body).replace("</li>\n<li>", "</li><li>")
    charts = _build_chart_html(
        pipeline_assets_path=pipeline_assets_path,
        catalyst_csv_path=catalyst_csv_path,
        target_price_json_path=target_price_json_path,
    )
    return (
        "<html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "</head><body>"
        f"{joined}"
        f"{charts}"
        "</body></html>\n"
    )


def export_html(
    markdown_path: str | Path,
    output_path: str | Path,
    *,
    pipeline_assets_path: str | Path | None = None,
    catalyst_csv_path: str | Path | None = None,
    target_price_json_path: str | Path | None = None,
) -> Path:
    text = Path(markdown_path).read_text(encoding="utf-8")
    html_text = memo_markdown_to_html(
        text,
        title=Path(markdown_path).stem,
        pipeline_assets_path=pipeline_assets_path,
        catalyst_csv_path=catalyst_csv_path,
        target_price_json_path=target_price_json_path,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    return path


def export_pdf(markdown_path: str | Path, output_path: str | Path) -> tuple[Path | None, str | None]:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        return None, "reportlab is not installed; pdf export skipped."
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 810
    for line in Path(markdown_path).read_text(encoding="utf-8").splitlines():
        c.drawString(40, y, line[:110])
        y -= 14
        if y < 40:
            c.showPage()
            y = 810
    c.save()
    return path, None


def _load_ohlcv_rows(path: str | Path) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            close = _num(row.get("close"))
            if close is None or close <= 0:
                continue
            rows.append({"close": close})
    if len(rows) < 20:
        raise ValueError("OHLCV rows with valid close price must be >= 20")
    return rows


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def _rsi(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    gains = 0.0
    losses = 0.0
    for idx in range(len(values) - period, len(values)):
        diff = values[idx] - values[idx - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100 - (100 / (1 + rs))


def _volatility(values: list[float], period: int) -> float | None:
    if len(values) <= period:
        return None
    returns: list[float] = []
    start = len(values) - period
    for idx in range(start, len(values)):
        prev = values[idx - 1]
        if prev <= 0:
            continue
        returns.append((values[idx] / prev) - 1)
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return variance ** 0.5


def _rounded_or_none(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


_LINE_MAP = {
    "## Investment Committee Memo": "## 投委会备忘录",
    "## Core Asset Deep Dive": "## 核心资产深度拆解",
    "## Catalyst Roadmap": "## 催化剂路线图",
    "## Key Risks": "## 关键风险",
    "## Next Actions": "## 后续动作",
}


def _translate_line(line: str) -> str:
    mapped = _LINE_MAP.get(line.strip())
    if mapped is not None:
        return mapped
    if line.startswith("- "):
        return f"- 待人工翻译: {line[2:]}"
    if line.startswith("#"):
        return line
    return f"待人工翻译: {line}" if line else line


def _build_chart_html(
    *,
    pipeline_assets_path: str | Path | None,
    catalyst_csv_path: str | Path | None,
    target_price_json_path: str | Path | None,
) -> str:
    sections: list[str] = []
    if pipeline_assets_path:
        sections.append(_pipeline_gantt_svg(pipeline_assets_path))
    if catalyst_csv_path:
        sections.append(_catalyst_timeline_svg(catalyst_csv_path))
    if target_price_json_path:
        sections.append(_rnpv_stack_svg(target_price_json_path))
    if not sections:
        return ""
    return (
        "<h2>Charts (Review-Gated)</h2>"
        "<p>Deterministic chart draft for analyst review.</p>"
        + "".join(sections)
    )


def _pipeline_gantt_svg(path: str | Path) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assets = payload.get("assets") if isinstance(payload, dict) else []
    rows = assets if isinstance(assets, list) else []
    width = 700
    row_h = 26
    height = max(80, 40 + len(rows) * row_h)
    bars: list[str] = []
    for idx, item in enumerate(rows[:12]):
        if not isinstance(item, dict):
            continue
        phase = str(item.get("phase") or "unknown").casefold()
        x = 120 + _phase_rank(phase) * 80
        y = 20 + idx * row_h
        name = html.escape(str(item.get("name") or "asset"))
        bars.append(
            f"<text x='10' y='{y + 14}' font-size='11'>{name}</text>"
            f"<rect x='{x}' y='{y}' width='70' height='14' fill='#4f46e5'></rect>"
        )
    return (
        "<h3>Pipeline Gantt</h3>"
        f"<svg id='pipeline-gantt' width='{width}' height='{height}' "
        "xmlns='http://www.w3.org/2000/svg'>"
        + "".join(bars)
        + "</svg>"
    )


def _phase_rank(phase: str) -> int:
    if "phase 3" in phase or "phase iii" in phase:
        return 4
    if "phase 2" in phase or "phase ii" in phase:
        return 3
    if "phase 1" in phase or "phase i" in phase:
        return 2
    if "ind" in phase:
        return 1
    return 0


def _catalyst_timeline_svg(path: str | Path) -> str:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    width = 700
    y = 22
    points: list[str] = []
    for idx, row in enumerate(rows[:15]):
        title = html.escape(str(row.get("title") or "catalyst"))
        x = 30 + idx * 42
        points.append(
            f"<circle cx='{x}' cy='{y}' r='5' fill='#059669'></circle>"
            f"<text x='{x - 8}' y='{y + 18}' font-size='9'>{idx + 1}</text>"
            f"<title>{title}</title>"
        )
    return (
        "<h3>Catalyst Timeline</h3>"
        f"<svg id='catalyst-timeline' width='{width}' height='60' "
        "xmlns='http://www.w3.org/2000/svg'>"
        "<line x1='20' y1='22' x2='680' y2='22' stroke='#6b7280' stroke-width='2'></line>"
        + "".join(points)
        + "</svg>"
    )


def _rnpv_stack_svg(path: str | Path) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    analysis = payload.get("analysis") if isinstance(payload, dict) else {}
    base = analysis.get("base") if isinstance(analysis, dict) else {}
    assets = base.get("asset_rnpv") if isinstance(base, dict) else []
    rows = assets if isinstance(assets, list) else []
    x = 40
    width = 620
    total = sum(float(item.get("rnpv", 0.0)) for item in rows if isinstance(item, dict))
    if total <= 0:
        return (
            "<h3>rNPV Stack</h3>"
            "<svg id='rnpv-stack' width='700' height='70' xmlns='http://www.w3.org/2000/svg'>"
            "<text x='20' y='30' font-size='12'>No asset rNPV rows available.</text>"
            "</svg>"
        )
    bars: list[str] = []
    palette = ("#1d4ed8", "#059669", "#d97706", "#7c3aed", "#dc2626")
    for idx, item in enumerate(rows[:10]):
        if not isinstance(item, dict):
            continue
        value = float(item.get("rnpv", 0.0))
        if value <= 0:
            continue
        w = int(width * (value / total))
        bars.append(
            f"<rect x='{x}' y='18' width='{max(w,1)}' height='20' "
            f"fill='{palette[idx % len(palette)]}'></rect>"
        )
        x += w
    return (
        "<h3>rNPV Stack</h3>"
        "<svg id='rnpv-stack' width='700' height='70' xmlns='http://www.w3.org/2000/svg'>"
        + "".join(bars)
        + "</svg>"
    )
