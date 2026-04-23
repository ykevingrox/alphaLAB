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

Status: started. Quality gates and validation warnings are now present in
report summaries, and quick reports expose and persist an extraction audit so
operators can see whether generated fields are source-supported, review-gated,
or missing source anchors.

- Distinguish official-source facts, model-inferred values, missing inputs, and
  human-review fields in every report.
- Block or downgrade conclusions when critical inputs are missing.
- Preserve report reproducibility through manifests and evidence records.
- Surface extraction support in operator output, JSON summaries, saved
  artifacts, and manifests.

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
landscape findings, risks, and artifacts exist. Auto-input now emits
heuristic competitor seed drafts from extracted target overlap to reduce
zero-competitor runs, while keeping all rows human-review flagged.
Data maturity comparison, efficacy/safety comparisons, and commercialization
analysis are pending. Seed drafting is now versioned and covers a
broader conservative HK-biotech target set, including BCMA/CD3,
CTLA-4, FcRn, TSLP, and normalized B7H4/B7-H4 composite matching,
while still marking generated competitors for human review and keeping
competitor indication as `to_verify`. Generated competitor drafts now also
emit source-backed discovery requests and can ingest review-gated global
discovery candidate packs. ClinicalTrials.gov is the first live source wired
to fill those packs.

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
Alibaba Bailian's `/compatible-mode/v1` endpoint with `qwen3.5-plus` as the
current development/default model. Five LLM agents are wired through
`company-report --llm-agents ...` and the quick `report "<company|ticker>"`
command enables the full stack by default. All LLM calls are JSONL-traced
with token counts, latency, and a run-level cost summary.

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
- **Done** — Multi-anchor `source_text_excerpt` so triage coverage is
  not first-asset-only. `_build_source_text_excerpt` now stitches one
  window per asset and exposes `anchor_assets` / `missing_assets`; the
  triage prompt tells the LLM to ignore assets absent from the text
  instead of flagging them.
- **Done** — Repeated-asset source excerpt ranking. When an asset name
  appears multiple times, `_build_source_text_excerpt` now prefers
  phase / IND / BLA / trial-rich windows and exposes `anchor_details`
  hit counts plus signal scores, so pipeline triage sees the same
  source-backed details used by deterministic extraction.
- **Done** — Third LLM agent (`FinancialTriageLLMAgent`): cross-checks
  cash / debt / burn rate / deterministic runway / market snapshot /
  currency alignment. Emits `runway_sanity` enum plus per-metric
  `findings[]` severity. Composable with both other agents; the
  skeptic's prompt renders the financial-triage payload in its own
  block alongside the pipeline-triage payload.
- **Done** — Fourth LLM agent (`MacroContextLLMAgent`): macro regime
  read with `macro_regime` enum
  (expansion / contraction / transition / insufficient_data),
  `sector_drivers[]`, `sector_headwinds[]`. Consumes a deterministic
  `macro_context` stub (market, sector, report-run date, source
  publication dates, `known_unknowns`). Prompt mandates
  `insufficient_data` when the stub is too thin, so the agent cannot
  hallucinate macro themes during the stub-only phase. Live smoke on
  09606.HK: 4/4 OK, 11919 tokens, skeptic consumed the macro finding.
- **Done** — Per-agent LLM call budget caps.
  `LLMConfig.per_agent_call_budget` (env
  `BIOTECH_ALPHA_LLM_PER_AGENT_CALL_BUDGET`) caps how many calls any
  single agent can make within one client lifetime;
  `OpenAICompatibleLLMClient` refuses pre-dispatch with
  `LLMBudgetError` (subclass of `LLMError`) so no token is spent and
  no trace entry is written for the refused call. A provider-agnostic
  `BudgetEnforcingLLMClient` wrapper applies the same logic to any
  `LLMClient`, useful for tests or adapters that lack native budget
  support.
- **Done** — Lightweight live macro-signals feed for the macro agent.
  New `MacroSignalsProvider` protocol plus
  `hk_macro_signals_yahoo` pull HSI level / 30-day return and USD/HKD
  spot from Yahoo's public chart endpoint, attach them to
  `macro_context.live_signals`, prune the corresponding
  `known_unknowns` entries, and degrade gracefully to a
  `None` sub-signal when the feed 429s. Opt-in via
  `--macro-signals yahoo-hk`.
- **Done** — Macro-signals disk cache. `CachingMacroSignalsProvider`
  keys on `(market, provider_label)` with a 6-hour default TTL and
  stale-if-error fallback, so analysts running back-to-back reports
  on several HK biotech names hit Yahoo once per TTL and transient
  429s serve slightly-stale cache plus a note instead of losing the
  live feed. Gitignored under `data/cache/macro_signals/`.
- **Done** — Multi-source macro-signals fallback chain so one vendor
  outage does not erase macro context. `FallbackMacroSignalsProvider`
  now runs `Yahoo -> Stooq -> stale cache` while preserving
  `macro_context.live_signals` schema and audit fields (`source`,
  `fetched_at`, `notes`).
- **Not started** — One short retry on Yahoo 429/503 inside
  `hk_macro_signals_yahoo` before surrendering to the stale-cache
  fallback, so the first cold run has a better chance of warming the
  cache.
- **Done** — Extend the macro-signals feed:
  HIBOR tenors, Hang Seng Biotech sub-index (^HSBIO), and compact
  source-tagged sector news are now included when reachable.
- **Not started** — Technical / K-line agent (long-horizon trend read on top
  of a future market-data pipeline).
- **Not started** — Orchestration fall-back: when an LLM agent fails schema
  validation three times, auto-downgrade to a shorter prompt variant or
  mark `needs_human_review=True` before giving up.
- **Done** — Multi-model support baseline: Anthropic adapter routed by
  `LLMConfig.provider` (`openai-compatible` default,
  `anthropic` opt-in), with provider-specific env key parsing and
  offline protocol tests. Remaining work is live smoke validation.

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
  orchestration path; Harbour BioMed covers USD financials and packed-table
  pipeline aliases; Leads Biolabs (`09887.HK`) now covers TCE/ADC-heavy
  annual-results text, `known as ... outside of China` aliases, table-header
  phase-ladder leakage, BLA/PCC milestones, and abbreviation/listing-warning
  noise. Broader representative ticker coverage remains open.

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
  Milestone extraction now also guards against stale legacy-year leakage
  (e.g. spurious `in 2017` values from broad context windows) by using
  asset-local context plus source-year sanity checks. Cached generated
  drafts with malformed or stale milestone warnings are now refreshed
  automatically from the latest source-backed extractor, and milestone
  whitespace is normalized so `planned to start in \n2026` becomes
  `planned to start in 2026`. Target/mechanism cleanup now handles
  HAT001/HBM9013 (`anti-CRH`, avoiding HBM7020 BCMA/CD3 leakage) and
  undisclosed-target packed rows such as J9003/R7027 without inventing
  source-unsupported targets. B7H4/CD3 local context now stops at the
  next numbered section so HBM7004 does not inherit Metabolic Disease /
  obesity text from a later source section. Harbour BioMed source-backed
  phase/partner cleanup now also rejects `Phase 3.0 strategic era` as a
  clinical phase, prefers BLA / IND statuses when stated, and prevents
  inline numbered collaboration sections from leaking partners across
  assets. Repeated source-text anchor selection now prefers evidence-rich
  mentions, so LLM triage does not miss later phase/IND/BLA evidence when
  an earlier collaboration-only mention appears first. Leads Biolabs source
  hardening now also prefers stronger repeated target / modality / indication /
  phase evidence, maps `known as ... outside of China` aliases, ignores generic
  pipeline table phase ladders, parses BLA/PCC milestone phrases, and blocks
  abbreviation/listing-warning leakage.

- **Partially done** — Extend generated draft inputs with clearer confidence
  tags and explicit `needs_human_review` markers (conference draft JSON from
  annual-results text exists; broader contracts still shallow).
  **Where:** `src/biotech_alpha/auto_inputs.py` (`draft_conference_catalysts`).

- **Partially done** — Add stricter validators for placeholder values,
  stale dates, and missing evidence metadata (beyond current warning-only
  checks).
  Current baseline now flags malformed milestone strings, stale
  milestone years vs evidence dates, non-positive evidence confidence,
  inferred evidence missing source dates, and generated quick reports
  now expose an `extraction_audit` summary with per-asset review reasons.

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

- **Partially done** — Improve competitor intelligence from deterministic
  target/indication matching toward better data-maturity and differentiation
  checks. Auto competitor seed drafting from extracted pipeline targets is
  now in place as a conservative bootstrap; generated seed drafts refresh
  by extractor version and cover the current Harbour BioMed target families
  without treating them as curated truth. Target-overlap seeds do not copy
  the pipeline asset indication into the competitor record. A first global
  discovery ingestion MVP is also live: generated competitor drafts emit
  `discovery_requests` and can ingest
  `<slug>_competitor_discovery_candidates.json` rows only when they include
  source URL, source date, evidence text, rationale, non-self company, and a
  deterministic target-family match. The first live bounded runner now uses
  ClinicalTrials.gov only, converts target-family-matching trials into
  review-gated candidates, and is enabled by default in quick `report`
  mode. The remaining gap is query quality / recall within CT.gov before
  adding company pages, filings, or other public sources.

- **Done (opt-in)** — Keep memo outputs deterministic-first while introducing
  a bounded, auditable scientific critique layer. `ScientificSkepticLLMAgent`
  runs only when `--llm-agents scientific-skeptic` is passed, uses a strict
  JSON schema, writes `data/memos/<run_id>_llm_findings.json` alongside a
  JSONL trace, and participates in the run-level cost summary. See Phase 10.

### Sprint 4: Multi-LLM Agent Collaboration

**Sprint status:** five-agent collaboration is live. Pipeline-triage,
financial-triage, competition-triage, and macro-context run before the
scientific-skeptic, which consumes their payloads through the FactStore.
Per-agent LLM budget caps, `--market-data-freshness-days`, Anthropic
adapter support, and the productized quick `report` command are in place.
Sprint continues with competitor-seed depth, provider smoke discipline, and
eventually a technical / K-line agent.

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
  Validated end-to-end via historical live Bailian Qwen dual-agent smoke
  (7298 total tokens, 2/2 calls OK, findings for both agents).
- **Done** — Multi-anchor `source_text_excerpt`: stitches one window per
  asset name, exposes `anchor_assets` / `missing_assets`, and the
  triage prompt respects them so extractor coverage limits are no
  longer flagged as data-quality issues. Raised triage confidence from
  0.6 to 0.95 on the DualityBio smoke.
- **Done** — Repeated-anchor ranking and extraction-audit UX. The excerpt
  builder now scores repeated mentions for clinical/regulatory signal
  terms and passes `anchor_signal_scores` into the pipeline-triage prompt.
  `report` terminal output prints `Extraction audit` and `Audit focus`;
  JSON summaries include the full `extraction_audit.assets[]` table, and
  saved runs write `<run_id>_extraction_audit.json` under the processed
  single-company directory with a manifest artifact pointer. Harbour
  BioMed smoke shows 6/12 supported assets, 6 review-gated assets, and
  0 missing anchors.
- **Done** — `FinancialTriageLLMAgent`: burn-rate / runway / cash-debt
  sanity across `financial_snapshot`, `runway_estimate`,
  `market_snapshot`, `valuation_metrics`. Emits `runway_sanity` enum
  (consistent / stretch / inconsistent / insufficient_data) plus
  per-metric severity findings. First non-pipeline LLM agent; validated
  on live DualityBio run at 3/3 OK and 10515 tokens combined.
- **Done** — `MacroContextLLMAgent`: stub-based macro regime read with
  `macro_regime` enum, `sector_drivers[]`, `sector_headwinds[]`. Four
  LLM agents composed cleanly (pipeline + financial + macro ->
  skeptic) and the skeptic's prompt renders all three upstream
  payloads. Live smoke on 09606.HK: 4/4 OK at 11919 tokens.
- **Done** — Per-agent LLM call budget cap via
  `LLMConfig.per_agent_call_budget`, enforced by
  `OpenAICompatibleLLMClient` and a separate
  `BudgetEnforcingLLMClient` wrapper. Refusal raises
  `LLMBudgetError` pre-dispatch so no token is spent.
- **Done** — `--market-data-freshness-days` CLI flag wraps the
  `hk_public_quote_provider` with `functools.partial` so operators
  can tune Tencent staleness without patching code; default stays at
  3 days.
- **Done** — `--macro-signals yahoo-hk` live feed: `MacroSignalsProvider`
  protocol + `hk_macro_signals_yahoo` pull HSI level / 30-day return and
  USD/HKD spot from Yahoo's public chart endpoint, attach them to
  `macro_context.live_signals`, and prune the matching
  `known_unknowns` entries. All sub-feed failures degrade to `None`
  with a note; no exception propagates. When Yahoo is reachable the
  macro agent forms a concrete regime; when rate-limited it falls back
  to the prior stub-only answer unchanged.
- **Done** — Macro-signals disk cache. `CachingMacroSignalsProvider`
  keyed on `(market, provider_label)` with 6-hour default TTL plus
  stale-if-error fallback, wrapped by default on
  `--macro-signals yahoo-hk`. Same-market requests across different
  companies reuse one successful fetch; transient Yahoo 429s serve
  slightly-stale cache plus a note instead of losing the live feed.
- **Done** — Add a Claude/Anthropic adapter so the runtime is not
  single-vendor (`AnthropicLLMClient` + `LLMConfig.provider` routing).
- **Done** — `CompetitionTriageLLMAgent` (opt-in via
  `--llm-agents competition-triage`) audits deterministic competitor
  matching outputs and feeds structured findings into the skeptic when
  chained in the same AgentGraph run.
- **Done** — Switch the openai-compatible development/default model from
  `qwen3.6-plus` to `qwen3.5-plus`. Stronger or alternate model ids remain
  available through `BIOTECH_ALPHA_LLM_MODEL` whenever quality requires them.
- **Done** — Ultra-simple CLI entry `report "<company|ticker>"` for
  operator UX. It auto-enables auto-inputs, market-data, macro-signals,
  and the full LLM stack by default; missing LLM env now fails fast unless
  `--allow-no-llm` is passed explicitly.
- **Done** — Productized quick-report terminal output. `report` now prints
  progress stages, a compact operator summary, LLM status, and artifact
  paths by default; `report --json` preserves the machine-readable compact
  summary for scripts.
- **Done** — Multi-source macro-signals fallback implementation:
  `Yahoo -> Stooq -> stale cache`, preserving current
  `macro_context.live_signals` output contract and audit keys.
- **Done** — Cached generated-input reuse bug fixed. When an existing
  `<slug>_pipeline_assets.json` draft is reused with `overwrite=False`,
  `generate_auto_inputs` now reads it correctly and still returns source
  documents, allowing pipeline triage to use source-text excerpts.
- **Deferred** — Short exponential backoff on Yahoo 429/503 inside
  `hk_macro_signals_yahoo` (operator preference is to rely on Stooq +
  stale-cache fallback for now, then revisit retries later).
