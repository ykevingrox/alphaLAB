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


MARKET_REGIME_TIMING_PROMPT = StructuredPrompt(
    name="market_regime_timing",
    tags=("market", "timing", "technical", "llm"),
    system=(
        "You are a market-regime and technical-timing analyst for a long-term "
        "biotech equity research workflow. You combine macro context, "
        "deterministic technical features, and available sentiment proxies into "
        "a research-only timing view. You must keep the long-term fundamental "
        "view separate from current price-action/regime context.\n\n"
        "Ground rules:\n"
        "- Work only from the provided payloads. Do NOT invent prices, "
        "support/resistance levels, flows, index moves, or headlines.\n"
        "- If technical_feature_payload is missing, state that the timing view "
        "is limited by missing price-history features.\n"
        "- If macro context is insufficient, carry that limitation forward "
        "instead of guessing.\n"
        "- No trading instructions. Do NOT say buy, sell, enter, exit, stop "
        "loss, or position size. Use research-only labels and monitoring "
        "language.\n"
        "- Prefer concrete trigger wording tied to provided fields, such as "
        "3m return, 52w drawdown, moving_average_state, HSI/HSBIO trend, "
        "volatility state, and source warnings.\n\n"
        "OUTPUT RULES (must follow exactly):\n"
        "- Return a single JSON object at the TOP LEVEL. No wrapper keys.\n"
        "- Required keys: timing_view, horizon, macro_regime, technical_state, "
        "sentiment_state, key_triggers, invalidation_signals, confidence, "
        "needs_human_review.\n"
        "- timing_view is exactly one of: favorable, neutral, fragile, "
        "avoid_chasing, de_risk_watch.\n"
        "- horizon is exactly one of: 1-3 months, 3-6 months, 6-12 months.\n"
        "- key_triggers and invalidation_signals are arrays of concise strings.\n"
        "- Never nest output inside analysis/result/market_regime_timing."
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n"
        "As of: ${as_of}\n\n"
        "Macro context payload:\n${macro_context}\n\n"
        "Macro LLM payload, if available:\n${macro_payload}\n\n"
        "Deterministic technical feature payload:\n${technical_payload}\n\n"
        "Sentiment / fund-flow proxy payload, if available:\n${sentiment_payload}\n\n"
        "Return EXACTLY this JSON shape (keep keys verbatim):\n"
        "{\n"
        "  \"timing_view\": "
        "\"favorable|neutral|fragile|avoid_chasing|de_risk_watch\",\n"
        "  \"horizon\": \"1-3 months|3-6 months|6-12 months\",\n"
        "  \"macro_regime\": \"<macro regime or insufficient_data>\",\n"
        "  \"technical_state\": \"<technical state or insufficient_data>\",\n"
        "  \"sentiment_state\": \"<sentiment/fund-flow state or unknown>\",\n"
        "  \"key_triggers\": [\"<monitoring trigger>\"],\n"
        "  \"invalidation_signals\": [\"<signal that would weaken timing view>\"],\n"
        "  \"confidence\": 0.0,\n"
        "  \"needs_human_review\": true\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": [
            "timing_view",
            "horizon",
            "macro_regime",
            "technical_state",
            "sentiment_state",
            "key_triggers",
            "invalidation_signals",
            "confidence",
            "needs_human_review",
        ],
        "properties": {
            "timing_view": {
                "type": "string",
                "enum": [
                    "favorable",
                    "neutral",
                    "fragile",
                    "avoid_chasing",
                    "de_risk_watch",
                ],
            },
            "horizon": {
                "type": "string",
                "enum": ["1-3 months", "3-6 months", "6-12 months"],
            },
            "macro_regime": {"type": "string", "min_length": 2},
            "technical_state": {"type": "string", "min_length": 2},
            "sentiment_state": {"type": "string", "min_length": 2},
            "key_triggers": {
                "type": "array",
                "min_items": 1,
                "max_items": 10,
                "items": {
                    "type": "string",
                    "min_length": 3,
                    "max_length": 220,
                },
            },
            "invalidation_signals": {
                "type": "array",
                "min_items": 1,
                "max_items": 10,
                "items": {
                    "type": "string",
                    "min_length": 3,
                    "max_length": 220,
                },
            },
            "confidence": {"type": "number"},
            "needs_human_review": {"type": "boolean"},
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


@dataclass
class MarketRegimeTimingLLMAgent(Agent):
    """LLM agent for research-only market regime and timing labels."""

    llm_client: LLMClient
    name: str = "market_regime_timing_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = (
        "market_regime_timing_llm_finding",
        "market_regime_timing_payload",
    )
    max_tokens: int | None = 1100
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("MarketRegimeTimingLLMAgent requires an LLMClient")

    def run(
        self, context: AgentContext, store: FactStore
    ) -> AgentStepResult:
        warnings: list[str] = []
        if not isinstance(store.get("technical_feature_payload"), dict):
            warnings.append("fallback_context:technical_feature_payload")
        has_macro_payload = isinstance(store.get("macro_context_payload"), dict)
        has_macro_context = isinstance(store.get("macro_context"), dict)
        if not has_macro_payload and not has_macro_context:
            warnings.append("fallback_context:macro_context")

        system, user = MARKET_REGIME_TIMING_PROMPT.render(
            self._collect_variables(context, store)
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
            payload = MARKET_REGIME_TIMING_PROMPT.parse_response(
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

        finding = _market_regime_timing_finding_from_payload(
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
                "market_regime_timing_llm_finding": finding,
                "market_regime_timing_payload": payload,
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
            "macro_payload": _json_block(store.get("macro_context_payload")),
            "technical_payload": _json_block(
                store.get("technical_feature_payload")
            ),
            "sentiment_payload": _json_block(
                store.get("market_sentiment_payload")
            ),
        }


def _market_regime_timing_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    timing_view = str(payload.get("timing_view") or "neutral").strip()
    horizon = str(payload.get("horizon") or "3-6 months").strip()
    technical_state = str(payload.get("technical_state") or "unknown").strip()
    macro_regime = str(payload.get("macro_regime") or "unknown").strip()
    summary = (
        f"Timing view: {timing_view} over {horizon}. "
        f"Macro={macro_regime}; technical={technical_state}."
    )

    risks: list[str] = []
    if timing_view in {"fragile", "avoid_chasing", "de_risk_watch"}:
        risks.append(f"[timing_view] {timing_view}")
    for signal in payload.get("invalidation_signals") or []:
        text = str(signal).strip()
        if text:
            risks.append(f"[invalidation] {text}")

    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    evidence = (
        Evidence(
            claim=(
                "Market regime/timing analysis produced by "
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
        needs_human_review=bool(payload.get("needs_human_review", True)),
    )


MARKET_EXPECTATIONS_PROMPT = StructuredPrompt(
    name="market_expectations",
    tags=("market", "valuation", "expectations", "llm"),
    system=(
        "You are a biotech market-expectations analyst. Your job is to "
        "explain what the current market value appears to imply before any "
        "research memo labels the stock cheap or expensive. You bridge "
        "valuation-pod outputs, conservative rNPV, current market cap, macro "
        "context, technical features, and timing labels.\n\n"
        "Ground rules:\n"
        "- Work only from provided payloads. Do NOT invent prices, peer "
        "multiples, historical bands, deal terms, or catalyst dates.\n"
        "- Current price is not proof of fair value.\n"
        "- Conservative rNPV below current market value is not by itself "
        "overvaluation for a biotech company.\n"
        "- Explicitly name which strategic economics, BD/licensing, platform, "
        "commercialization, catalyst-window, or liquidity assumptions would "
        "need to be true for the market value to make sense. If an assumption "
        "is not evidenced in the inputs, label it as an evidence gap.\n"
        "- No trading instructions. Do NOT say buy, sell, enter, exit, stop "
        "loss, or position size.\n\n"
        "OUTPUT RULES (must follow exactly):\n"
        "- Return a single JSON object at the TOP LEVEL. No wrapper keys.\n"
        "- Required keys: market_implied_assumptions, valuation_band_context, "
        "rnpv_gap_explanation, expectation_risk_flags, evidence_gaps, "
        "confidence, needs_human_review.\n"
        "- valuation_band_context is exactly one of: historical_floor, "
        "mid_band, extended_band, unknown.\n"
        "- Arrays must contain concise strings.\n"
        "- Never nest output inside analysis/result/market_expectations."
    ),
    user_template=(
        "Company: ${company}\n"
        "Ticker: ${ticker}\n"
        "Market: ${market}\n"
        "As of: ${as_of}\n\n"
        "Valuation snapshot:\n${valuation_snapshot}\n\n"
        "Target-price snapshot:\n${target_price_snapshot}\n\n"
        "Valuation pod payloads:\n${valuation_pod_payloads}\n\n"
        "Macro context payload:\n${macro_context}\n\n"
        "Technical feature payload:\n${technical_payload}\n\n"
        "Market-regime/timing payload:\n${timing_payload}\n\n"
        "Catalyst payload, if available:\n${catalyst_payload}\n\n"
        "Scorecard summary:\n${scorecard_summary}\n\n"
        "Return EXACTLY this JSON shape (keep keys verbatim):\n"
        "{\n"
        "  \"market_implied_assumptions\": [\"<assumption implied by market value>\"],\n"
        "  \"valuation_band_context\": \"historical_floor|mid_band|extended_band|unknown\",\n"
        "  \"rnpv_gap_explanation\": \"<why the gap vs conservative rNPV may or may not be justified>\",\n"
        "  \"expectation_risk_flags\": [\"<risk that priced-in expectations are too high>\"],\n"
        "  \"evidence_gaps\": [\"<missing evidence needed before calling value fair/cheap/expensive>\"],\n"
        "  \"confidence\": 0.0,\n"
        "  \"needs_human_review\": true\n"
        "}"
    ),
    schema={
        "type": "object",
        "required": [
            "market_implied_assumptions",
            "valuation_band_context",
            "rnpv_gap_explanation",
            "expectation_risk_flags",
            "evidence_gaps",
            "confidence",
            "needs_human_review",
        ],
        "properties": {
            "market_implied_assumptions": {
                "type": "array",
                "min_items": 1,
                "max_items": 12,
                "items": {
                    "type": "string",
                    "min_length": 3,
                    "max_length": 260,
                },
            },
            "valuation_band_context": {
                "type": "string",
                "enum": [
                    "historical_floor",
                    "mid_band",
                    "extended_band",
                    "unknown",
                ],
            },
            "rnpv_gap_explanation": {
                "type": "string",
                "min_length": 6,
                "max_length": 700,
            },
            "expectation_risk_flags": {
                "type": "array",
                "max_items": 12,
                "items": {
                    "type": "string",
                    "min_length": 3,
                    "max_length": 260,
                },
            },
            "evidence_gaps": {
                "type": "array",
                "max_items": 12,
                "items": {
                    "type": "string",
                    "min_length": 3,
                    "max_length": 260,
                },
            },
            "confidence": {"type": "number"},
            "needs_human_review": {"type": "boolean"},
        },
    },
)


@dataclass
class MarketExpectationsLLMAgent(Agent):
    """LLM agent that explains market-implied biotech valuation assumptions."""

    llm_client: LLMClient
    name: str = "market_expectations_llm_agent"
    depends_on: tuple[str, ...] = ()
    produces: tuple[str, ...] = (
        "market_expectations_llm_finding",
        "market_expectations_payload",
    )
    max_tokens: int | None = 1300
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if self.llm_client is None:
            raise ValueError("MarketExpectationsLLMAgent requires an LLMClient")

    def run(
        self, context: AgentContext, store: FactStore
    ) -> AgentStepResult:
        warnings: list[str] = []
        if not isinstance(store.get("valuation_snapshot"), dict):
            warnings.append("fallback_context:valuation_snapshot")
        if not isinstance(store.get("valuation_committee_payload"), dict):
            warnings.append("fallback_context:valuation_committee_payload")

        system, user = MARKET_EXPECTATIONS_PROMPT.render(
            self._collect_variables(context, store)
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
            payload = MARKET_EXPECTATIONS_PROMPT.parse_response(
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

        finding = _market_expectations_finding_from_payload(
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
                "market_expectations_llm_finding": finding,
                "market_expectations_payload": payload,
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
            "valuation_snapshot": _json_block(store.get("valuation_snapshot")),
            "target_price_snapshot": _json_block(
                store.get("target_price_snapshot")
            ),
            "valuation_pod_payloads": _json_block(
                {
                    "commercial": store.get("valuation_commercial_payload"),
                    "rnpv": store.get("valuation_rnpv_payload"),
                    "balance_sheet": store.get("valuation_balance_sheet_payload"),
                    "committee": store.get("valuation_committee_payload"),
                }
            ),
            "macro_context": _json_block(
                store.get("macro_context_payload")
                or store.get("macro_context")
            ),
            "technical_payload": _json_block(
                store.get("technical_feature_payload")
            ),
            "timing_payload": _json_block(
                store.get("market_regime_timing_payload")
            ),
            "catalyst_payload": _json_block(
                store.get("catalyst_payload")
                or store.get("catalyst_calendar_payload")
            ),
            "scorecard_summary": _json_block(store.get("scorecard_summary")),
        }


def _market_expectations_finding_from_payload(
    *,
    payload: dict[str, Any],
    agent_name: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> AgentFinding:
    band = str(payload.get("valuation_band_context") or "unknown").strip()
    gap = str(payload.get("rnpv_gap_explanation") or "").strip()
    if gap:
        summary = f"Market expectations: {band}. {gap}"
    else:
        summary = f"Market expectations: {band}."

    risks: list[str] = []
    if band in {"extended_band", "unknown"}:
        risks.append(f"[valuation_band_context] {band}")
    for line in payload.get("market_implied_assumptions") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[market_implied_assumption] {text}")
    for line in payload.get("expectation_risk_flags") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[expectation_risk] {text}")
    for line in payload.get("evidence_gaps") or []:
        text = str(line).strip()
        if text:
            risks.append(f"[evidence_gap] {text}")

    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    evidence = (
        Evidence(
            claim=(
                "Market-expectations analysis produced by "
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
        needs_human_review=bool(payload.get("needs_human_review", True)),
    )


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
        "港股创新药公司估值不能把保守rNPV当作唯一公允价值。"
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
        "角色硬约束:\n"
        "- valuation-commercial-agent: 只评估已商业化产品、经常性收入、"
        "launch ramp或已确认的milestone/royalty收入；如果没有收入证据，"
        "返回0贡献或低置信度，不得改用rNPV。\n"
        "- valuation-pipeline-rnpv-agent: 只评估管线rNPV，必须引用输入中的"
        "PoS、峰值销售、上市时间和权益假设；不得创造新数字。\n"
        "- valuation-balance-sheet-agent: 只做净现金、债务、非经营资产调整，"
        "method必须为balance_sheet_adjustment，不得评估经营或管线资产。\n"
        "- valuation-committee-agent: 不要把保守rNPV写成唯一合理股价；"
        "请区分conservative_rnpv_floor、market_implied_value和"
        "scenario_repricing_range，并解释市场溢价是否有证据支持。\n\n"
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
        "  \"value_type\": \"<per_share|equity_value>\",\n"
        "  \"unit_basis\": \"<reported|normalized>\",\n"
        "  \"fx_assumption\": \"<汇率说明>\",\n"
        "  \"shares_outstanding_used\": 0.0,\n"
        "  \"conservative_rnpv_floor\": \"<仅committee填写，可空>\",\n"
        "  \"market_implied_value\": \"<仅committee填写，可空>\",\n"
        "  \"scenario_repricing_range\": \"<仅committee填写，可空>\",\n"
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
            "value_type": {
                "type": "string",
                "enum": ["per_share", "equity_value"],
            },
            "unit_basis": {"type": "string", "min_length": 2},
            "fx_assumption": {"type": "string", "min_length": 2},
            "shares_outstanding_used": {"type": ["number", "null"]},
            "conservative_rnpv_floor": {
                "type": ["string", "object", "null"],
            },
            "market_implied_value": {
                "type": ["string", "object", "null"],
            },
            "scenario_repricing_range": {
                "type": ["string", "object", "null"],
            },
            "sotp_bridge": {
                "type": "array",
                "items": {
                    "type": ["string", "object"],
                },
                "max_items": 20,
            },
            "method_weights": {
                "type": "array",
                "items": {
                    "type": ["string", "object"],
                },
                "max_items": 10,
            },
            "conflict_resolution": {
                "type": "array",
                "items": {
                    "type": ["string", "object"],
                },
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
            payload = _normalize_valuation_payload(
                payload=payload,
                component=self.role,
                valuation_snapshot=store.get("valuation_snapshot"),
            )
            payload = _coerce_valuation_role_payload(
                payload=payload,
                role=self.role,
                financials_snapshot=store.get("financials_snapshot"),
                valuation_snapshot=store.get("valuation_snapshot"),
            )
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

    def run(self, context: AgentContext, store: FactStore) -> AgentStepResult:
        step = super().run(context, store)
        if not step.ok:
            return step
        payload = step.outputs.get(self.payload_output_key)
        if not isinstance(payload, dict):
            return step
        enriched = _enrich_committee_payload_from_sub_agents(
            payload=payload,
            commercial_payload=store.get("valuation_commercial_payload"),
            rnpv_payload=store.get("valuation_rnpv_payload"),
            balance_sheet_payload=store.get("valuation_balance_sheet_payload"),
            valuation_snapshot=store.get("valuation_snapshot"),
        )
        finding = _valuation_pod_finding_from_payload(
            payload=enriched,
            agent_name=self.name,
            model=_finding_model_hint(step.finding),
            prompt_tokens=None,
            completion_tokens=None,
        )
        return AgentStepResult(
            agent_name=step.agent_name,
            finding=finding,
            outputs={
                **step.outputs,
                self.finding_output_key: finding,
                self.payload_output_key: enriched,
            },
            warnings=step.warnings,
            error=step.error,
            skipped=step.skipped,
            latency_ms=step.latency_ms,
        )


REPORT_QUALITY_PROMPT = StructuredPrompt(
    name="report_quality",
    tags=("report", "quality", "llm"),
    system=(
        "你是独立报告质量审阅员。"
        "仅审查一致性、证据充分性、语言质量与估值口径一致性。"
        "对创新药biotech，保守rNPV低于市价本身不是hard_error；"
        "只有数学断裂、单位错误、双重计算、缺失关键证据或把rNPV误写成"
        "唯一公允价值时才升级。"
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
        "估值标准化结果:\n${normalized_valuation}\n\n"
        "审阅规则:\n"
        "- 若问题只是缺少战略经济/市场预期解释，优先给review_required，"
        "不要直接block。\n"
        "- 若commercial/rNPV/balance_sheet重复同一估值范围，或"
        "balance_sheet使用rNPV方法，应作为估值口径问题。\n"
        "- 若报告把保守rNPV写成唯一合理股价，请列入"
        "valuation_coherence_findings。\n\n"
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
        "  \"issue_classification\": [\n"
        "    {\"issue\": \"<简述>\", \"severity\": \"<hard_error|soft_warning>\", \"rationale\": \"<原因>\"}\n"
        "  ],\n"
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
            "issue_classification": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["issue", "severity", "rationale"],
                    "properties": {
                        "issue": {"type": "string", "min_length": 1},
                        "severity": {
                            "type": "string",
                            "enum": ["hard_error", "soft_warning"],
                        },
                        "rationale": {"type": "string", "min_length": 1},
                    },
                },
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
    max_tokens: int | None = 1800
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
            "market_regime_timing": _finding_snapshot(
                store.get("market_regime_timing_llm_finding")
            ),
            "market_expectations": _finding_snapshot(
                store.get("market_expectations_llm_finding")
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
                "normalized_valuation": _json_block(
                    _normalized_valuation_for_review(store)
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
            payload = _postprocess_report_quality_payload(
                payload=payload,
                store=store,
            )
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
    for key in (
        "conservative_rnpv_floor",
        "market_implied_value",
        "scenario_repricing_range",
    ):
        value = payload.get(key)
        if value:
            risks.append(f"[{key}] {value}")

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
        "issue_classification": [
            {
                "issue": "report_quality_unavailable",
                "severity": "hard_error",
                "rationale": reason,
            }
        ],
        "confidence": 0.2,
    }


def _finding_model_hint(finding: AgentFinding | None) -> str:
    if finding is None:
        return "unknown"
    for ev in finding.evidence:
        if ev.source.startswith("llm:"):
            return ev.source.removeprefix("llm:")
    return "unknown"


def _enrich_committee_payload_from_sub_agents(
    *,
    payload: dict[str, Any],
    commercial_payload: Any,
    rnpv_payload: Any,
    balance_sheet_payload: Any,
    valuation_snapshot: Any,
) -> dict[str, Any]:
    enriched = dict(payload)
    components: list[tuple[str, dict[str, Any]]] = []
    for name, item in (
        ("rnpv", rnpv_payload),
        ("commercial", commercial_payload),
        ("balance_sheet", balance_sheet_payload),
    ):
        if isinstance(item, dict):
            components.append((name, item))
    if not components:
        return enriched

    bridge: list[dict[str, Any]] = []
    currencies: set[str] = set()
    bear_total = 0.0
    base_total = 0.0
    bull_total = 0.0
    abs_base_total = 0.0
    shares_outstanding = None
    if isinstance(valuation_snapshot, dict):
        shares_outstanding = _safe_float(
            valuation_snapshot.get("shares_outstanding")
        )
    seen_signatures: set[tuple[float, float, float]] = set()
    conflicts: list[dict[str, Any]] = []
    for component_name, component_payload in components:
        bear, base, bull = _valuation_range_tuple(component_payload)
        value_type = str(
            component_payload.get("value_type") or "equity_value"
        ).strip()
        currency = str(component_payload.get("currency") or "HKD").upper()
        fx_rate_to_hkd = _currency_to_hkd_rate(currency, valuation_snapshot)
        unit_basis = "equity_value"
        if (
            value_type == "per_share"
            and shares_outstanding
            and shares_outstanding > 0
        ):
            bear *= shares_outstanding
            base *= shares_outstanding
            bull *= shares_outstanding
            unit_basis = "per_share_to_equity"
            conflicts.append(
                {
                    "conflict": "unit_basis_normalized",
                    "resolution": (
                        f"{component_name} range scaled by shares_outstanding"
                    ),
                    "rationale": (
                        "component range appears to be per-share; converted "
                        "to equity value before SOTP aggregation"
                    ),
                }
            )
        currencies.add(currency)
        method = str(component_payload.get("method") or "").strip()
        contribution_allowed = True
        expected_methods = {
            "balance_sheet": {"balance_sheet_adjustment"},
        }
        expected = expected_methods.get(component_name, set())
        if expected and method not in expected:
            contribution_allowed = False
            conflicts.append(
                {
                    "conflict": "component_method_mismatch",
                    "resolution": (
                        f"{component_name} contribution is excluded from SOTP total"
                    ),
                    "rationale": (
                        f"{component_name} expected one of {sorted(expected)}, "
                        f"got {method or 'unknown'}"
                    ),
                }
            )
        elif component_name in {"commercial", "rnpv"}:
            preferred_methods = {
                "commercial": {"multiple", "dcf_simple", "sum_of_parts"},
                "rnpv": {"rNPV"},
            }
            preferred = preferred_methods.get(component_name, set())
            if method and preferred and method not in preferred:
                conflicts.append(
                    {
                        "conflict": "component_method_mismatch",
                        "resolution": (
                            f"{component_name} kept with caution in committee total"
                        ),
                        "rationale": (
                            f"{component_name} preferred methods are "
                            f"{sorted(preferred)}, got {method}"
                        ),
                    }
                )

        if component_name == "balance_sheet" and not contribution_allowed:
            # Deterministic fallback: net cash/debt adjustment from valuation snapshot.
            det_bear, det_base, det_bull = _deterministic_balance_sheet_adjustment(
                valuation_snapshot
            )
            if det_base != 0.0:
                bear, base, bull = det_bear, det_base, det_bull
                method = "balance_sheet_adjustment(deterministic_fallback)"
                contribution_allowed = True
                conflicts.append(
                    {
                        "conflict": "balance_sheet_llm_method_invalid",
                        "resolution": "fallback to deterministic net cash/debt adjustment",
                        "rationale": "preserve additive adjustment in committee bridge",
                    }
                )

        converted_bear = bear * fx_rate_to_hkd
        converted_base = base * fx_rate_to_hkd
        converted_bull = bull * fx_rate_to_hkd
        signature = (
            round(converted_bear, 4),
            round(converted_base, 4),
            round(converted_bull, 4),
        )
        if contribution_allowed and signature in seen_signatures:
            contribution_allowed = False
            conflicts.append(
                {
                    "conflict": "duplicate_component_valuation_range",
                    "resolution": (
                        f"{component_name} contribution is excluded to avoid double count"
                    ),
                    "rationale": (
                        "another component already contributes the same "
                        f"(bear, base, bull) range {signature}"
                    ),
                }
            )
        seen_signatures.add(signature)

        base_contribution = base if contribution_allowed else 0.0
        bridge.append(
            {
                "component": component_name,
                "method": method,
                "bear": bear,
                "base": base,
                "bull": bull,
                "currency": currency,
                "value_type": value_type,
                "unit_basis": unit_basis,
                "fx_to_hkd": fx_rate_to_hkd,
                "bear_hkd": round(converted_bear, 4),
                "base_hkd": round(converted_base, 4),
                "bull_hkd": round(converted_bull, 4),
                "value_contribution": base_contribution * fx_rate_to_hkd,
                "contribution_allowed": contribution_allowed,
            }
        )
        if contribution_allowed:
            bear_total += converted_bear
            base_total += converted_base
            bull_total += converted_bull
            abs_base_total += abs(converted_base)

    weights: list[dict[str, Any]] = []
    for row in bridge:
        base = float(row.get("value_contribution") or 0.0)
        allowed = bool(row.get("contribution_allowed"))
        if not allowed:
            weights.append(
                {
                    "component": row.get("component"),
                    "weight": 0.0,
                }
            )
            continue
        if abs_base_total > 0:
            weight = abs(base) / abs_base_total
        else:
            weight = 1.0 / max(1, len(bridge))
        weights.append(
            {
                "component": row.get("component"),
                "weight": round(weight, 4),
            }
        )

    if len(currencies) > 1:
        conflicts.append(
            {
                "conflict": "currency_mismatch_between_valuation_components",
                "resolution": "committee normalizes totals to HKD for reporting",
                "rationale": (
                    "mixed currencies detected across valuation sub-agents: "
                    + ", ".join(sorted(currencies))
                ),
            }
        )
    if bear_total > bull_total:
        conflicts.append(
            {
                "conflict": "valuation_range_ordering_inverted",
                "resolution": "committee reorders totals into bear<=base<=bull",
                "rationale": "aggregated range violated monotonic ordering",
            }
        )
        ordered = sorted((bear_total, base_total, bull_total))
        bear_total, base_total, bull_total = ordered[0], ordered[1], ordered[2]

    enriched["method"] = "sotp_committee"
    enriched["scope"] = "sotp_committee_full_company"
    enriched["currency"] = "HKD"
    enriched["sotp_bridge"] = bridge
    enriched["method_weights"] = weights
    enriched["conflict_resolution"] = conflicts
    enriched["valuation_range"] = {
        "bear": round(bear_total, 2),
        "base": round(base_total, 2),
        "bull": round(bull_total, 2),
    }
    enriched["final_equity_value_range"] = dict(enriched["valuation_range"])
    if shares_outstanding and shares_outstanding > 0:
        per_share_bear = bear_total / shares_outstanding
        per_share_base = base_total / shares_outstanding
        per_share_bull = bull_total / shares_outstanding
        enriched["final_per_share_range"] = {
            "bear": _preserve_small_value(per_share_bear),
            "base": _preserve_small_value(per_share_base),
            "bull": _preserve_small_value(per_share_bull),
        }
    else:
        enriched["final_per_share_range"] = dict(enriched["valuation_range"])
        conflicts.append(
            {
                "conflict": "missing_or_invalid_shares_outstanding",
                "resolution": (
                    "fallback to equity value range for final_per_share_range"
                ),
                "rationale": "shares_outstanding unavailable or non-positive",
            }
        )
    conservative_floor = _committee_floor_from_bridge(
        bridge=bridge,
        shares_outstanding=shares_outstanding,
    )
    market_cap = _extract_numeric(valuation_snapshot, "market_cap")
    premium_to_floor = None
    floor_base = _safe_float(conservative_floor.get("base"))
    if market_cap > 0 and floor_base > 0:
        premium_to_floor = round((market_cap / floor_base) - 1.0, 4)
    enriched["conservative_rnpv_floor"] = conservative_floor
    enriched["market_implied_value"] = {
        "market_cap": market_cap or None,
        "currency": "HKD",
        "premium_to_conservative_floor": premium_to_floor,
        "interpretation": (
            "Current market value may include strategic economics, BD, "
            "platform optionality when evidenced, catalyst-window premium, "
            "and sector liquidity. These require separate agent support in "
            "Stage B."
        ),
    }
    enriched["scenario_repricing_range"] = {
        "bear": enriched["valuation_range"]["bear"],
        "base": enriched["valuation_range"]["base"],
        "bull": enriched["valuation_range"]["bull"],
        "currency": "HKD",
        "basis": "committee_current_components_before_stage_b_market_premium",
    }
    return enriched


def _valuation_range_tuple(payload: dict[str, Any]) -> tuple[float, float, float]:
    raw = payload.get("valuation_range")
    if not isinstance(raw, dict):
        return (0.0, 0.0, 0.0)
    return (
        _safe_float(raw.get("bear")),
        _safe_float(raw.get("base")),
        _safe_float(raw.get("bull")),
    )


def _committee_floor_from_bridge(
    *,
    bridge: list[dict[str, Any]],
    shares_outstanding: float | None,
) -> dict[str, Any]:
    bear = 0.0
    base = 0.0
    bull = 0.0
    for row in bridge:
        if row.get("component") not in {"rnpv", "balance_sheet"}:
            continue
        if not bool(row.get("contribution_allowed")):
            continue
        bear += _safe_float(row.get("bear_hkd"))
        base += _safe_float(row.get("base_hkd"))
        bull += _safe_float(row.get("bull_hkd"))
    result: dict[str, Any] = {
        "bear": round(bear, 2),
        "base": round(base, 2),
        "bull": round(bull, 2),
        "currency": "HKD",
        "basis": "rnpv_plus_balance_sheet_only",
    }
    if shares_outstanding and shares_outstanding > 0:
        result["per_share"] = {
            "bear": _preserve_small_value(bear / shares_outstanding),
            "base": _preserve_small_value(base / shares_outstanding),
            "bull": _preserve_small_value(bull / shares_outstanding),
        }
    return result


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _extract_numeric(mapping: Any, *keys: str) -> float:
    if not isinstance(mapping, dict):
        return 0.0
    for key in keys:
        value = mapping.get(key)
        parsed = _safe_float(value)
        if parsed != 0.0:
            return parsed
    for nested_key in (
        "snapshot",
        "metrics",
        "financials",
        "financial_snapshot",
        "market_snapshot",
        "runway_estimate",
        "valuation_metrics",
    ):
        nested = mapping.get(nested_key)
        parsed = _extract_numeric(nested, *keys)
        if parsed != 0.0:
            return parsed
    return 0.0


def _has_commercial_revenue(financials_snapshot: Any) -> bool:
    revenue = _extract_numeric(
        financials_snapshot,
        "revenue_ttm",
        "total_revenue",
        "revenue",
        "product_revenue",
        "sales",
        "turnover",
    )
    return revenue > 0


def _coerce_valuation_role_payload(
    *,
    payload: dict[str, Any],
    role: str,
    financials_snapshot: Any,
    valuation_snapshot: Any,
) -> dict[str, Any]:
    coerced = dict(payload)
    if role == "valuation-commercial-agent" and not _has_commercial_revenue(
        financials_snapshot
    ):
        coerced["method"] = "multiple"
        coerced["scope"] = (
            "commercialized_products_and_recurring_revenue; no commercial "
            "revenue evidence in current inputs"
        )
        coerced["valuation_range"] = {"bear": 0.0, "base": 0.0, "bull": 0.0}
        coerced["currency"] = str(coerced.get("currency") or "HKD").upper()
        coerced["value_type"] = "equity_value"
        coerced["unit_basis"] = "no_revenue_zero_commercial_contribution"
        coerced["needs_human_review"] = True
        coerced["confidence"] = min(_safe_float(coerced.get("confidence")), 0.35)
        assumptions = list(coerced.get("assumptions") or [])
        assumptions.append(
            "No recurring/product revenue found; commercial agent must not "
            "fall back to pipeline rNPV."
        )
        coerced["assumptions"] = assumptions[:12]
    elif role == "valuation-balance-sheet-agent":
        net_cash = _deterministic_balance_sheet_adjustment(valuation_snapshot)
        if net_cash == (0.0, 0.0, 0.0):
            net_cash = _deterministic_balance_sheet_adjustment(
                financials_snapshot
            )
        coerced["method"] = "balance_sheet_adjustment"
        coerced["scope"] = "net_cash_debt_and_non_operating_adjustments_only"
        coerced["valuation_range"] = {
            "bear": net_cash[0],
            "base": net_cash[1],
            "bull": net_cash[2],
        }
        coerced["currency"] = "HKD"
        coerced["value_type"] = "equity_value"
        coerced["unit_basis"] = "deterministic_balance_sheet_adjustment"
        coerced["needs_human_review"] = bool(coerced.get("needs_human_review", True))
        assumptions = list(coerced.get("assumptions") or [])
        assumptions.append(
            "Balance-sheet agent is constrained to net cash/debt adjustments "
            "and must not price pipeline or operating assets."
        )
        coerced["assumptions"] = assumptions[:12]
    return coerced


def _deterministic_balance_sheet_adjustment(
    valuation_snapshot: Any,
) -> tuple[float, float, float]:
    if not isinstance(valuation_snapshot, dict):
        return (0.0, 0.0, 0.0)
    cash = _extract_numeric(
        valuation_snapshot,
        "cash",
        "cash_and_equivalents",
        "cash_and_cash_equivalents",
    )
    debt = _extract_numeric(valuation_snapshot, "total_debt", "debt")
    if debt == 0.0:
        debt = _extract_numeric(
            valuation_snapshot,
            "short_term_debt",
        ) + _extract_numeric(
            valuation_snapshot,
            "long_term_debt",
        )
    net = cash - debt
    return (net, net, net)


def _preserve_small_value(value: float) -> float:
    rounded = round(value, 6)
    if rounded != 0.0:
        return rounded
    return value


def _currency_to_hkd_rate(currency: str, valuation_snapshot: Any) -> float:
    normalized = (currency or "HKD").strip().upper()
    if normalized == "HKD":
        return 1.0
    if normalized in {"CNY", "RMB"}:
        inferred = 1.1
        if isinstance(valuation_snapshot, dict):
            for key in (
                "fx_cny_hkd",
                "fx_rmb_hkd",
                "cny_to_hkd",
                "rmb_to_hkd",
            ):
                candidate = _safe_float(valuation_snapshot.get(key))
                if candidate > 0:
                    inferred = candidate
                    break
        return inferred
    return 1.0


def _normalize_valuation_payload(
    *,
    payload: dict[str, Any],
    component: str,
    valuation_snapshot: Any,
) -> dict[str, Any]:
    normalized = dict(payload)
    method = str(normalized.get("method") or "").strip()
    value_type = str(normalized.get("value_type") or "").strip()
    if not value_type:
        if method in {"rNPV", "multiple", "dcf_simple"}:
            value_type = "per_share"
        else:
            value_type = "equity_value"
    currency = str(normalized.get("currency") or "HKD").strip().upper()
    normalized["currency"] = currency
    normalized["value_type"] = value_type
    normalized["unit_basis"] = str(
        normalized.get("unit_basis") or "reported_by_sub_agent"
    ).strip()
    fx = _currency_to_hkd_rate(currency, valuation_snapshot)
    normalized["fx_assumption"] = str(
        normalized.get("fx_assumption")
        or f"1 {currency} = {fx} HKD (deterministic default)"
    ).strip()
    shares = None
    if isinstance(valuation_snapshot, dict):
        shares = _safe_float(valuation_snapshot.get("shares_outstanding"))
    raw_shares = normalized.get("shares_outstanding_used")
    parsed_raw_shares = _safe_float(raw_shares)
    if parsed_raw_shares > 0:
        normalized["shares_outstanding_used"] = parsed_raw_shares
    elif shares and shares > 0:
        normalized["shares_outstanding_used"] = shares
    else:
        normalized["shares_outstanding_used"] = None

    # Committee output is always a normalized aggregation product.
    if component == "valuation-committee-agent":
        normalized["value_type"] = "equity_value"
        normalized["unit_basis"] = "committee_normalized_hkd_equity_value"
    return normalized


def _normalized_valuation_for_review(store: FactStore) -> dict[str, Any]:
    snapshot = store.get("valuation_snapshot")
    return {
        "commercial": _normalize_valuation_payload(
            payload=dict(store.get("valuation_commercial_payload") or {}),
            component="valuation-commercial-agent",
            valuation_snapshot=snapshot,
        ),
        "rnpv": _normalize_valuation_payload(
            payload=dict(store.get("valuation_rnpv_payload") or {}),
            component="valuation-pipeline-rnpv-agent",
            valuation_snapshot=snapshot,
        ),
        "balance_sheet": _normalize_valuation_payload(
            payload=dict(store.get("valuation_balance_sheet_payload") or {}),
            component="valuation-balance-sheet-agent",
            valuation_snapshot=snapshot,
        ),
        "committee": _normalize_valuation_payload(
            payload=dict(store.get("valuation_committee_payload") or {}),
            component="valuation-committee-agent",
            valuation_snapshot=snapshot,
        ),
    }


def _postprocess_report_quality_payload(
    *,
    payload: dict[str, Any],
    store: FactStore,
) -> dict[str, Any]:
    normalized = dict(payload)
    gate = str(normalized.get("publish_gate") or "review_required").strip()
    if gate != "block":
        return normalized

    issue_classification = normalized.get("issue_classification")
    hard_count = 0
    if isinstance(issue_classification, list):
        for item in issue_classification:
            if isinstance(item, dict) and item.get("severity") == "hard_error":
                hard_count += 1

    if hard_count == 0:
        texts: list[str] = []
        for key in (
            "critical_issues",
            "consistency_findings",
            "missing_evidence_findings",
            "language_quality_findings",
            "valuation_coherence_findings",
        ):
            texts.extend(str(x) for x in (normalized.get(key) or []))
        combined = " ".join(texts).lower()
        hard_tokens = (
            "计算",
            "公式",
            "加总",
            "单位",
            "currency",
            "fx",
            "冲突",
            "不一致",
            "断裂",
            "漏算",
            "double count",
            "shares",
        )
        has_hard_signal = any(token in combined for token in hard_tokens)
        if not has_hard_signal:
            normalized["publish_gate"] = "review_required"
            fixes = list(normalized.get("recommended_fixes") or [])
            fixes.append(
                "deterministic gate override: downgrade block to review_required "
                "because only soft warnings were detected"
            )
            normalized["recommended_fixes"] = fixes

    committee_payload = store.get("valuation_committee_payload")
    if isinstance(committee_payload, dict):
        normalized["committee_unit_basis"] = committee_payload.get("unit_basis")
    return normalized


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
