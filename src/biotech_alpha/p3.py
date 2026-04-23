"""Sprint-3 strategic utilities (deterministic baseline)."""

from __future__ import annotations

import csv
import difflib
import html
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


def memo_markdown_to_html(markdown_text: str, *, title: str = "Biotech Alpha Memo") -> str:
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
    return (
        "<html><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "</head><body>"
        f"{joined}"
        "</body></html>\n"
    )


def export_html(markdown_path: str | Path, output_path: str | Path) -> Path:
    text = Path(markdown_path).read_text(encoding="utf-8")
    html_text = memo_markdown_to_html(text, title=Path(markdown_path).stem)
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
