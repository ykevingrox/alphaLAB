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
        "Financial triage findings (from the financial-triage LLM agent, "
        "if present):\n${financial_triage}\n\n"
        "Macro context findings (from the macro-context LLM agent, if "
        "present):\n${macro_context}\n\n"
        "Competition triage findings (from the competition-triage LLM "
        "agent, if present):\n${competition_triage}\n\n"
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
            "financial_triage": _json_block(
                store.get("financial_triage_payload")
            ),
            "macro_context": _json_block(
                store.get("macro_context_payload")
            ),
            "competition_triage": _json_block(
                store.get("competition_triage_payload")
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
        "Source text excerpt (from the annual-results / main source). The "
        "header of this block includes `anchor_assets` (names we confirmed "
        "are present in the source) and `missing_assets` (names the "
        "extractor could not locate in the source text at all). Windows "
        "are stitched from multiple offsets; each window starts with a "
        "`[... source ~offset N ...]` marker.\n${source_text_excerpt}\n\n"
        "Review each asset in the pipeline snapshot. Rules:\n"
        "- If an asset appears in `anchor_assets` above, validate its "
        "target/phase/indication/milestone against the excerpt.\n"
        "- If an asset appears in `missing_assets`, do NOT flag it as "
        "\"not in excerpt\"; that is an extractor coverage limit, not a "
        "data-quality issue on the asset itself. Use severity \"none\" "
        "for such assets unless the pipeline snapshot has an internal "
        "inconsistency (e.g. malformed milestone, past-due date, or "
        "contradictory fields) you can flag from the snapshot alone.\n"
        "- Only flag issues that the source text or a clear logical "
        "inconsistency actually supports; if an asset looks clean, use "
        "severity \"none\" with an empty `issues` list. Do not invent "
        "issues to seem thorough.\n"
        "- Keep the response compact so it cannot be truncated: summary "
        "under 60 words, at most 2 short issues per asset, and at most "
        "1 short suggested_fix per asset.\n\n"
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
    max_tokens: int | None = 2200
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


FINANCIAL_TRIAGE_PROMPT = StructuredPrompt(
    name="financial_triage",
    tags=("financial", "triage", "llm"),
    system=(
        "You are a biotech CFO reviewer. Your job is to cross-check a "
        "company's reported cash position, debt, burn rate, runway "
        "estimate, and market snapshot for consistency. Typical anomalies "
        "to flag include: runway implied by cash / burn disagreeing with "
        "the deterministic `runway_months` estimate by more than ~10%; "
        "market_snapshot.cash contradicting financial_snapshot."
        "cash_and_equivalents; short_term_debt exceeding net cash by a "
        "wide margin with no mention in financial_warnings; a missing or "
        "zero burn rate on a clearly pre-revenue company (revenue_ttm "
        "null or 0 on an EV scale above ~USD 200M); currency mismatches "
        "between financial_snapshot and market_snapshot; stale "
        "source_date relative to the report year.\n\n"
        "Work only from the provided facts. Do not fabricate cash or "
        "debt figures. If a field you need is null, say so in the issue "
        "text instead of guessing.\n\n"
        "OUTPUT RULES (must follow exactly):\n"
        "- Return a single JSON object at the TOP LEVEL. No wrapper keys.\n"
        "- Required top-level keys: runway_sanity, summary, findings.\n"
        "- Optional top-level keys: confidence, implied_runway_months.\n"
        "- `runway_sanity` is exactly one of \"consistent\", \"stretch\", "
        "\"inconsistent\", \"insufficient_data\".\n"
        "- `findings` is a list of objects. Each object MUST have "
        "`severity` (exactly one of \"low\", \"medium\", \"high\") and "
        "`description`. Optional per-finding keys: `metric` (the field "
        "you are commenting on, e.g. `runway_months`) and "
        "`suggested_action`.\n"
        "- Never put the output inside `financial_triage`, `analysis`, "
        "`result`, or any other wrapper key."
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n"
        "As of: ${as_of}\n\n"
        "Financials + runway snapshot (deterministic):\n"
        "${financials_snapshot}\n\n"
        "Trial coverage summary (context for burn-rate expectations):\n"
        "${trial_summary}\n\n"
        "Existing input validator warnings (deterministic):\n"
        "${input_warnings}\n\n"
        "Return EXACTLY this JSON shape (keep keys verbatim):\n"
        "{\n"
        "  \"runway_sanity\": "
        "\"consistent|stretch|inconsistent|insufficient_data\",\n"
        "  \"summary\": \"<1-3 sentence read on financial posture>\",\n"
        "  \"implied_runway_months\": 0.0,\n"
        "  \"confidence\": 0.0,\n"
        "  \"findings\": [\n"
        "    {\"severity\": \"low|medium|high\", "
        "\"metric\": \"<field name or null>\", "
        "\"description\": \"<concrete anomaly>\", "
        "\"suggested_action\": \"<string or null>\"}\n"
        "  ]\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": ["runway_sanity", "summary", "findings"],
        "properties": {
            "runway_sanity": {
                "type": "string",
                "enum": [
                    "consistent",
                    "stretch",
                    "inconsistent",
                    "insufficient_data",
                ],
            },
            "summary": {"type": "string", "min_length": 1},
            "implied_runway_months": {"type": ["number", "null"]},
            "confidence": {"type": ["number", "null"]},
            "findings": {
                "type": "array",
                "max_items": 20,
                "items": {
                    "type": "object",
                    "required": ["severity", "description"],
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                        },
                        "description": {
                            "type": "string",
                            "min_length": 3,
                        },
                        "metric": {"type": ["string", "null"]},
                        "suggested_action": {"type": ["string", "null"]},
                    },
                },
            },
        },
    },
)


@dataclass
class FinancialTriageLLMAgent(Agent):
    """LLM agent that sanity-checks cash / burn / runway / valuation."""

    llm_client: LLMClient
    name: str = "financial_triage_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = (
        "financial_triage_llm_finding",
        "financial_triage_payload",
    )
    max_tokens: int | None = 1200
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("FinancialTriageLLMAgent requires an LLMClient")

    def run(
        self, context: AgentContext, store: FactStore
    ) -> AgentStepResult:
        snapshot = store.get("financials_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return AgentStepResult(
                agent_name=self.name,
                skipped=True,
                error=(
                    "no financials_snapshot available for triage; either "
                    "financial inputs or a valuation snapshot must be "
                    "present for this agent to run"
                ),
            )

        variables = self._collect_variables(context, store)
        system, user = FINANCIAL_TRIAGE_PROMPT.render(variables)
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
            payload = FINANCIAL_TRIAGE_PROMPT.parse_response(
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

        finding = _financial_triage_finding_from_payload(
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
                "financial_triage_llm_finding": finding,
                "financial_triage_payload": payload,
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
            "financials_snapshot": _json_block(
                store.get("financials_snapshot")
            ),
            "trial_summary": _json_block(store.get("trial_summary")),
            "input_warnings": _format_lines(
                store.get("input_warnings") or []
            ),
        }


def _financial_triage_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        summary = "Financial triage completed."

    risks: list[str] = []
    has_high_severity = False
    for entry in payload.get("findings") or []:
        severity = str(entry.get("severity", "")).strip().lower()
        description = str(entry.get("description", "")).strip()
        metric = entry.get("metric")
        if not description or severity not in {"low", "medium", "high"}:
            continue
        prefix = f"[{severity}]"
        if metric:
            prefix = f"{prefix}[{metric}]"
        risks.append(f"{prefix} {description}")
        if severity == "high":
            has_high_severity = True

    runway_sanity = str(payload.get("runway_sanity") or "").strip().lower()
    if runway_sanity in {"inconsistent", "stretch"}:
        risks.insert(0, f"[runway_sanity] {runway_sanity}")

    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    evidence = (
        Evidence(
            claim=(
                "Financial triage produced by "
                f"{model} (prompt_tokens={prompt_tokens}, "
                f"completion_tokens={completion_tokens})"
            ),
            source="llm:" + model,
            confidence=confidence,
            is_inferred=True,
        ),
    )

    needs_review = (
        has_high_severity
        or runway_sanity in {"inconsistent", "insufficient_data"}
    )

    return AgentFinding(
        agent_name=agent_name,
        summary=summary,
        risks=tuple(risks),
        evidence=evidence,
        confidence=confidence,
        needs_human_review=True if needs_review else True,
    )


COMPETITION_TRIAGE_PROMPT = StructuredPrompt(
    name="competition_triage",
    tags=("competition", "triage", "llm"),
    system=(
        "You are a biotech competitive-landscape reviewer. Your job is to "
        "stress-test deterministic competitor matching output and highlight "
        "where the current competitor set may be crowded, sparse, stale, or "
        "internally inconsistent. Work only from provided facts. Do not "
        "invent competitors, readouts, ownership corrections, approved "
        "indications, or market-share claims. If a concern relies on facts "
        "not present in the input, phrase it as `requires verification` "
        "instead of asserting it as true. Do not claim a competitor belongs "
        "to a different company unless the provided facts say so.\n\n"
        "OUTPUT RULES (must follow exactly):\n"
        "- Return a single JSON object at the TOP LEVEL. No wrapper keys.\n"
        "- Required top-level keys: crowding_signal, summary, findings.\n"
        "- Optional top-level key: confidence.\n"
        "- `crowding_signal` is exactly one of \"crowded\", \"balanced\", "
        "\"unclear\", \"insufficient_data\".\n"
        "- `findings` is a list of objects, each with required keys "
        "`severity` (one of \"low\", \"medium\", \"high\") and "
        "`description`. Optional keys: `asset_name`, `match_scope`, "
        "`suggested_action`.\n"
        "- Never wrap output in `competition_triage`, `analysis`, `result`, "
        "or any other outer key."
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n"
        "As of: ${as_of}\n\n"
        "Competition snapshot (deterministic):\n${competition_snapshot}\n\n"
        "Pipeline snapshot context:\n${pipeline_snapshot}\n\n"
        "Input warnings:\n${input_warnings}\n\n"
        "Review rules:\n"
        "- Keep the response compact so it cannot be truncated: summary "
        "under 50 words, at most 8 findings, and each description under "
        "35 words.\n"
        "- Treat `to_verify` competitor fields as explicit uncertainty, "
        "not as proof that the competitor has the pipeline asset's "
        "indication or phase.\n\n"
        "Return EXACTLY this JSON shape (keep keys verbatim):\n"
        "{\n"
        "  \"crowding_signal\": \"crowded|balanced|unclear|insufficient_data\",\n"
        "  \"summary\": \"<1-3 sentence competition read>\",\n"
        "  \"confidence\": 0.0,\n"
        "  \"findings\": [\n"
        "    {\"severity\": \"low|medium|high\", "
        "\"description\": \"<specific issue or observation>\", "
        "\"asset_name\": \"<asset or null>\", "
        "\"match_scope\": \"<target|indication|target+indication|null>\", "
        "\"suggested_action\": \"<string or null>\"}\n"
        "  ]\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": ["crowding_signal", "summary", "findings"],
        "properties": {
            "crowding_signal": {
                "type": "string",
                "enum": [
                    "crowded",
                    "balanced",
                    "unclear",
                    "insufficient_data",
                ],
            },
            "summary": {"type": "string", "min_length": 1},
            "confidence": {"type": ["number", "null"]},
            "findings": {
                "type": "array",
                "max_items": 20,
                "items": {
                    "type": "object",
                    "required": ["severity", "description"],
                    "properties": {
                        "severity": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                        },
                        "description": {
                            "type": "string",
                            "min_length": 3,
                        },
                        "asset_name": {"type": ["string", "null"]},
                        "match_scope": {"type": ["string", "null"]},
                        "suggested_action": {"type": ["string", "null"]},
                    },
                },
            },
        },
    },
)


@dataclass
class CompetitionTriageLLMAgent(Agent):
    """LLM agent that critiques deterministic competitor matching outputs."""

    llm_client: LLMClient
    name: str = "competition_triage_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = (
        "competition_triage_llm_finding",
        "competition_triage_payload",
    )
    max_tokens: int | None = 1800
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("CompetitionTriageLLMAgent requires an LLMClient")

    def run(
        self, context: AgentContext, store: FactStore
    ) -> AgentStepResult:
        snapshot = store.get("competition_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return AgentStepResult(
                agent_name=self.name,
                skipped=True,
                error=(
                    "no competition_snapshot available for triage; "
                    "competitor inputs are required"
                ),
            )
        competitor_assets = snapshot.get("competitor_assets")
        if not competitor_assets:
            return AgentStepResult(
                agent_name=self.name,
                skipped=True,
                error=(
                    "competition_snapshot has no competitor_assets; "
                    "skip competition triage"
                ),
            )

        variables = self._collect_variables(context, store)
        system, user = COMPETITION_TRIAGE_PROMPT.render(variables)
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
            payload = COMPETITION_TRIAGE_PROMPT.parse_response(
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

        finding = _competition_triage_finding_from_payload(
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
                "competition_triage_llm_finding": finding,
                "competition_triage_payload": payload,
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
            "competition_snapshot": _json_block(
                store.get("competition_snapshot")
            ),
            "pipeline_snapshot": _json_block(store.get("pipeline_snapshot")),
            "input_warnings": _format_lines(store.get("input_warnings") or []),
        }


def _competition_triage_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        summary = "Competition triage completed."

    crowding_signal = str(payload.get("crowding_signal") or "").strip().lower()
    risks: list[str] = []
    if crowding_signal in {"crowded", "insufficient_data"}:
        risks.append(f"[crowding_signal] {crowding_signal}")

    has_high = False
    for entry in payload.get("findings") or []:
        severity = str(entry.get("severity", "")).strip().lower()
        description = str(entry.get("description", "")).strip()
        asset_name = str(entry.get("asset_name") or "").strip()
        match_scope = str(entry.get("match_scope") or "").strip()
        if not description or severity not in {"low", "medium", "high"}:
            continue
        prefix = f"[{severity}]"
        if asset_name:
            prefix = f"{prefix}[{asset_name}]"
        if match_scope:
            prefix = f"{prefix}[{match_scope}]"
        risks.append(f"{prefix} {description}")
        if severity == "high":
            has_high = True

    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    evidence = (
        Evidence(
            claim=(
                "Competition triage produced by "
                f"{model} (prompt_tokens={prompt_tokens}, "
                f"completion_tokens={completion_tokens})"
            ),
            source="llm:" + model,
            confidence=confidence,
            is_inferred=True,
        ),
    )

    needs_review = has_high or crowding_signal == "insufficient_data"

    return AgentFinding(
        agent_name=agent_name,
        summary=summary,
        risks=tuple(risks),
        evidence=evidence,
        confidence=confidence,
        needs_human_review=True if needs_review else True,
    )


MACRO_CONTEXT_PROMPT = StructuredPrompt(
    name="macro_context",
    tags=("macro", "context", "llm"),
    system=(
        "You are a macro strategist scoped to Hong Kong-listed biotech and "
        "China innovative-drug equities. You receive a small deterministic "
        "stub of macro facts (market, sector, report-run date, source "
        "publication dates, an optional `live_signals` block with a few "
        "source-tagged market indicators, and a list of `known_unknowns` "
        "the caller could not provide). Your job is to give the downstream "
        "skeptic agent a sober, explicitly-scoped read of the macro regime "
        "for this company.\n\n"
        "Ground rules:\n"
        "- Work only from the stub. Do NOT invent specific index moves, "
        "rate prints, news headlines, or FDA actions. If `live_signals` "
        "contains an `hsi` / `hkd_usd` entry, you MAY quote its values "
        "(e.g. \"HSI ~18290, +1.6% over last 30d\") in `summary` or the "
        "lists, but always cite the field name. If you need data that is "
        "not in the stub, reflect that by returning "
        "`macro_regime = \"insufficient_data\"` and listing the gap in "
        "`sector_headwinds` or `sector_drivers` only as a factually-"
        "framed unknown (e.g. \"rate trajectory unclear from provided "
        "inputs\"). When `live_signals` is present and at least one "
        "sub-field is non-null, prefer a concrete regime read "
        "(\"expansion\" / \"contraction\" / \"transition\") grounded in "
        "those values rather than defaulting to `insufficient_data`.\n"
        "- Prefer short, decision-grade phrases in `sector_drivers` and "
        "`sector_headwinds`. Aim for 2-5 items per side, max 8. No "
        "duplicates across the two lists.\n"
        "- Flag stale report-run date or stale source publication date "
        "(> 180 days old) in `sector_headwinds` as a data-freshness "
        "concern.\n\n"
        "OUTPUT RULES (must follow exactly):\n"
        "- Return a single JSON object at the TOP LEVEL. No wrapper keys.\n"
        "- Required top-level keys: macro_regime, summary, "
        "sector_drivers, sector_headwinds.\n"
        "- Optional top-level keys: confidence.\n"
        "- `macro_regime` is exactly one of "
        "\"expansion\", \"contraction\", \"transition\", "
        "\"insufficient_data\".\n"
        "- `sector_drivers` and `sector_headwinds` are lists of short "
        "strings (2-200 chars each).\n"
        "- Never nest the output inside `macro_context`, `analysis`, "
        "`result`, or any other wrapper key."
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n"
        "As of: ${as_of}\n\n"
        "Macro context stub (deterministic):\n${macro_context}\n\n"
        "Return EXACTLY this JSON shape (keep keys verbatim):\n"
        "{\n"
        "  \"macro_regime\": "
        "\"expansion|contraction|transition|insufficient_data\",\n"
        "  \"summary\": \"<1-3 sentence read on the macro regime>\",\n"
        "  \"confidence\": 0.0,\n"
        "  \"sector_drivers\": [\"<short driver>\"],\n"
        "  \"sector_headwinds\": [\"<short headwind>\"]\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": [
            "macro_regime",
            "summary",
            "sector_drivers",
            "sector_headwinds",
        ],
        "properties": {
            "macro_regime": {
                "type": "string",
                "enum": [
                    "expansion",
                    "contraction",
                    "transition",
                    "insufficient_data",
                ],
            },
            "summary": {"type": "string", "min_length": 1},
            "confidence": {"type": ["number", "null"]},
            "sector_drivers": {
                "type": "array",
                "max_items": 8,
                "items": {
                    "type": "string",
                    "min_length": 2,
                    "max_length": 200,
                },
            },
            "sector_headwinds": {
                "type": "array",
                "max_items": 8,
                "items": {
                    "type": "string",
                    "min_length": 2,
                    "max_length": 200,
                },
            },
        },
    },
)


@dataclass
class MacroContextLLMAgent(Agent):
    """LLM agent that reads a macro-context stub and frames the regime.

    Consumes the deterministic ``macro_context`` fact (market, sector,
    report date, source publication dates, and ``known_unknowns``) and
    produces a structured macro regime read for the skeptic to reason
    against. The agent is explicitly allowed (and instructed) to return
    ``macro_regime = "insufficient_data"`` when the stub is too thin,
    which is the expected early-state outcome until the fact is enriched
    with live index / rate / FX / news feeds.
    """

    llm_client: LLMClient
    name: str = "macro_context_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = (
        "macro_context_llm_finding",
        "macro_context_payload",
    )
    max_tokens: int | None = 900
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("MacroContextLLMAgent requires an LLMClient")

    def run(
        self, context: AgentContext, store: FactStore
    ) -> AgentStepResult:
        macro_context = store.get("macro_context")
        if not isinstance(macro_context, dict) or not macro_context:
            return AgentStepResult(
                agent_name=self.name,
                skipped=True,
                error=(
                    "no macro_context fact available; upstream "
                    "publish_research_facts must supply at least a "
                    "market / sector stub for this agent to run"
                ),
            )

        variables = self._collect_variables(context, store)
        system, user = MACRO_CONTEXT_PROMPT.render(variables)
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
            payload = MACRO_CONTEXT_PROMPT.parse_response(
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

        finding = _macro_context_finding_from_payload(
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
                "macro_context_llm_finding": finding,
                "macro_context_payload": payload,
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
            "macro_context": _json_block(store.get("macro_context")),
        }


def _macro_context_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        summary = "Macro context analysis completed."

    macro_regime = str(payload.get("macro_regime") or "").strip().lower()

    risks: list[str] = []
    if macro_regime == "contraction":
        risks.append("[macro_regime] contraction")
    elif macro_regime == "insufficient_data":
        risks.append("[macro_regime] insufficient_data")

    headwinds = payload.get("sector_headwinds") or []
    for headwind in headwinds:
        text = str(headwind).strip()
        if text:
            risks.append(f"[headwind] {text}")

    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    evidence = (
        Evidence(
            claim=(
                "Macro context analysis produced by "
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
        risks=tuple(risks),
        evidence=evidence,
        confidence=confidence,
        needs_human_review=True,
    )


def _source_text_block(value: Any) -> str:
    if value is None:
        return "(source text unavailable)"
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        anchors = value.get("anchor_assets")
        missing = value.get("missing_assets") or []
        if anchors is None and "anchor_asset" in value:
            anchors = [value["anchor_asset"]] if value["anchor_asset"] else []
        anchors = anchors or []
        anchor_line = (
            ", ".join(anchors)
            if anchors
            else "(no asset anchor found)"
        )
        missing_line = (
            ", ".join(str(m) for m in missing)
            if missing
            else "(all asset names found in text)"
        )
        details = value.get("anchor_details") or []
        details_line = "(not available)"
        if isinstance(details, list) and details:
            parts = []
            for item in details[:20]:
                if not isinstance(item, dict):
                    continue
                parts.append(
                    f"{item.get('asset')}:score={item.get('signal_score')}"
                )
            if parts:
                details_line = ", ".join(parts)
        header = [
            f"title: {value.get('title') or 'unknown'}",
            f"url: {value.get('url') or 'unknown'}",
            f"publication_date: {value.get('publication_date') or 'unknown'}",
            f"anchor_assets: {anchor_line}",
            f"missing_assets: {missing_line}",
            f"anchor_signal_scores: {details_line}",
            (
                f"excerpt_chars: {value.get('excerpt_chars')} "
                f"(of total {value.get('total_chars')}, "
                f"truncated={bool(value.get('truncated'))})"
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
