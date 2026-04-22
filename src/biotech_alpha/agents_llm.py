"""LLM-backed research agents.

Each agent here relies on :class:`biotech_alpha.llm.LLMClient` for its
reasoning step but still adheres to the :class:`biotech_alpha.models.AgentFinding`
contract: evidence is source-backed, counter-theses are made explicit,
and ``needs_human_review`` remains True for the first batch of agents until
we have production-level calibration.

The first agent, :class:`ScientificSkepticLLMAgent`, consumes the outputs
of deterministic steps (pipeline extraction, trial coverage, valuation,
cash runway, deterministic scientific skeptic) and produces a structured
JSON counter-thesis that a portfolio manager can read in under a minute.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from biotech_alpha.agent_runtime import Agent, AgentStepResult, FactStore
from biotech_alpha.agents import AgentContext
from biotech_alpha.llm import LLMClient, SchemaError, StructuredPrompt
from biotech_alpha.llm.client import LLMError
from biotech_alpha.models import AgentFinding, Evidence


SCIENTIFIC_SKEPTIC_PROMPT = StructuredPrompt(
    name="scientific_skeptic",
    tags=("skeptic", "llm"),
    system=(
        "You are a senior biotech equity research analyst. You specialize in "
        "identifying why a bullish investment case may be wrong. You work "
        "only with the structured facts provided in the user message. You "
        "never invent trial IDs, revenue figures, or deal terms. If evidence "
        "is missing for a claim, say so in `needs_more_evidence` instead of "
        "speculating. Write in English. Be concise and concrete.\n\n"
        "OUTPUT RULES (must follow exactly):\n"
        "- Return a single JSON object at the TOP LEVEL. No wrapper keys.\n"
        "- Required top-level keys: summary, bear_case, risks.\n"
        "- Optional top-level keys: bull_case, needs_more_evidence, confidence.\n"
        "- Use key name `risks` (not `critical_risks` or similar).\n"
        "- Each item in `risks` MUST be an object with keys `description` and "
        "`severity` (severity must be exactly one of \"low\", \"medium\", "
        "\"high\"). Optional per-risk keys: `related_asset`, `evidence_key`.\n"
        "- Never put the output inside a `counter_thesis`, `analysis`, "
        "`result`, or any other wrapper key."
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n"
        "As of: ${as_of}\n\n"
        "Deterministic skeptic risks (pre-computed):\n${skeptic_risks}\n\n"
        "Pipeline snapshot:\n${pipeline_snapshot}\n\n"
        "Pipeline triage findings (from the pipeline-triage LLM agent, if "
        "present):\n${pipeline_triage}\n\n"
        "Trial coverage summary:\n${trial_summary}\n\n"
        "Valuation + cash snapshot:\n${valuation_snapshot}\n\n"
        "Input warnings:\n${input_warnings}\n\n"
        "Produce a structured counter-thesis. Focus on what could make the "
        "investment thesis fail in the next 12-24 months. Prioritise risks "
        "that are specific to this company and its disclosed assets. Avoid "
        "generic platitudes that apply to all biotech names.\n\n"
        "Return EXACTLY this JSON shape (fill the strings; keep the keys "
        "verbatim; do NOT wrap it in any outer object):\n"
        "{\n"
        "  \"summary\": \"<1-3 sentence bear-case thesis>\",\n"
        "  \"bull_case\": [\"<point>\", ...],\n"
        "  \"bear_case\": [\"<point>\", ...],\n"
        "  \"risks\": [\n"
        "    {\"description\": \"<specific risk>\", \"severity\": \"high|"
        "medium|low\", \"related_asset\": \"<asset or null>\", "
        "\"evidence_key\": \"<key or null>\"}\n"
        "  ],\n"
        "  \"needs_more_evidence\": [\"<question>\", ...],\n"
        "  \"confidence\": 0.0\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": ["summary", "bear_case", "risks"],
        "properties": {
            "summary": {
                "type": "string",
                "min_length": 20,
                "max_length": 600,
            },
            "bull_case": {
                "type": "array",
                "items": {"type": "string", "min_length": 5},
                "max_items": 8,
            },
            "bear_case": {
                "type": "array",
                "items": {"type": "string", "min_length": 5},
                "min_items": 1,
                "max_items": 10,
            },
            "risks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["description", "severity"],
                    "properties": {
                        "description": {"type": "string", "min_length": 10},
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                        },
                        "related_asset": {
                            "type": ["string", "null"],
                        },
                        "evidence_key": {
                            "type": ["string", "null"],
                        },
                    },
                },
                "min_items": 1,
                "max_items": 15,
            },
            "needs_more_evidence": {
                "type": "array",
                "items": {"type": "string", "min_length": 5},
                "max_items": 10,
            },
            "confidence": {
                "type": "number",
            },
        },
    },
)


@dataclass
class ScientificSkepticLLMAgent(Agent):
    """LLM counter-thesis agent, grounded on deterministic findings."""

    llm_client: LLMClient
    name: str = "scientific_skeptic_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = ("scientific_skeptic_llm_finding",)
    max_tokens: int | None = 1200
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("ScientificSkepticLLMAgent requires an LLMClient")

    def run(
        self, context: AgentContext, store: FactStore
    ) -> AgentStepResult:
        variables = self._collect_variables(context, store)
        system, user = SCIENTIFIC_SKEPTIC_PROMPT.render(variables)
        _write_debug_prompt(
            store=store,
            agent_name=self.name,
            system=system,
            user=user,
        )

        try:
            call = self.llm_client.complete(
                system=system,
                user=user,
                agent_name=self.name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format_json=True,
                extra_metadata={
                    "company": context.company,
                    "ticker": context.ticker,
                },
            )
        except LLMError as exc:
            return AgentStepResult(
                agent_name=self.name,
                error=f"LLM call failed: {exc}",
            )

        try:
            payload = SCIENTIFIC_SKEPTIC_PROMPT.parse_response(
                call.response_text
            )
        except SchemaError as exc:
            return AgentStepResult(
                agent_name=self.name,
                error=f"response did not match schema: {exc}",
                warnings=(
                    f"raw response (first 500 chars): "
                    f"{call.response_text[:500]}",
                ),
            )

        finding = _finding_from_payload(
            payload=payload,
            agent_name=self.name,
            model=call.model,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
        )
        return AgentStepResult(
            agent_name=self.name,
            finding=finding,
            outputs={
                "scientific_skeptic_llm_finding": finding,
                "scientific_skeptic_llm_payload": payload,
            },
        )

    def _collect_variables(
        self, context: AgentContext, store: FactStore
    ) -> dict[str, Any]:
        return {
            "company": context.company,
            "ticker": context.ticker or "n/a",
            "market": context.market,
            "as_of": context.as_of_date or "n/a",
            "skeptic_risks": _format_lines(store.get("skeptic_risks") or []),
            "pipeline_snapshot": _json_block(
                store.get("pipeline_snapshot")
            ),
            "pipeline_triage": _json_block(
                store.get("pipeline_triage_payload")
            ),
            "trial_summary": _json_block(store.get("trial_summary")),
            "valuation_snapshot": _json_block(
                store.get("valuation_snapshot")
            ),
            "input_warnings": _format_lines(store.get("input_warnings") or []),
        }


PIPELINE_TRIAGE_PROMPT = StructuredPrompt(
    name="pipeline_triage",
    tags=("pipeline", "triage", "llm"),
    system=(
        "You are a biotech pipeline data reviewer. Your job is to triage a "
        "structured pipeline snapshot against the original source text and "
        "flag anomalies a human analyst should double-check before using "
        "the data downstream. Anomalies include: implausible phase for an "
        "asset that otherwise looks preclinical, missing or contradictory "
        "target/indication vs the source text, past-due or malformed "
        "`next_milestone` values, registry name mismatches, and duplicate "
        "or near-duplicate entries. Work only from the provided facts plus "
        "the source text excerpt. Do not invent assets, targets, trial IDs, "
        "or dates.\n\n"
        "OUTPUT RULES (must follow exactly):\n"
        "- Return a single JSON object at the TOP LEVEL. No wrapper keys.\n"
        "- Required top-level keys: coverage_confidence, assets.\n"
        "- Optional top-level keys: summary, global_warnings.\n"
        "- `coverage_confidence` is a float in [0, 1] for how well the "
        "source text supports the current structured pipeline.\n"
        "- `assets` MUST be a list of objects, one per asset reviewed. "
        "Each object has keys: `name` (string, must match an asset name "
        "from the pipeline_snapshot), `severity` (exactly one of "
        "\"none\", \"low\", \"medium\", \"high\"), and `issues` (list of "
        "strings describing concrete anomalies; empty list when severity "
        "is \"none\"). Optional per-asset keys: `suggested_fixes` (list "
        "of strings) and `confidence` (float 0-1).\n"
        "- Never put the result under `pipeline_triage`, `analysis`, "
        "`result`, or any other wrapper key."
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n\n"
        "Pipeline snapshot (parsed by the deterministic extractor):\n"
        "${pipeline_snapshot}\n\n"
        "Input warnings from validators:\n${input_warnings}\n\n"
        "Trial coverage summary:\n${trial_summary}\n\n"
        "Source text excerpt (from the annual-results / main source):\n"
        "${source_text_excerpt}\n\n"
        "Review each asset in the pipeline snapshot. Only flag issues that "
        "the source text or a clear logical inconsistency actually "
        "supports; if an asset looks clean, use severity \"none\" with an "
        "empty `issues` list. Do not invent issues to seem thorough.\n\n"
        "Return EXACTLY this JSON shape (keep keys verbatim):\n"
        "{\n"
        "  \"coverage_confidence\": 0.0,\n"
        "  \"summary\": \"<1-3 sentence summary of pipeline data quality>\",\n"
        "  \"global_warnings\": [\"<warning>\", ...],\n"
        "  \"assets\": [\n"
        "    {\"name\": \"<asset name>\", \"severity\": "
        "\"none|low|medium|high\", "
        "\"issues\": [\"<issue>\", ...], "
        "\"suggested_fixes\": [\"<fix>\", ...], "
        "\"confidence\": 0.0}\n"
        "  ]\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": ["coverage_confidence", "assets"],
        "properties": {
            "coverage_confidence": {"type": "number"},
            "summary": {
                "type": ["string", "null"],
                "max_length": 600,
            },
            "global_warnings": {
                "type": "array",
                "items": {"type": "string", "min_length": 3},
                "max_items": 10,
            },
            "assets": {
                "type": "array",
                "min_items": 1,
                "max_items": 40,
                "items": {
                    "type": "object",
                    "required": ["name", "severity", "issues"],
                    "properties": {
                        "name": {"type": "string", "min_length": 1},
                        "severity": {
                            "type": "string",
                            "enum": ["none", "low", "medium", "high"],
                        },
                        "issues": {
                            "type": "array",
                            "items": {"type": "string", "min_length": 3},
                            "max_items": 10,
                        },
                        "suggested_fixes": {
                            "type": "array",
                            "items": {"type": "string", "min_length": 3},
                            "max_items": 10,
                        },
                        "confidence": {"type": ["number", "null"]},
                    },
                },
            },
        },
    },
)


@dataclass
class PipelineTriageLLMAgent(Agent):
    """LLM agent that triages the structured pipeline vs the source text."""

    llm_client: LLMClient
    name: str = "pipeline_triage_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = (
        "pipeline_triage_llm_finding",
        "pipeline_triage_payload",
    )
    max_tokens: int | None = 1500
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("PipelineTriageLLMAgent requires an LLMClient")

    def run(
        self, context: AgentContext, store: FactStore
    ) -> AgentStepResult:
        pipeline = store.get("pipeline_snapshot") or {}
        assets = pipeline.get("assets") if isinstance(pipeline, dict) else None
        if not assets:
            return AgentStepResult(
                agent_name=self.name,
                skipped=True,
                error="no pipeline assets available for triage",
            )

        variables = self._collect_variables(context, store)
        system, user = PIPELINE_TRIAGE_PROMPT.render(variables)
        _write_debug_prompt(
            store=store,
            agent_name=self.name,
            system=system,
            user=user,
        )

        try:
            call = self.llm_client.complete(
                system=system,
                user=user,
                agent_name=self.name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                response_format_json=True,
                extra_metadata={
                    "company": context.company,
                    "ticker": context.ticker,
                },
            )
        except LLMError as exc:
            return AgentStepResult(
                agent_name=self.name,
                error=f"LLM call failed: {exc}",
            )

        try:
            payload = PIPELINE_TRIAGE_PROMPT.parse_response(
                call.response_text
            )
        except SchemaError as exc:
            return AgentStepResult(
                agent_name=self.name,
                error=f"response did not match schema: {exc}",
                warnings=(
                    f"raw response (first 500 chars): "
                    f"{call.response_text[:500]}",
                ),
            )

        finding = _triage_finding_from_payload(
            payload=payload,
            agent_name=self.name,
            model=call.model,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
        )
        return AgentStepResult(
            agent_name=self.name,
            finding=finding,
            outputs={
                "pipeline_triage_llm_finding": finding,
                "pipeline_triage_payload": payload,
            },
        )

    def _collect_variables(
        self, context: AgentContext, store: FactStore
    ) -> dict[str, Any]:
        return {
            "company": context.company,
            "ticker": context.ticker or "n/a",
            "market": context.market,
            "pipeline_snapshot": _json_block(store.get("pipeline_snapshot")),
            "input_warnings": _format_lines(store.get("input_warnings") or []),
            "trial_summary": _json_block(store.get("trial_summary")),
            "source_text_excerpt": _source_text_block(
                store.get("source_text_excerpt")
            ),
        }


def _triage_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        summary = "Pipeline triage completed."

    risks: list[str] = []
    for warning in payload.get("global_warnings") or []:
        line = str(warning).strip()
        if line:
            risks.append(f"[global] {line}")

    flagged_severities: set[str] = set()
    for asset in payload.get("assets") or []:
        name = str(asset.get("name", "")).strip()
        severity = str(asset.get("severity", "")).strip().lower()
        issues = [
            str(issue).strip()
            for issue in asset.get("issues") or []
            if str(issue).strip()
        ]
        if severity and severity != "none":
            flagged_severities.add(severity)
        if severity in {"low", "medium", "high"} and issues:
            for issue in issues:
                prefix = f"[{severity}][{name}]" if name else f"[{severity}]"
                risks.append(f"{prefix} {issue}")

    try:
        coverage_confidence = float(payload.get("coverage_confidence") or 0.0)
    except (TypeError, ValueError):
        coverage_confidence = 0.0
    coverage_confidence = max(0.0, min(1.0, coverage_confidence))

    needs_review = bool(flagged_severities & {"medium", "high"})

    evidence = (
        Evidence(
            claim=(
                "Pipeline triage produced by "
                f"{model} (prompt_tokens={prompt_tokens}, "
                f"completion_tokens={completion_tokens})"
            ),
            source="llm:" + model,
            confidence=coverage_confidence,
            is_inferred=True,
        ),
    )

    return AgentFinding(
        agent_name=agent_name,
        summary=summary,
        risks=tuple(risks),
        evidence=evidence,
        confidence=coverage_confidence,
        needs_human_review=True if needs_review else True,
    )


def _source_text_block(value: Any) -> str:
    if value is None:
        return "(source text unavailable)"
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        anchor = value.get("anchor_asset")
        header = [
            f"title: {value.get('title') or 'unknown'}",
            f"url: {value.get('url') or 'unknown'}",
            f"publication_date: {value.get('publication_date') or 'unknown'}",
            f"anchor_asset: {anchor or '(no asset anchor found)'}",
            (
                f"excerpt_chars: {value.get('excerpt_chars')} "
                f"(of total {value.get('total_chars')})"
            ),
        ]
        excerpt = value.get("excerpt") or ""
        return "\n".join(header) + "\n---\n" + excerpt
    return str(value)


def _format_lines(items: Any) -> str:
    if not items:
        return "(none)"
    if isinstance(items, str):
        return items
    lines = [f"- {item}" for item in items if str(item).strip()]
    return "\n".join(lines) if lines else "(none)"


def _write_debug_prompt(
    *,
    store: FactStore,
    agent_name: str,
    system: str,
    user: str,
) -> None:
    debug_dir = store.get("_llm_prompt_debug_dir")
    run_id = store.get("_llm_prompt_debug_run_id")
    if not isinstance(debug_dir, Path) or not isinstance(run_id, str):
        return
    path = debug_dir / f"{run_id}_{agent_name}_prompt.txt"
    path.write_text(
        "\n".join(
            (
                f"agent={agent_name}",
                "--- system ---",
                system,
                "",
                "--- user ---",
                user,
                "",
            )
        ),
        encoding="utf-8",
    )


def _json_block(value: Any) -> str:
    if value is None:
        return "(not available)"
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        return str(value)


def _finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    summary = str(payload.get("summary") or "").strip()
    risks_raw = payload.get("risks") or []
    risk_lines: list[str] = []
    for entry in risks_raw:
        description = str(entry.get("description", "")).strip()
        severity = str(entry.get("severity", "")).strip()
        asset = entry.get("related_asset")
        prefix = f"[{severity}]" if severity else ""
        if asset:
            prefix = f"{prefix}[{asset}]".strip()
        line = f"{prefix} {description}".strip() if prefix else description
        if line:
            risk_lines.append(line)

    bear_lines = [
        str(x).strip()
        for x in payload.get("bear_case") or []
        if str(x).strip()
    ]
    for line in bear_lines:
        risk_lines.append(f"[bear] {line}")

    missing = [
        str(x).strip()
        for x in payload.get("needs_more_evidence") or []
        if str(x).strip()
    ]
    needs_review = bool(missing) or bool(
        payload.get("needs_more_evidence")
    )

    confidence_raw = payload.get("confidence")
    try:
        confidence = (
            float(confidence_raw) if confidence_raw is not None else 0.4
        )
    except (TypeError, ValueError):
        confidence = 0.4

    evidence = (
        Evidence(
            claim=(
                "LLM counter-thesis produced by "
                f"{model} (prompt_tokens={prompt_tokens}, "
                f"completion_tokens={completion_tokens})"
            ),
            source="llm:" + model,
            confidence=confidence,
            is_inferred=True,
        ),
    )
    return AgentFinding(
        agent_name=agent_name,
        summary=summary,
        risks=tuple(risk_lines),
        evidence=evidence,
        confidence=confidence,
        needs_human_review=True if needs_review else True,
    )
