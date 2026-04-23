from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .auto_inputs import (
    _next_binary_event_from_context,
    _regulatory_pathway_from_context,
)


@dataclass(frozen=True)
class P04GroundTruthCase:
    case_id: str
    field: str
    context: str
    expected: str | None


@dataclass(frozen=True)
class P04GroundTruthMetrics:
    case_count: int
    positive_count: int
    true_positive: int
    false_positive: int
    false_negative: int
    exact_match_count: int
    precision: float
    recall: float
    f1: float
    exact_match_rate: float


@dataclass(frozen=True)
class P04GroundTruthReport:
    regulatory_pathway: P04GroundTruthMetrics
    next_binary_event: P04GroundTruthMetrics
    failures: tuple[dict[str, Any], ...]


def load_p0_4_ground_truth_cases(path: str | Path) -> tuple[P04GroundTruthCase, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("cases")
    if not isinstance(rows, list):
        raise ValueError("ground truth cases must be a list")
    cases: list[P04GroundTruthCase] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        case_id = row.get("id")
        field = row.get("field")
        context = row.get("context")
        expected = row.get("expected")
        if not isinstance(case_id, str) or not case_id.strip():
            continue
        if field not in {"regulatory_pathway", "next_binary_event"}:
            continue
        if not isinstance(context, str) or not context.strip():
            continue
        if expected is not None and not isinstance(expected, str):
            continue
        cases.append(
            P04GroundTruthCase(
                case_id=case_id.strip(),
                field=field,
                context=context,
                expected=expected.strip() if isinstance(expected, str) else None,
            )
        )
    return tuple(cases)


def evaluate_p0_4_ground_truth(
    cases: tuple[P04GroundTruthCase, ...],
) -> P04GroundTruthReport:
    by_field = {
        "regulatory_pathway": tuple(
            case for case in cases if case.field == "regulatory_pathway"
        ),
        "next_binary_event": tuple(
            case for case in cases if case.field == "next_binary_event"
        ),
    }
    extractors: dict[str, Callable[[str], str | None]] = {
        "regulatory_pathway": _regulatory_pathway_from_context,
        "next_binary_event": _next_binary_event_from_context,
    }
    failures: list[dict[str, Any]] = []
    metrics_by_field: dict[str, P04GroundTruthMetrics] = {}
    for field, field_cases in by_field.items():
        extractor = extractors[field]
        exact_match_count = 0
        true_positive = 0
        false_positive = 0
        false_negative = 0
        positive_count = 0
        for case in field_cases:
            predicted = extractor(case.context)
            expected = case.expected
            if expected is not None:
                positive_count += 1
            if predicted == expected:
                exact_match_count += 1
                if expected is not None:
                    true_positive += 1
                continue
            if expected is None and predicted is not None:
                false_positive += 1
            elif expected is not None and predicted is None:
                false_negative += 1
            elif expected is not None and predicted is not None:
                false_positive += 1
                false_negative += 1
            failures.append(
                {
                    "id": case.case_id,
                    "field": case.field,
                    "expected": expected,
                    "predicted": predicted,
                }
            )
        precision = _safe_ratio(true_positive, true_positive + false_positive)
        recall = _safe_ratio(true_positive, true_positive + false_negative)
        f1 = _safe_ratio(2 * precision * recall, precision + recall)
        exact_match_rate = _safe_ratio(exact_match_count, len(field_cases))
        metrics_by_field[field] = P04GroundTruthMetrics(
            case_count=len(field_cases),
            positive_count=positive_count,
            true_positive=true_positive,
            false_positive=false_positive,
            false_negative=false_negative,
            exact_match_count=exact_match_count,
            precision=precision,
            recall=recall,
            f1=f1,
            exact_match_rate=exact_match_rate,
        )
    return P04GroundTruthReport(
        regulatory_pathway=metrics_by_field["regulatory_pathway"],
        next_binary_event=metrics_by_field["next_binary_event"],
        failures=tuple(failures),
    )


def report_to_dict(report: P04GroundTruthReport) -> dict[str, Any]:
    return {
        "regulatory_pathway": _metrics_to_dict(report.regulatory_pathway),
        "next_binary_event": _metrics_to_dict(report.next_binary_event),
        "failures": list(report.failures),
    }


def _metrics_to_dict(metrics: P04GroundTruthMetrics) -> dict[str, Any]:
    return {
        "case_count": metrics.case_count,
        "positive_count": metrics.positive_count,
        "true_positive": metrics.true_positive,
        "false_positive": metrics.false_positive,
        "false_negative": metrics.false_negative,
        "exact_match_count": metrics.exact_match_count,
        "precision": round(metrics.precision, 4),
        "recall": round(metrics.recall, 4),
        "f1": round(metrics.f1, 4),
        "exact_match_rate": round(metrics.exact_match_rate, 4),
    }


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
