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
        "speculating. Be concise and concrete.\n\n"
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
        "Fallback context (raw trials/evidence/input-validation for low-input runs):\n"
        "${fallback_context}\n\n"
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
            payload = _normalize_payload_company(payload, context.company)
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
            "fallback_context": _json_block(store.get("fallback_context")),
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
                "min_items": 0,
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
        warnings: list[str] = []
        if not assets:
            warnings.append("fallback_context:pipeline_triage")

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
            payload = _normalize_payload_company(payload, context.company)
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
            warnings=tuple(warnings),
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
        warnings: list[str] = []
        if not isinstance(snapshot, dict) or not snapshot:
            warnings.append("fallback_context:financial_triage")

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
            payload = _normalize_payload_company(payload, context.company)
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
            warnings=tuple(warnings),
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
        warnings: list[str] = []
        if not isinstance(snapshot, dict) or not snapshot:
            warnings.append("fallback_context:competition_triage")
            snapshot = {}
        competitor_assets = snapshot.get("competitor_assets")
        if not competitor_assets:
            if "fallback_context:competition_triage" not in warnings:
                warnings.append("fallback_context:competition_triage")

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
            payload = _normalize_payload_company(payload, context.company)
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
            warnings=tuple(warnings),
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
        warnings: list[str] = []
        if not isinstance(macro_context, dict) or not macro_context:
            warnings.append("fallback_context:macro_context")

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
            payload = _normalize_payload_company(payload, context.company)
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
            warnings=tuple(warnings),
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


INVESTMENT_THESIS_PROMPT = StructuredPrompt(
    name="investment_thesis",
    tags=("thesis", "investment", "llm"),
    system=(
        "You are the final investment-thesis editor for a biotech research memo. "
        "You synthesize deterministic outputs and upstream LLM triage payloads into "
        "an actionable thesis. Work only with provided facts. Do not invent numbers, "
        "trial outcomes, or external data.\n\n"
        "OUTPUT RULES:\n"
        "- Return a single JSON object at top level.\n"
        "- Required keys: thesis_summary, bull_drivers, bear_drivers, "
        "key_assumptions, falsification_watch, decision_rationale.\n"
        "- Optional key: confidence.\n"
        "- Keep each bullet concise and concrete.\n"
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n"
        "As of: ${as_of}\n\n"
        "Pipeline triage payload:\n${pipeline_triage}\n\n"
        "Financial triage payload:\n${financial_triage}\n\n"
        "Competition triage payload:\n${competition_triage}\n\n"
        "Macro context payload:\n${macro_context}\n\n"
        "Scientific skeptic finding:\n${skeptic_finding}\n\n"
        "Target-price snapshot:\n${target_price_snapshot}\n\n"
        "Scorecard summary:\n${scorecard_summary}\n\n"
        "Fallback context (raw evidence/trials for low-input runs):\n"
        "${fallback_context}\n\n"
        "Return EXACTLY this JSON shape:\n"
        "{\n"
        "  \"thesis_summary\": \"<2-3 sentence thesis>\",\n"
        "  \"bull_drivers\": [\"<driver>\", \"...\"],\n"
        "  \"bear_drivers\": [\"<driver>\", \"...\"],\n"
        "  \"key_assumptions\": [\"<assumption>\", \"...\"],\n"
        "  \"falsification_watch\": [\"<what would falsify thesis>\", \"...\"],\n"
        "  \"decision_rationale\": \"<why current decision bucket>\",\n"
        "  \"confidence\": 0.0\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": [
            "thesis_summary",
            "bull_drivers",
            "bear_drivers",
            "key_assumptions",
            "falsification_watch",
            "decision_rationale",
        ],
        "properties": {
            "thesis_summary": {"type": "string", "min_length": 10},
            "bull_drivers": {
                "type": "array",
                "items": {"type": "string", "min_length": 3},
                "max_items": 8,
            },
            "bear_drivers": {
                "type": "array",
                "items": {"type": "string", "min_length": 3},
                "max_items": 8,
            },
            "key_assumptions": {
                "type": "array",
                "items": {"type": "string", "min_length": 3},
                "max_items": 8,
            },
            "falsification_watch": {
                "type": "array",
                "items": {"type": "string", "min_length": 3},
                "max_items": 8,
            },
            "decision_rationale": {"type": "string", "min_length": 5},
            "confidence": {"type": ["number", "null"]},
        },
    },
)


@dataclass
class InvestmentThesisLLMAgent(Agent):
    """Final synthesis agent for investment-thesis framing."""

    llm_client: LLMClient
    name: str = "investment_thesis_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = (
        "investment_thesis_llm_finding",
        "investment_thesis_payload",
    )
    max_tokens: int | None = 1800
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("InvestmentThesisLLMAgent requires an LLMClient")

    def run(self, context: AgentContext, store: FactStore) -> AgentStepResult:
        variables = self._collect_variables(context, store)
        system, user = INVESTMENT_THESIS_PROMPT.render(variables)
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
            payload = INVESTMENT_THESIS_PROMPT.parse_response(call.response_text)
            payload = _normalize_payload_company(payload, context.company)
        except SchemaError as exc:
            return AgentStepResult(
                agent_name=self.name,
                error=f"response did not match schema: {exc}",
                warnings=(
                    f"raw response (first 500 chars): "
                    f"{call.response_text[:500]}",
                ),
            )
        finding = _investment_thesis_finding_from_payload(
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
                "investment_thesis_llm_finding": finding,
                "investment_thesis_payload": payload,
            },
        )

    def _collect_variables(
        self, context: AgentContext, store: FactStore
    ) -> dict[str, Any]:
        skeptic = store.get("scientific_skeptic_llm_finding")
        return {
            "company": context.company,
            "ticker": context.ticker or "n/a",
            "market": context.market,
            "as_of": context.as_of_date or "n/a",
            "pipeline_triage": _json_block(store.get("pipeline_triage_payload")),
            "financial_triage": _json_block(store.get("financial_triage_payload")),
            "competition_triage": _json_block(store.get("competition_triage_payload")),
            "macro_context": _json_block(store.get("macro_context_payload")),
            "fallback_context": _json_block(store.get("fallback_context")),
            "skeptic_finding": _json_block(
                {
                    "summary": getattr(skeptic, "summary", None),
                    "risks": list(getattr(skeptic, "risks", ()) or ()),
                    "confidence": getattr(skeptic, "confidence", None),
                }
                if skeptic is not None
                else None
            ),
            "target_price_snapshot": _json_block(store.get("target_price_snapshot")),
            "scorecard_summary": _json_block(store.get("scorecard_summary")),
        }


VALUATION_SPECIALIST_PROMPT = StructuredPrompt(
    name="valuation_specialist",
    tags=("valuation", "specialist", "llm"),
    system=(
        "你是生物医药投研团队的估值专家。你的任务是基于已给定事实，"
        "选择并解释合适的估值框架（例如 rNPV、可比估值、分部估值）。"
        "你必须明确每个框架适用条件、关键假设、以及结果局限性。"
        "不得编造外部数据。"
    ),
    user_template=(
        "公司: ${company}\n"
        "代码: ${ticker}\n"
        "市场: ${market}\n"
        "日期: ${as_of}\n\n"
        "估值快照:\n${valuation_snapshot}\n\n"
        "目标价快照(rNPV场景):\n${target_price_snapshot}\n\n"
        "财务快照:\n${financials_snapshot}\n\n"
        "管线分诊:\n${pipeline_triage}\n\n"
        "竞争分诊:\n${competition_triage}\n\n"
        "回退上下文:\n${fallback_context}\n\n"
        "请返回严格 JSON:\n"
        "{\n"
        "  \"summary\": \"<2-4句估值结论>\",\n"
        "  \"primary_method\": \"<rNPV|SOTP|multiples|hybrid>\",\n"
        "  \"method_rationale\": [\"<理由>\", \"...\"],\n"
        "  \"valuation_breakdown\": [\"<分项估值说明>\", \"...\"],\n"
        "  \"key_assumptions\": [\"<关键假设>\", \"...\"],\n"
        "  \"risks\": [\"<估值风险>\", \"...\"],\n"
        "  \"confidence\": 0.0\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": [
            "summary",
            "primary_method",
            "method_rationale",
            "valuation_breakdown",
            "key_assumptions",
            "risks",
        ],
        "properties": {
            "summary": {"type": "string", "min_length": 10},
            "primary_method": {
                "type": "string",
                "enum": ["rNPV", "SOTP", "multiples", "hybrid"],
            },
            "method_rationale": {
                "type": "array",
                "items": {"type": "string", "min_length": 3},
                "max_items": 8,
            },
            "valuation_breakdown": {
                "type": "array",
                "items": {"type": "string", "min_length": 3},
                "max_items": 10,
            },
            "key_assumptions": {
                "type": "array",
                "items": {"type": "string", "min_length": 3},
                "max_items": 10,
            },
            "risks": {
                "type": "array",
                "items": {"type": "string", "min_length": 3},
                "max_items": 12,
            },
            "confidence": {"type": ["number", "null"]},
        },
    },
)


@dataclass
class ValuationSpecialistLLMAgent(Agent):
    """估值专用 LLM agent：给出框架、拆解与风险。"""

    llm_client: LLMClient
    name: str = "valuation_specialist_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = (
        "valuation_specialist_llm_finding",
        "valuation_specialist_payload",
    )
    max_tokens: int | None = 1500
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("ValuationSpecialistLLMAgent requires an LLMClient")

    def run(self, context: AgentContext, store: FactStore) -> AgentStepResult:
        system, user = VALUATION_SPECIALIST_PROMPT.render(
            {
                "company": context.company,
                "ticker": context.ticker or "n/a",
                "market": context.market,
                "as_of": context.as_of_date or "n/a",
                "valuation_snapshot": _json_block(store.get("valuation_snapshot")),
                "target_price_snapshot": _json_block(store.get("target_price_snapshot")),
                "financials_snapshot": _json_block(store.get("financials_snapshot")),
                "pipeline_triage": _json_block(store.get("pipeline_triage_payload")),
                "competition_triage": _json_block(store.get("competition_triage_payload")),
                "fallback_context": _json_block(store.get("fallback_context")),
            }
        )
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
            payload = VALUATION_SPECIALIST_PROMPT.parse_response(call.response_text)
            payload = _normalize_payload_company(payload, context.company)
        except SchemaError as exc:
            return AgentStepResult(
                agent_name=self.name,
                error=f"response did not match schema: {exc}",
                warnings=(
                    f"raw response (first 500 chars): {call.response_text[:500]}",
                ),
            )
        finding = _valuation_specialist_finding_from_payload(
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
                "valuation_specialist_llm_finding": finding,
                "valuation_specialist_payload": payload,
            },
        )


VALUATION_POD_PROMPT = StructuredPrompt(
    name="valuation_pod_agent",
    tags=("valuation", "pod", "llm"),
    system=(
        "你是投研估值小组成员。"
        "仅使用输入事实做估值解释，不得编造外部数字。"
        "输出严格 JSON，数字字段必须是数字。"
    ),
    user_template=(
        "公司: ${company}\n"
        "代码: ${ticker}\n"
        "市场: ${market}\n"
        "日期: ${as_of}\n"
        "角色: ${role}\n\n"
        "估值快照:\n${valuation_snapshot}\n\n"
        "目标价快照:\n${target_price_snapshot}\n\n"
        "财务快照:\n${financials_snapshot}\n\n"
        "管线分诊:\n${pipeline_triage}\n\n"
        "竞争分诊:\n${competition_triage}\n\n"
        "宏观上下文:\n${macro_context}\n\n"
        "上游估值分项(仅 committee 可用):\n${upstream_valuation_payloads}\n\n"
        "请返回严格 JSON：\n"
        "{\n"
        "  \"summary\": \"<2-4句>\",\n"
        "  \"method\": \"<multiple|dcf_simple|rNPV|balance_sheet_adjustment|sotp_committee>\",\n"
        "  \"scope\": \"<估值覆盖范围>\",\n"
        "  \"assumptions\": [\"<关键假设>\", \"...\"],\n"
        "  \"valuation_range\": {\"bear\": 0.0, \"base\": 0.0, \"bull\": 0.0},\n"
        "  \"sensitivity\": [\"<敏感性说明>\", \"...\"],\n"
        "  \"risks\": [\"<风险>\", \"...\"],\n"
        "  \"confidence\": 0.0,\n"
        "  \"needs_human_review\": true,\n"
        "  \"currency\": \"HKD\",\n"
        "  \"sotp_bridge\": [\"<仅committee填写，可空>\"],\n"
        "  \"method_weights\": [\"<仅committee填写，可空>\"],\n"
        "  \"conflict_resolution\": [\"<仅committee填写，可空>\"]\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": [
            "summary",
            "method",
            "scope",
            "assumptions",
            "valuation_range",
            "sensitivity",
            "risks",
            "needs_human_review",
            "currency",
        ],
        "properties": {
            "summary": {"type": "string", "min_length": 6},
            "method": {
                "type": "string",
                "enum": [
                    "multiple",
                    "dcf_simple",
                    "rNPV",
                    "balance_sheet_adjustment",
                    "sotp_committee",
                ],
            },
            "scope": {"type": "string", "min_length": 2},
            "assumptions": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 12,
            },
            "valuation_range": {
                "type": "object",
                "required": ["bear", "base", "bull"],
                "properties": {
                    "bear": {"type": "number"},
                    "base": {"type": "number"},
                    "bull": {"type": "number"},
                },
            },
            "sensitivity": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 12,
            },
            "risks": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 12,
            },
            "confidence": {"type": ["number", "null"]},
            "needs_human_review": {"type": "boolean"},
            "currency": {"type": "string", "min_length": 3},
            "sotp_bridge": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 20,
            },
            "method_weights": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 10,
            },
            "conflict_resolution": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 10,
            },
        },
    },
)


@dataclass
class _ValuationPodLLMAgentBase(Agent):
    llm_client: LLMClient
    role: str = "valuation_role"
    name: str = "valuation_pod_llm_agent"
    depends_on: tuple[str, ...] = ()
    finding_output_key: str = "valuation_pod_llm_finding"
    payload_output_key: str = "valuation_pod_payload"
    max_tokens: int | None = 1300
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError(f"{self.__class__.__name__} requires an LLMClient")

    def run(self, context: AgentContext, store: FactStore) -> AgentStepResult:
        system, user = VALUATION_POD_PROMPT.render(
            {
                "company": context.company,
                "ticker": context.ticker or "n/a",
                "market": context.market,
                "as_of": context.as_of_date or "n/a",
                "role": self.role,
                "valuation_snapshot": _json_block(store.get("valuation_snapshot")),
                "target_price_snapshot": _json_block(
                    store.get("target_price_snapshot")
                ),
                "financials_snapshot": _json_block(store.get("financials_snapshot")),
                "pipeline_triage": _json_block(store.get("pipeline_triage_payload")),
                "competition_triage": _json_block(
                    store.get("competition_triage_payload")
                ),
                "macro_context": _json_block(store.get("macro_context_payload")),
                "upstream_valuation_payloads": _json_block(
                    {
                        "commercial": store.get("valuation_commercial_payload"),
                        "rnpv": store.get("valuation_rnpv_payload"),
                        "balance_sheet": store.get("valuation_balance_sheet_payload"),
                    }
                ),
            }
        )
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
                    "valuation_role": self.role,
                },
            )
        except LLMError as exc:
            return AgentStepResult(
                agent_name=self.name,
                error=f"LLM call failed: {exc}",
            )
        try:
            payload = VALUATION_POD_PROMPT.parse_response(call.response_text)
            payload = _normalize_payload_company(payload, context.company)
        except SchemaError as exc:
            return AgentStepResult(
                agent_name=self.name,
                error=f"response did not match schema: {exc}",
                warnings=(
                    f"raw response (first 500 chars): {call.response_text[:500]}",
                ),
            )
        finding = _valuation_pod_finding_from_payload(
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
                self.finding_output_key: finding,
                self.payload_output_key: payload,
            },
        )


@dataclass
class ValuationCommercialLLMAgent(_ValuationPodLLMAgentBase):
    role: str = "valuation-commercial-agent"
    name: str = "valuation_commercial_llm_agent"
    produces: tuple[str, ...] = (
        "valuation_commercial_llm_finding",
        "valuation_commercial_payload",
    )
    finding_output_key: str = "valuation_commercial_llm_finding"
    payload_output_key: str = "valuation_commercial_payload"


@dataclass
class ValuationPipelineRnpvLLMAgent(_ValuationPodLLMAgentBase):
    role: str = "valuation-pipeline-rnpv-agent"
    name: str = "valuation_rnpv_llm_agent"
    produces: tuple[str, ...] = (
        "valuation_rnpv_llm_finding",
        "valuation_rnpv_payload",
    )
    finding_output_key: str = "valuation_rnpv_llm_finding"
    payload_output_key: str = "valuation_rnpv_payload"


@dataclass
class ValuationBalanceSheetLLMAgent(_ValuationPodLLMAgentBase):
    role: str = "valuation-balance-sheet-agent"
    name: str = "valuation_balance_sheet_llm_agent"
    produces: tuple[str, ...] = (
        "valuation_balance_sheet_llm_finding",
        "valuation_balance_sheet_payload",
    )
    finding_output_key: str = "valuation_balance_sheet_llm_finding"
    payload_output_key: str = "valuation_balance_sheet_payload"


@dataclass
class ValuationCommitteeLLMAgent(_ValuationPodLLMAgentBase):
    role: str = "valuation-committee-agent"
    name: str = "valuation_committee_llm_agent"
    produces: tuple[str, ...] = (
        "valuation_committee_llm_finding",
        "valuation_committee_payload",
    )
    finding_output_key: str = "valuation_committee_llm_finding"
    payload_output_key: str = "valuation_committee_payload"
    max_tokens: int | None = 1600


REPORT_QUALITY_PROMPT = StructuredPrompt(
    name="report_quality",
    tags=("report", "quality", "llm"),
    system=(
        "你是独立报告质量审阅员。"
        "仅审查一致性、证据充分性、语言质量与估值口径一致性。"
        "不得发明新数据，不得覆盖上游结论。"
    ),
    user_template=(
        "公司: ${company}\n"
        "代码: ${ticker}\n"
        "市场: ${market}\n"
        "日期: ${as_of}\n\n"
        "摘要指标:\n${result_summary}\n\n"
        "估值分项输出:\n${valuation_pod_payloads}\n\n"
        "LLM findings:\n${llm_findings}\n\n"
        "请返回严格 JSON：\n"
        "{\n"
        "  \"summary\": \"<1-3句审查结论>\",\n"
        "  \"publish_gate\": \"<pass|review_required|block>\",\n"
        "  \"critical_issues\": [\"<问题>\", \"...\"],\n"
        "  \"consistency_findings\": [\"<发现>\", \"...\"],\n"
        "  \"missing_evidence_findings\": [\"<发现>\", \"...\"],\n"
        "  \"language_quality_findings\": [\"<发现>\", \"...\"],\n"
        "  \"valuation_coherence_findings\": [\"<发现>\", \"...\"],\n"
        "  \"recommended_fixes\": [\"<可执行修复>\", \"...\"],\n"
        "  \"confidence\": 0.0\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": [
            "summary",
            "publish_gate",
            "critical_issues",
            "consistency_findings",
            "missing_evidence_findings",
            "language_quality_findings",
            "valuation_coherence_findings",
            "recommended_fixes",
        ],
        "properties": {
            "summary": {"type": "string", "min_length": 4},
            "publish_gate": {
                "type": "string",
                "enum": ["pass", "review_required", "block"],
            },
            "critical_issues": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 20,
            },
            "consistency_findings": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 20,
            },
            "missing_evidence_findings": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 20,
            },
            "language_quality_findings": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 20,
            },
            "valuation_coherence_findings": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 20,
            },
            "recommended_fixes": {
                "type": "array",
                "items": {"type": "string", "min_length": 1},
                "max_items": 20,
            },
            "confidence": {"type": ["number", "null"]},
        },
    },
)


@dataclass
class ReportQualityLLMAgent(Agent):
    llm_client: LLMClient
    name: str = "report_quality_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = (
        "report_quality_llm_finding",
        "report_quality_payload",
    )
    max_tokens: int | None = 1200
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("ReportQualityLLMAgent requires an LLMClient")

    def run(self, context: AgentContext, store: FactStore) -> AgentStepResult:
        llm_findings = {
            "scientific_skeptic": _finding_snapshot(
                store.get("scientific_skeptic_llm_finding")
            ),
            "investment_thesis": _finding_snapshot(
                store.get("investment_thesis_llm_finding")
            ),
            "valuation_specialist": _finding_snapshot(
                store.get("valuation_specialist_llm_finding")
            ),
            "valuation_commercial": _finding_snapshot(
                store.get("valuation_commercial_llm_finding")
            ),
            "valuation_rnpv": _finding_snapshot(
                store.get("valuation_rnpv_llm_finding")
            ),
            "valuation_balance_sheet": _finding_snapshot(
                store.get("valuation_balance_sheet_llm_finding")
            ),
            "valuation_committee": _finding_snapshot(
                store.get("valuation_committee_llm_finding")
            ),
        }
        system, user = REPORT_QUALITY_PROMPT.render(
            {
                "company": context.company,
                "ticker": context.ticker or "n/a",
                "market": context.market,
                "as_of": context.as_of_date or "n/a",
                "result_summary": _json_block(store.get("scorecard_summary")),
                "valuation_pod_payloads": _json_block(
                    {
                        "commercial": store.get("valuation_commercial_payload"),
                        "rnpv": store.get("valuation_rnpv_payload"),
                        "balance_sheet": store.get("valuation_balance_sheet_payload"),
                        "committee": store.get("valuation_committee_payload"),
                    }
                ),
                "llm_findings": _json_block(llm_findings),
            }
        )
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
            payload = _report_quality_fallback_payload(
                reason=f"llm_error: {exc}"
            )
            finding = _report_quality_finding_from_payload(
                payload=payload,
                agent_name=self.name,
                model="fallback",
                prompt_tokens=None,
                completion_tokens=None,
            )
            return AgentStepResult(
                agent_name=self.name,
                finding=finding,
                warnings=(f"report_quality fallback applied: {exc}",),
                outputs={
                    "report_quality_llm_finding": finding,
                    "report_quality_payload": payload,
                },
            )
        try:
            payload = REPORT_QUALITY_PROMPT.parse_response(call.response_text)
            payload = _normalize_payload_company(payload, context.company)
        except SchemaError as exc:
            payload = _report_quality_fallback_payload(
                reason=f"schema_error: {exc}"
            )
            finding = _report_quality_finding_from_payload(
                payload=payload,
                agent_name=self.name,
                model=call.model,
                prompt_tokens=call.prompt_tokens,
                completion_tokens=call.completion_tokens,
            )
            return AgentStepResult(
                agent_name=self.name,
                finding=finding,
                warnings=(
                    f"raw response (first 500 chars): {call.response_text[:500]}",
                ),
                outputs={
                    "report_quality_llm_finding": finding,
                    "report_quality_payload": payload,
                },
            )
        finding = _report_quality_finding_from_payload(
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
                "report_quality_llm_finding": finding,
                "report_quality_payload": payload,
            },
        )


PROVISIONAL_PIPELINE_PROMPT = StructuredPrompt(
    name="provisional_pipeline",
    tags=("pipeline", "provisional", "llm"),
    system=(
        "You generate provisional pipeline rows when curated pipeline inputs are missing. "
        "Work only from provided trial/evidence context. Do not fabricate external facts."
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n\n"
        "Pipeline snapshot:\n${pipeline_snapshot}\n\n"
        "Trial summary:\n${trial_summary}\n\n"
        "Fallback context:\n${fallback_context}\n\n"
        "Return EXACTLY this JSON shape:\n"
        "{\n"
        "  \"summary\": \"<short summary>\",\n"
        "  \"confidence\": 0.0,\n"
        "  \"assets\": [\n"
        "    {\n"
        "      \"name\": \"<asset>\",\n"
        "      \"target\": \"<target or null>\",\n"
        "      \"indication\": \"<indication or null>\",\n"
        "      \"phase\": \"<phase or null>\",\n"
        "      \"confidence\": 0.0,\n"
        "      \"needs_human_review\": true\n"
        "    }\n"
        "  ]\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": ["summary", "assets"],
        "properties": {
            "summary": {"type": "string", "min_length": 1},
            "confidence": {"type": ["number", "null"]},
            "assets": {
                "type": "array",
                "max_items": 24,
                "items": {
                    "type": "object",
                    "required": ["name", "needs_human_review"],
                    "properties": {
                        "name": {"type": "string", "min_length": 1},
                        "target": {"type": ["string", "null"]},
                        "indication": {"type": ["string", "null"]},
                        "phase": {"type": ["string", "null"]},
                        "confidence": {"type": ["number", "null"]},
                        "needs_human_review": {"type": "boolean"},
                    },
                },
            },
        },
    },
)


@dataclass
class ProvisionalPipelineLLMAgent(Agent):
    llm_client: LLMClient
    name: str = "provisional_pipeline_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = ("provisional_pipeline_payload",)

    def run(self, context: AgentContext, store: FactStore) -> AgentStepResult:
        pipeline = store.get("pipeline_snapshot") or {}
        assets = pipeline.get("assets") if isinstance(pipeline, dict) else None
        if assets:
            return AgentStepResult(agent_name=self.name)
        system, user = PROVISIONAL_PIPELINE_PROMPT.render(
            {
                "company": context.company,
                "ticker": context.ticker or "n/a",
                "market": context.market,
                "pipeline_snapshot": _json_block(store.get("pipeline_snapshot")),
                "trial_summary": _json_block(store.get("trial_summary")),
                "fallback_context": _json_block(store.get("fallback_context")),
            }
        )
        try:
            call = self.llm_client.complete(
                system=system,
                user=user,
                agent_name=self.name,
                temperature=0.1,
                max_tokens=1200,
                response_format_json=True,
            )
            payload = PROVISIONAL_PIPELINE_PROMPT.parse_response(call.response_text)
            payload = _normalize_payload_company(payload, context.company)
        except (LLMError, SchemaError):
            payload = _deterministic_provisional_pipeline_from_fallback(
                store.get("fallback_context")
            )
        provisional_assets = payload.get("assets") or []
        return AgentStepResult(
            agent_name=self.name,
            warnings=("fallback_context:provisional_pipeline",),
            outputs={
                "provisional_pipeline_payload": payload,
                "pipeline_snapshot": {"assets": provisional_assets},
            },
        )


def _deterministic_provisional_pipeline_from_fallback(
    fallback_context: Any,
) -> dict[str, Any]:
    trial_rows = []
    if isinstance(fallback_context, dict):
        raw_rows = fallback_context.get("trial_rows")
        if isinstance(raw_rows, list):
            trial_rows = raw_rows
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in trial_rows:
        if not isinstance(row, dict):
            continue
        interventions = row.get("interventions")
        name = None
        if isinstance(interventions, list) and interventions:
            name = str(interventions[0]).strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        assets.append(
            {
                "name": name,
                "target": None,
                "indication": (
                    str((row.get("conditions") or [None])[0])
                    if isinstance(row.get("conditions"), list) and row.get("conditions")
                    else None
                ),
                "phase": row.get("phase"),
                "confidence": 0.2,
                "needs_human_review": True,
            }
        )
        if len(assets) >= 12:
            break
    return {
        "summary": "基于试验回退上下文生成临时管线草案。",
        "confidence": 0.2,
        "assets": assets,
    }


PROVISIONAL_FINANCIAL_PROMPT = StructuredPrompt(
    name="provisional_financial",
    tags=("financial", "provisional", "llm"),
    system=(
        "You provide a provisional runway range when curated financial inputs are missing. "
        "Use cautious language and include uncertainty."
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n\n"
        "Financial snapshot:\n${financials_snapshot}\n\n"
        "Valuation snapshot:\n${valuation_snapshot}\n\n"
        "Fallback context:\n${fallback_context}\n\n"
        "Return EXACTLY this JSON shape:\n"
        "{\n"
        "  \"summary\": \"<short summary>\",\n"
        "  \"confidence\": 0.0,\n"
        "  \"runway_range_months\": \"<e.g. 6-12>\",\n"
        "  \"needs_human_review\": true\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": ["summary", "runway_range_months", "needs_human_review"],
        "properties": {
            "summary": {"type": "string", "min_length": 1},
            "confidence": {"type": ["number", "null"]},
            "runway_range_months": {"type": "string", "min_length": 3},
            "needs_human_review": {"type": "boolean"},
        },
    },
)


@dataclass
class ProvisionalFinancialLLMAgent(Agent):
    llm_client: LLMClient
    name: str = "provisional_financial_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = ("provisional_financial_payload",)

    def run(self, context: AgentContext, store: FactStore) -> AgentStepResult:
        snapshot = store.get("financials_snapshot")
        if isinstance(snapshot, dict) and snapshot:
            return AgentStepResult(agent_name=self.name)
        system, user = PROVISIONAL_FINANCIAL_PROMPT.render(
            {
                "company": context.company,
                "ticker": context.ticker or "n/a",
                "market": context.market,
                "financials_snapshot": _json_block(store.get("financials_snapshot")),
                "valuation_snapshot": _json_block(store.get("valuation_snapshot")),
                "fallback_context": _json_block(store.get("fallback_context")),
            }
        )
        try:
            call = self.llm_client.complete(
                system=system,
                user=user,
                agent_name=self.name,
                temperature=0.1,
                max_tokens=700,
                response_format_json=True,
            )
            payload = PROVISIONAL_FINANCIAL_PROMPT.parse_response(call.response_text)
            payload = _normalize_payload_company(payload, context.company)
        except (LLMError, SchemaError) as exc:
            return AgentStepResult(agent_name=self.name, error=str(exc))
        return AgentStepResult(
            agent_name=self.name,
            warnings=("fallback_context:provisional_financial",),
            outputs={
                "provisional_financial_payload": payload,
                "financials_snapshot": {
                    "provisional_runway": payload,
                    "financial_warnings": [
                        "provisional financial snapshot generated by LLM"
                    ],
                },
            },
        )


def _investment_thesis_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    summary = str(payload.get("thesis_summary") or "").strip()
    if not summary:
        summary = "Investment thesis synthesis completed."
    risks: list[str] = []
    for line in payload.get("bear_drivers") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[bear] {text}")
    for line in payload.get("key_assumptions") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[assumption] {text}")
    for line in payload.get("falsification_watch") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[falsification] {text}")
    decision_rationale = str(payload.get("decision_rationale") or "").strip()
    if decision_rationale:
        risks.append(f"[decision] {decision_rationale}")
    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else 0.5
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    evidence = (
        Evidence(
            claim=(
                "Investment thesis produced by "
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


def _valuation_specialist_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        summary = "估值专用LLM已完成估值框架评估。"
    primary_method = str(payload.get("primary_method") or "").strip()
    risks: list[str] = []
    if primary_method:
        risks.append(f"[method] 主估值框架：{primary_method}")
    for line in payload.get("method_rationale") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[rationale] {text}")
    for line in payload.get("valuation_breakdown") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[breakdown] {text}")
    for line in payload.get("key_assumptions") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[assumption] {text}")
    for line in payload.get("risks") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[risk] {text}")
    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else 0.55
    except (TypeError, ValueError):
        confidence = 0.55
    confidence = max(0.0, min(1.0, confidence))
    evidence = (
        Evidence(
            claim=(
                "Valuation specialist analysis produced by "
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


def _valuation_pod_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        summary = "Valuation pod analysis completed."

    risks: list[str] = []
    method = str(payload.get("method") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    currency = str(payload.get("currency") or "").strip()
    valuation_range = payload.get("valuation_range") or {}
    if method:
        risks.append(f"[method] {method}")
    if scope:
        risks.append(f"[scope] {scope}")
    if valuation_range:
        risks.append(
            "[range] "
            f"bear={valuation_range.get('bear')} "
            f"base={valuation_range.get('base')} "
            f"bull={valuation_range.get('bull')} "
            f"currency={currency or 'n/a'}"
        )

    for line in payload.get("assumptions") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[assumption] {text}")
    for line in payload.get("sensitivity") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[sensitivity] {text}")
    for line in payload.get("risks") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[risk] {text}")
    for line in payload.get("conflict_resolution") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[conflict] {text}")

    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else 0.55
    except (TypeError, ValueError):
        confidence = 0.55
    confidence = max(0.0, min(1.0, confidence))
    needs_human_review = bool(payload.get("needs_human_review", True))

    evidence = (
        Evidence(
            claim=(
                "Valuation pod analysis produced by "
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
        needs_human_review=needs_human_review,
    )


def _report_quality_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        summary = "Report quality review completed."

    risks: list[str] = []
    publish_gate = str(payload.get("publish_gate") or "review_required").strip()
    if publish_gate:
        risks.append(f"[publish_gate] {publish_gate}")
    for key in (
        "critical_issues",
        "consistency_findings",
        "missing_evidence_findings",
        "language_quality_findings",
        "valuation_coherence_findings",
        "recommended_fixes",
    ):
        for line in payload.get(key) or []:
            text = str(line).strip()
            if text:
                risks.append(f"[{key}] {text}")

    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw is not None else 0.6
    except (TypeError, ValueError):
        confidence = 0.6
    confidence = max(0.0, min(1.0, confidence))
    needs_human_review = publish_gate != "pass"

    evidence = (
        Evidence(
            claim=(
                "Report quality review produced by "
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
        needs_human_review=needs_human_review,
    )


def _report_quality_fallback_payload(*, reason: str) -> dict[str, Any]:
    return {
        "summary": "Report quality agent fallback: manual review required.",
        "publish_gate": "review_required",
        "critical_issues": [f"report_quality_unavailable: {reason}"],
        "consistency_findings": [],
        "missing_evidence_findings": [],
        "language_quality_findings": [],
        "valuation_coherence_findings": [],
        "recommended_fixes": [
            "rerun report-quality agent after fixing LLM/schema issue"
        ],
        "confidence": 0.2,
    }


def _finding_snapshot(finding: Any) -> dict[str, Any] | None:
    if finding is None:
        return None
    return {
        "agent_name": getattr(finding, "agent_name", None),
        "summary": getattr(finding, "summary", None),
        "risks": list(getattr(finding, "risks", ()) or ()),
        "confidence": getattr(finding, "confidence", None),
        "needs_human_review": getattr(finding, "needs_human_review", None),
    }


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


def _normalize_payload_company(payload: Any, expected_company: str) -> Any:
    wrong_names = ("德琪医药", "Antengene", "德琪")

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            text = value
            for wrong in wrong_names:
                if wrong in text and expected_company:
                    text = text.replace(wrong, expected_company)
            return text
        if isinstance(value, list):
            return [_walk(item) for item in value]
        if isinstance(value, dict):
            return {key: _walk(item) for key, item in value.items()}
        return value

    return _walk(payload)


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
