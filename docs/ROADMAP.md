# Roadmap

## Product Thesis

Build an AI-assisted research system for long-term investing in innovative
drug companies, where multiple LLM agents collaborate with deterministic
pipelines to produce auditable investment analysis.

The design target is a graph of agents with clearly separated responsibilities
— data collection, cleansing, pipeline triage, clinical trials, financial
triage, competitive landscape, valuation, K-line / technical timing, macro
context, and scientific skeptic — all writing into a shared, traceable fact
store and producing `AgentFinding` outputs with source, severity, and
confidence. HK biotech is the first vertical we harden, not the endgame.

## MVP Strategy

The near-term priority remains a working Hong Kong biotech MVP. Future
expansion to other HK sectors, US stocks, and A-shares should influence
module boundaries, but it should not distract the current implementation.

Design rules for new work:

- Keep core orchestration company-, market-, and sector-aware.
- Put biotech-specific concepts behind industry boundaries.
- Put HKEX-specific discovery and filing logic behind market boundaries.
- Preserve curated JSON contracts because future auto-extraction can populate
  the same contracts.
- Prefer one-command workflows for users, while keeping lower-level commands
  for debugging and reproducibility.
- Every LLM call is audited via `LLMTraceRecorder` and budget-capped.
- LLM agents must always be opt-in; deterministic path must continue to
  produce a useful first-pass report with zero network-LLM traffic.

## Milestone A: One-Command HK Biotech Report

Status: started. The `company-report` command resolves a company identity,
auto-discovers existing curated input files, runs the current single-company
research pipeline, writes artifacts, and emits a missing-input report.

- Accept company name or ticker.
- Read optional local company registry aliases.
- Auto-discover curated inputs under `data/input`.
- Run a useful first-pass report even when curated inputs are missing.
- Write `missing_inputs_report.json` so the next pass can be upgraded.

## Milestone B: HK Biotech Source Pack

Status: started. The first implementation discovers HKEX annual results
announcements, downloads the PDF, extracts text, and drafts pipeline and
financial inputs for Hong Kong biotech reports.

- Discover HKEX announcements, annual reports, interim reports, results
  announcements, company investor pages, and trial registries.
- Save source manifests before extraction.
- Keep source discovery separate from biotech analysis.

## Milestone C: Auto-Extract Into Current Contracts

Status: started for pipeline and financial drafts from HKEX annual results.

- Extract draft pipeline assets, financial snapshots, valuation snapshots,
  competitor seeds, and target-price assumption skeletons from source packs.
- Mark low-confidence fields for review.
- Keep generated drafts compatible with existing validators.

## Milestone D: Validation-Centric Report

Status: planned.

- Distinguish official-source facts, model-inferred values, missing inputs, and
  human-review fields in every report.
- Block or downgrade conclusions when critical inputs are missing.
- Preserve report reproducibility through manifests and evidence records.

## Phase 0: Repository Foundation

Status: implemented.

- Define project scope.
- Document agent contracts.
- Create lightweight Python package.
- Verify ClinicalTrials.gov access.

## Phase 1: Single Company Clinical Trial Research

Status: implemented for ClinicalTrials.gov.

- Search ClinicalTrials.gov by company and asset.
- Normalize trial records.
- Extract trial status, dates, phase, condition, and intervention.
- Produce a trial summary table.

## Phase 2: Pipeline Extraction

Status: partially implemented. Curated JSON inputs, validation, and
asset-trial matching exist. Automatic extraction from presentations and reports
is still pending.

- Add document ingestion for company presentations and reports.
- Extract pipeline assets into structured records.
- Match assets against trial records.
- Store evidence references.

## Phase 3: Catalyst Calendar

Status: partially implemented. The current CLI derives catalysts from future
ClinicalTrials.gov primary completion dates and curated asset milestones, then
writes a catalyst-calendar CSV.

- Generate expected catalyst windows from:
  - Primary completion dates
  - Company guidance
  - Regulatory milestones
  - Conferences
  - Earnings and annual results
- Add curated conference catalyst input contracts with explicit source type,
  confidence tags, and human-review flags.

## Phase 4: Cash Runway

Status: partially implemented. Curated financial snapshot JSON inputs,
validation, and first-pass runway calculation exist. Financial statement
parsing and scenario variants are pending.

- Parse financial statements.
- Estimate quarterly and annual cash burn.
- Calculate runway under base, optimistic, and conservative assumptions.

## Phase 5: Competitive Landscape

Status: partially implemented. Curated competitor asset JSON inputs,
validation, deterministic matching by target and indication, competitive
landscape findings, risks, and artifacts exist. Automatic competitor discovery,
data maturity comparison, efficacy/safety comparisons, and commercialization
analysis are pending.

- Group assets by target, mechanism, indication, and geography.
- Compare stage, data maturity, safety, efficacy, and commercialization status.
- Mark crowded targets and weak differentiation.

## Phase 6: Investment Memo

Status: partially implemented. The current memo combines clinical trials,
curated pipeline assets, deterministic asset-trial matches, derived catalysts,
cash runway, curated competitive landscape findings, valuation context, key
risks, evidence, and follow-up questions. A deterministic data-quality
finding flags missing inputs and validation warnings. A deterministic
skeptical review finding produces counter-thesis risks from current
structured inputs. An LLM-backed `ScientificSkepticLLMAgent` now augments
this via the new AgentGraph runtime (opt-in through `--llm-agents
scientific-skeptic`) and produces a structured counter-thesis with
per-risk severity. Deeper multi-agent critique is tracked in Phase 10.

- Combine pipeline, trial, catalyst, competition, cash runway, and valuation
  outputs.
- Generate a memo with bull case, bear case, evidence table, and watchlist
  decision.
- Surface LLM findings alongside deterministic ones when they are produced,
  without changing the default LLM-free behaviour.

## Phase 7: Portfolio Layer

Status: partially implemented. The current CLI emits a deterministic
single-company watchlist scorecard with dimension scores, a bucket, and
monitoring rules. It can also rank saved single-company runs into a local JSON
or CSV watchlist table with latest-run filtering, first-pass research-only
position sizing, and concentration guardrails. It can also compare each
company's latest two saved catalyst calendars for local change alerts. More
advanced portfolio controls are pending.

- Add watchlist scoring.
- Add local cross-run watchlist ranking.
- Add latest-run filtering for repeat company research runs.
- Add first-pass position sizing guardrails.
- Track first-pass concentration by company, market, target, and indication.
- Add first-pass alerting for catalyst changes.

## Phase 8: Catalyst-Adjusted Target Price Ranges

Status: implemented as a first-pass deterministic model. The current system has
catalyst calendars, catalyst-change alerts, curated valuation context,
watchlist guardrails, target-price assumption templates and validation, asset
rNPV calculation, event-impact deltas, target price ranges, standalone
`event-impact` CLI output, and optional research memo integration. Deeper
calibration and backtesting remain Phase 9 work.

- Add target-price assumptions template and validation.
- Add transparent asset rNPV calculation.
- Map catalyst alert types to probability, timing, peak-sales, or dilution
  assumption deltas.
- Generate bear, base, bull, and probability-weighted target price ranges.
- Write `event_impact.json`, `target_price_scenarios.json`, and
  `target_price_summary.csv` artifacts.
- Add `Catalyst-Adjusted Valuation` section to memos.
- Keep target-price outputs assumption-first and human-review gated.

## Phase 9: Technical Timing And Backtesting

Status: not started.

- Add market data ingestion.
- Add long-term technical trend analysis.
- Backtest watchlist entry rules.
- Backtest historical catalyst-event reactions and target-range calibration.
- Avoid look-ahead bias by using historical source snapshots.

## Phase 10: Multi-LLM Agent Runtime

Status: partially implemented. A custom lightweight `AgentGraph` runtime is
in place (`src/biotech_alpha/agent_runtime.py`) with a thread-safe
`FactStore`, topological layer scheduling, same-layer parallelism, and
per-agent error isolation. An OpenAI-compatible LLM adapter targets
Alibaba Bailian's `/compatible-mode/v1` endpoint with `qwen3.6-plus` as the
default model. A first LLM agent, `ScientificSkepticLLMAgent`, is wired
behind `company-report --llm-agents scientific-skeptic`. All LLM calls are
JSONL-traced with token counts, latency, and a run-level cost summary.

- **Done** — LLM adapter layer (config, client, trace, prompt templating,
  lightweight JSON-schema validation). Supports `DASHSCOPE_API_KEY` fallback
  and explicit `enable_thinking` control for Qwen3 models.
- **Done** — `AgentGraph` + `FactStore` + `Agent` + `DeterministicAgent`.
- **Done** — First LLM agent (`ScientificSkepticLLMAgent`) with strict
  top-level JSON shape, per-risk severity enum, and asset/evidence refs.
- **Done** — Second LLM agent (`PipelineTriageLLMAgent`): structured
  per-asset triage against the deterministic pipeline and source-text
  excerpts. Produces `coverage_confidence` plus per-asset severity
  (`none|low|medium|high`) with issues and suggested fixes. Composable
  with the skeptic under `--llm-agents pipeline-triage
  scientific-skeptic`; the skeptic's prompt renders the triage payload
  in a dedicated block so counter-thesis reasoning can cite it.
- **In progress** — Multi-anchor `source_text_excerpt` so triage coverage
  is not first-asset-only.
- **Not started** — Financial triage agent (burn-rate + runway cross-check).
- **Not started** — Macro context agent (sector / policy / rate-sensitivity
  narrative; feeds the skeptic via `FactStore`).
- **Not started** — Technical / K-line agent (long-horizon trend read on top
  of a future market-data pipeline).
- **Not started** — Orchestration fall-back: when an LLM agent fails schema
  validation three times, auto-downgrade to a shorter prompt variant or
  mark `needs_human_review=True` before giving up.
- **Not started** — Multi-model support: Claude adapter reusing
  `LLMConfig` / `OpenAICompatibleLLMClient` abstractions with provider
  routing by `model` prefix.
- **Not started** — Per-agent budget caps inside `LLMTraceRecorder` so a
  single runaway agent cannot exhaust the run budget.

## Next Execution Plan (Suggested)

The highest-priority path is to make one-command `company-report` reliable for
daily use with minimal manual prep.

**Doc discipline:** Each sprint below lists **implementation status** so this
section stays aligned with the repo. Update statuses when scope changes.

**Last status pass:** 2026-04-22 (match to `git` history for this file when in doubt).

### Sprint 1: Reliability And Coverage Baseline

**Sprint status:** in progress (core paths covered; HK fixture set started).

- **Done** — Expand and harden one-command tests for `company-report`, including
  missing-input fallback, `auto_inputs` success paths, `auto_inputs` exception
  fallback, manual-over-generated precedence, ticker-only identity, and
  conference input discovery.
  **Where:** `tests/test_company_report.py`, `tests/test_cli.py` (watchlist
  filter), `tests/test_research.py` (manifest quality gate).

- **Partially done** — Add fixture-based regression tests for representative HK
  biotech tickers to catch schema or parsing drift early. DualityBio covers the
  orchestration path; Harbour BioMed now covers a second HKEX disclosure style
  with USD financials and packed-table pipeline aliases. Broader representative
  ticker coverage remains open.

- **Done** — Standardize run-level quality gates in summaries and manifests so
  users can quickly see whether output is decision-ready; optional watchlist
  filtering by minimum gate.
  **Where:** `company_report_summary` / `missing_inputs_payload` and research
  run `manifest` (`quality_gate`), `watchlist-rank --min-quality-gate` in
  `src/biotech_alpha/cli.py` and `src/biotech_alpha/watchlist.py`.

### Sprint 2: Input Quality Upgrade

**Sprint status:** partially started (HKEX annual-results extraction exists;
resilience and validator tightening remain).

- **Partially done** — Improve HKEX source discovery robustness and retry
  behavior for annual-results fetch and extraction. Lightweight request retries
  exist; broader fallback source selection remains open.

- **Partially done** — Harden HKEX PDF text parsing for packed tables. Current
  extraction handles slash aliases with whitespace/newlines, local phase
  context, day-month financial dates, immediate-left table row fields, and
  USD/HKD/RMB thousand-unit statements. Remaining phase or undisclosed-target
  warnings are intentionally left for human review unless the source text
  clearly resolves them.

- **Partially done** — Extend generated draft inputs with clearer confidence
  tags and explicit `needs_human_review` markers (conference draft JSON from
  annual-results text exists; broader contracts still shallow).
  **Where:** `src/biotech_alpha/auto_inputs.py` (`draft_conference_catalysts`).

- **Not started** — Add stricter validators for placeholder values, stale dates,
  and missing evidence metadata (beyond current warning-only checks).

### Sprint 3: Research Depth Upgrade

**Sprint status:** partially started (curated conference path in; China registry
and web ingestion out).

- **Not started** — Add first-pass China trial registry ingestion to improve
  China-heavy program coverage.

- **Partially done** — Conference catalyst layer: curated JSON contract + CLI
  template/validate + research pipeline + memo section split + optional
  auto-draft from HKEX PDF text (not full public-web scraping).
  **Where:** `src/biotech_alpha/conference.py`, `src/biotech_alpha/research.py`,
  `src/biotech_alpha/auto_inputs.py`, `tests/test_conference.py`.

- **Not started** — Improve competitor intelligence from deterministic
  target/indication matching toward better data-maturity and differentiation
  checks.

- **Done (opt-in)** — Keep memo outputs deterministic-first while introducing
  a bounded, auditable scientific critique layer. `ScientificSkepticLLMAgent`
  runs only when `--llm-agents scientific-skeptic` is passed, uses a strict
  JSON schema, writes `data/memos/<run_id>_llm_findings.json` alongside a
  JSONL trace, and participates in the run-level cost summary. See Phase 10.

### Sprint 4: Multi-LLM Agent Collaboration

**Sprint status:** dual-agent collaboration landed on 2026-04-22. The
runtime + two distinct LLM agents (pipeline-triage -> scientific-skeptic)
now run in a single AgentGraph with shared facts, and the skeptic actually
consumes triage findings. Sprint continues with a third agent and coverage
improvements.

- **Done** — LLM + Agent runtime skeleton (config, client, trace, prompt,
  schema, FactStore, AgentGraph, opt-in CLI flag).
- **Done** — First LLM agent: `ScientificSkepticLLMAgent`.
- **Done** — Fix `discover_company_inputs` cross-ticker mis-match
  uncovered by the initial smoke.
- **Done** — `BIOTECH_ALPHA_LLM_DEBUG_PROMPT` env flag that dumps rendered
  prompts to `data/traces/<run>_<agent>_prompt.txt` for offline prompt
  debugging.
- **Done** — Second LLM agent: `PipelineTriageLLMAgent` with
  `source_text_excerpt` fact and in-graph chaining into the skeptic.
  Validated end-to-end via live Bailian Qwen3.6 dual-agent smoke
  (7298 total tokens, 2/2 calls OK, findings for both agents).
- **In progress** — Multi-anchor `source_text_excerpt`: today the window
  is anchored on the first matching asset name, which leaves later-listed
  assets marked `medium [not in excerpt]`. Next iteration produces one
  window per asset or a capped concatenated multi-anchor excerpt.
- **Not started** — `FinancialTriageLLMAgent`: burn-rate, runway, cash vs
  debt sanity. First non-pipeline-domain LLM agent and the real test
  that the agent graph is domain-agnostic.
- **Not started** — Add a Claude adapter so the runtime is not single-vendor.
- **Not started** — Per-agent LLM call budget cap.
