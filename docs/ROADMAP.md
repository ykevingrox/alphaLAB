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

Architecture alignment baseline is documented in
`docs/ARCHITECTURE_AUDIT.md`. Roadmap execution should follow that target
agent topology (including valuation pod and report-quality layer).

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
  without changing the default LLM-free behaviour. Saved markdown memos now
  append an `## LLM Agent Addendum` for LLM runs while preserving the
  standalone `data/memos/<run_id>_llm_findings.json` artifact.

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

## Next Execution Plan

**Active sprint:** Stage B prework — deterministic market technical feature
layer, then market-expectations and market-regime/timing agents. Sprint 6
Stage A is implemented at baseline level and remains open only for calibration
hardening.

**Doc discipline:** Each sprint below lists **implementation status** so
this section stays aligned with the repo. Update statuses when scope
changes.

**Last status pass:** 2026-04-27 (Stage A+ valuation calibration committed;
external repo review added for `yfinance` and `TradingAgents`).

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
  pipeline aliases; Leads Biolabs (`09887.HK`) covers TCE/ADC-heavy
  annual-results text, `known as ... outside of China` aliases, table-header
  phase-ladder leakage, BLA/PCC milestones, and abbreviation/listing-warning
  noise; Innovent Biologics (`01801.HK`) now covers HKD thousand-unit
  financial parsing, mixed Phase 3 / Phase 1b / IND-enabling extraction,
  `anti-LAG-3` anti-target parsing, and `planned to start in 2027` milestone
  normalization. Broader representative ticker coverage (next distinct HK
  disclosure style) remains open.

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
  mode. Candidate packs include `rejection_summary`, and generic target-class
  interventions are rejected so background therapies are not mistaken for
  competitor assets. The remaining gap is using the refreshed CT.gov candidate
  set in full LLM competition-triage runs before adding company pages, filings,
  or other public sources.

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
  and the full LLM stack by default; missing LLM env now auto-degrades to
  deterministic mode with an explicit terminal note (no fail-fast by default).
- **Done** — Productized quick-report terminal output. `report` now prints
  progress stages, a compact operator summary, LLM status, and artifact
  paths by default; `report --json` preserves the machine-readable compact
  summary for scripts.
- **Done** — Saved markdown memos now include an LLM addendum whenever LLM
  agents run: run status, token count, trace path, per-agent summaries,
  risks, evidence, and step issues are visible in the human report without
  parsing the separate findings JSON.
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
- **Moved to Sprint 6 (Stage A)** — Valuation pod decomposition
  (`valuation-commercial-agent`, `valuation-pipeline-rnpv-agent`,
  `valuation-balance-sheet-agent`, `valuation-committee-agent`) plus
  `report-quality-agent`.
- **Moved to Sprint 7 (Stage B)** — `strategic-economics-agent`,
  `catalyst-agent`, `market-expectations-agent`, and
  `market-regime-timing-agent`.
- **Moved to Sprint 8 (Stage C)** — `data-collector-agent`,
  `report-synthesizer-agent` formalization.

### Sprint 5: From Data Sheet To Investment Memo

**Sprint status:** core objectives closed (P0/P1/P2/P3 baseline landed). Current
workstream is quality hardening, valuation traceability, and backlog cleanup.

**Why this sprint exists.** The current memo reads like a statistics report,
not an investment recommendation. Reviewing
`data/memos/09887-hk/20260423T095148Z_memo.md` showed the sharpest judgement
(scientific skeptic, pipeline triage) is buried under "LLM Agent Addendum"
while the top-of-memo Summary / Bull / Bear sections are generic counts and
meta-disclaimers. Catalyst-Adjusted Valuation is empty by default because
`target_price_assumptions.json` is required but never generated. Pipeline
descriptions stop at target / indication / phase; core products such as
LBL-024 get one line. This sprint upgrades the memo from "data present" to
"investment view present, with explicit assumptions and falsifiable
predictions".

**Design principles for this sprint.**

- Deterministic defaults stay conservative. Every auto-generated assumption
  (PoS, peak sales, launch year) is sourced from a transparent lookup table
  that lives in the repo, not inside an LLM prompt.
- LLM agents do not invent numbers. They explain, compare, and critique
  deterministic numbers, and they must cite the upstream fact by field name.
- Every new field is `needs_human_review` until an explicit curated override
  exists.
- No change to the `AgentFinding` contract or to manifest / run shapes; all
  new content threads through existing fields.
- The memo template change is backwards-compatible: the compact JSON summary
  shape and `decision` / `quality_gate` / `watchlist_bucket` field names do
  not change.

**Model strategy during this sprint.** Development continues on
`qwen3.5-plus` (Bailian free tier) to keep iteration cost low. Every new LLM
agent must accept a per-agent model override (env + config) so switching to a
stronger model later is a configuration change, not a code change. Output
quality differences across models are tracked as a separate "Model Upgrade
Pass", not as Sprint 5 acceptance gates.

#### P0 — Make the memo investable

Highest ROI: the moment these land, each memo has a target price, a concrete
thesis, and deep content on the core asset instead of counts.

- **P0.1** — Default rNPV / target-price draft.
  - **Status:** done.
  - **What:** add `draft_target_price_assumptions(identity, pipeline_assets,
    market_snapshot, financial_snapshot)` in
    `src/biotech_alpha/target_price.py`; write
    `data/input/generated/<slug>_target_price_assumptions.json` alongside
    other generated inputs; make `run_company_report` consume it by default
    so the memo's `Catalyst-Adjusted Valuation` section is never empty.
  - **Lookup tables (committed):** phase → PoS (e.g. P1 ~10%, P2 ~15%,
    P3 ~50%, filed ~85%, oncology vs autoimmune variants); indication →
    peak sales band (e.g. NSCLC 1L $3-10B, MM $1-4B, SLE $1-3B, EP-NEC
    $0.3-1B, solid tumor default $1-3B). Both tables live in a single
    reference file with citations to published benchmarks.
  - **Economics:** default economics_share = 1.0 for China-only rights,
    0.1-0.3 royalty for licensed-out programs when the disclosure mentions
    `licensed`, `out-licensed`, `license agreement`, or similar patterns.
  - **Launch year:** derived from phase + buffer, floored to current year
    + 2. Discount rate default 0.12.
  - **Gating:** manual `data/input/<slug>_target_price_assumptions.json`
    still wins over the generated file. The generated file carries
    `inferred_by: "default_rnpv_v1"` and `needs_human_review: true`.
  - **Done when:**
    1. `report "09887.HK" --no-llm --no-save` prints a
       `probability_weighted_target_price` and bear/base/bull range.
    2. `Catalyst-Adjusted Valuation` section of the memo shows values
       instead of "No catalyst-adjusted target price range was generated."
    3. Manual override precedence has a regression test.
    4. Missing `market_snapshot` or missing pipeline degrades to a
       deterministic `needs_human_review=true` placeholder, not an
       exception.
  - **Estimated size:** 2-3 days.

- **P0.2** — Memo template rewrite.
  - **Status:** done.
  - **What:** restructure `src/biotech_alpha/research.py` /
    `company_report.py` markdown builder to the investment-memo order:
    1. Executive Verdict (decision + target-price range + 1-line thesis).
    2. Investment Thesis (bull drivers, bear drivers, key assumptions,
       falsification watch).
    3. Core Asset Deep Dive (top-3 Phase 2+ assets).
    4. Catalyst Roadmap.
    5. Competitive Landscape.
    6. Financials & Runway.
    7. Valuation Detail.
    8. Key Risks & Falsification.
    9. Evidence & Sources (appendix).
  - **LLM integration rule:** LLM agent findings render into the matching
    main section, with a `source: llm[agent, confidence]` tag. The current
    bottom-of-memo `## LLM Agent Addendum` block keeps only token / trace /
    step-status metadata.
  - **Confidence gating:** findings with `confidence < 0.3` do not appear
    in the main sections; they stay in the appendix only.
  - **Done when:**
    1. Memo for `09887.HK` shows decision + bear/base/bull target price
       within the first screen.
    2. LLM findings appear exactly once (in the relevant main section),
       not duplicated between main body and addendum.
    3. `quality_gate`, `watchlist_score`, `decision`, `needs_human_review`
       field contracts are unchanged in the saved manifest and compact
       JSON summary.
    4. Regression tests cover both the full-LLM render path and the
       deterministic-only render path.
  - **Depends on:** P0.1 (so Executive Verdict has a target price to
    render).
  - **Estimated size:** 2 days.

- **P0.3** — `InvestmentThesisLLMAgent`.
  - **Status:** done.
  - **What:** new agent in `src/biotech_alpha/agents_llm.py` that runs
    last in the DAG, reads `pipeline_triage_payload`,
    `financial_triage_payload`, `competition_triage_payload`,
    `macro_context`, `scorecard_summary`, and the new
    `target_price_snapshot`, and returns a single structured finding:
    ```json
    {
      "thesis_summary": "...",
      "bull_drivers": [{"claim": "...", "evidence_refs": [...]}, ...],
      "bear_drivers": [{"claim": "...", "evidence_refs": [...]}, ...],
      "key_assumptions": [
        {"assumption": "...", "falsification": "..."}, ...
      ],
      "falsification_watch": [
        {
          "observation": "...",
          "window": "next 6 months",
          "direction": "bull"
        },
        ...
      ],
      "decision_rationale": "...",
      "confidence": 0.0
    }
    ```
  - **CLI:** `--llm-agents investment-thesis` flag; quick `report` path
    enables it by default alongside the existing five agents.
  - **Cost guard:** prompt capped at ~6k tokens with structured
    upstream summaries; completion capped so the agent stays under
    ~3000 tokens per run on `qwen3.5-plus`. Per-agent budget plugs into
    existing `BudgetEnforcingLLMClient`.
  - **Output consumption:** renders into Memo § Investment Thesis and
    feeds `thesis_summary` into Memo § Executive Verdict.
  - **Done when:**
    1. 09887 memo has non-empty, asset-specific bull/bear drivers and at
       least one falsification observation within a stated window.
    2. Strict JSON schema validation passes; schema drift raises the same
       `LLMOutputValidationError` the other agents use.
    3. Upstream agent failure or missing upstream fact causes this agent
       to skip with a clear `AgentStepResult(ok=false)` note, never an
       exception.
  - **Depends on:** P0.1, P0.2 so Executive Verdict has a slot for the
    summary.
  - **Estimated size:** 1.5-2 days.

- **P0.4** — Core Asset Deep Dive extraction + agent.
  - **Status:** done for deterministic track (deep-dive ranking + structured
    clinical datapoints + regulatory/binary-event enrichment + deterministic
    differentiation-vs-competitor line + ground-truth harness landed). Optional
    `AssetDeepDiveLLMAgent` remains a non-blocking enhancement.
  - **What:** broaden HKEX PDF text extraction beyond "Business
    Highlights" into "Clinical Highlights" / "Clinical Update" / "Data
    Highlights" sections (`auto_inputs._extract_clinical_highlights`).
    Add an optional `clinical_data` list to the pipeline asset JSON
    schema (ORR, DCR, mPFS, OS, n, cutoff date, meeting citation) with
    validation.
  - **New agent (optional but recommended):** `AssetDeepDiveLLMAgent`
    per top-3 Phase 2+ asset. Consumes extracted clinical_data plus the
    asset's source window plus matched competitor records, returns
    structured `market_size_note`, `clinical_data_summary`,
    `regulatory_pathway`, `next_binary_event`,
    `differentiation_vs_competitors`.
  - **Ranking:** Top-3 determined by phase, then clinical trial count,
    then registry-match strength. Ties broken by asset-name order for
    stability.
  - **Memo:** § Core Asset Deep Dive renders one sub-section per top-3
    asset with deterministic fields first, then the LLM agent's text.
    Non-Top-3 Phase 2+ assets get one-line summaries. Preclinical assets
    remain in the pipeline table only.
  - **Done when:**
    1. 09887 memo's LBL-024 deep dive section includes at least one
       ORR/DCR data point from source, BLA timeline, and a
       differentiation sentence against Phase 2+ competitor with the
       closest target or indication.
    2. Manual `data/input/<slug>_pipeline_assets.json` with
       `clinical_data` overrides generated clinical_data rows.
    3. If no clinical_data is extractable, the section gracefully
       degrades to `Clinical data not yet extracted from source; see
       Evidence § ...` and the run still succeeds.
  - **Depends on:** P0.2.
  - **Estimated size:** 3-4 days.

#### P1 — Connect judgement to action

Each P1 task sharpens an answer that the user still has to reconstruct by
hand after reading a P0 memo.

- **P1.5** — Cross-agent finding merge into main Risks / Core Asset
  sections.
  - **Status:** done for deterministic merge baseline (risk de-dup/severity
    ordering landed; medium/high triage risks with confidence gate now carry
    `source: llm[agent_name]` tags in memo risk rendering).
  - **What:** promote LLM triage findings (pipeline / financial /
    competition) with `severity in {"medium", "high"}` and
    `confidence >= 0.4` into the deterministic risks list, tagged with
    `source: llm[agent_name]`. De-duplicate by `(related_asset, issue
    description normalized)`.
  - **Done when:** the `LBL-024 phase mislabeled` pipeline-triage
    finding appears in Memo § Key Risks. LLM addendum no longer repeats
    it. Confidence < 0.3 findings still only appear in appendix.
  - **Depends on:** P0.2, P0.3.
  - **Estimated size:** 1 day.

- **P1.6** — Catalyst Roadmap with value-weighted ranking.
  - **Status:** done (deterministic impact score + time buckets + priority sort
    in memo rendering).
  - **What:** extend `pipeline.py` / `target_price.py` so each
    `clinical_catalyst` carries `expected_pos` (from rNPV PoS) and
    `expected_value_delta_pct` (signed, based on catalyst type: positive
    readout +X%, negative -Y%, delay pushes launch year). Sort by
    `|pos × delta|`; bucket into near-term (0-6M), mid-term (6-18M),
    long-term (18M+).
  - **Memo:** § Catalyst Roadmap replaces the flat
    `Upcoming Clinical Catalysts` list; each bullet shows expected bear
    / base / bull price movement for the event.
  - **Done when:** LBL-024 BLA Q3 2026 ranks in the top near-term bucket
    on 09887's memo; each catalyst shows a signed expected value delta.
  - **Depends on:** P0.1.
  - **Estimated size:** 1 day.

- **P1.7** — Scorecard transparency.
  - **Status:** done (memo + summary + manifest surface per-dimension
    score/weight/contribution; `watchlist-rank` expands per-dimension columns
    behind `--with-scorecard-dimensions`; memo now includes a deterministic
    "Path to Core Candidate" top-3 lift-target list).
  - **What:** expose `scorecard.dimensions` (dimension, raw score,
    weight, contribution) in manifest and memo. Auto-generate a "Path
    to core candidate" list of the 3 lowest-contribution dimensions
    plus the concrete evidence needed to raise each.
  - **Done when:** 09887 memo shows each dimension's score and the top
    3 lift targets. `watchlist-rank` CSV gains per-dimension columns
    behind a flag.
  - **Depends on:** none (independent).
  - **Estimated size:** 0.5 day.

- **P1.8** — Research-only Action Plan.
  - **Status:** done (memo section + explicit research-only language +
    standalone `position_action.py` structured module + dedicated unit tests +
    edge-case hardening for missing/non-finite anchors + structured summary/
    manifest payload with `guidance_type` labeling).
  - **What:** new module `src/biotech_alpha/position_action.py` that
    combines `target_price_range`, `current_share_price`, and
    `research_position_limit_pct` into `entry_zone_price_range`,
    `suggested_position_pct`, and `exit_trigger_conditions` (price >
    bull target; runway < 12M; catalyst miss on a high-weight event).
  - **Labeling:** every output field must carry
    `guidance_type = "research_only"`. Memo § Action Plan explicitly
    states "research support only; not a trading instruction".
    `Do Not Break` list gains a dedicated rule about this.
  - **Done when:** memo shows a bounded entry zone and explicit exit
    triggers; unit tests cover absent share price, inverted
    bear > bull edge cases, and the do-not-format-as-signal rule.
  - **Depends on:** P0.1, P1.7.
  - **Estimated size:** 1 day.

#### P2 — Data breadth

These tasks are necessary medium-term but only pay off once the P0 / P1
structure can consume them.

- **P2.9** — China drug clinical trial registry ingestion.
  - **Status:** done for deterministic baseline + normalization draft
    (`cde-track` CLI + feed parser/state tracker + optional `company-report`
    CDE artifact + memo addendum + summary/manifest threading + structured
    `normalized_new_records` fields for registry-style trial rows).
  - **Boundary now:** normalization is heuristic/feed-title based and still
    review-gated; no official full CDE schema mirror is implied.
  - **Contingency (deferred):** add hybrid fallback (rule-first extraction with
    LLM invoked only for low-confidence leftovers) if deterministic quality
    drops on future fixtures.
  **Size:** 3-5 days.
- **P2.10** — HKEXnews announcement RSS and change tracker.
  - **Status:** done (phase-1 baseline + report-chain integration landed:
    RSS parse, seen-guid tracking, CLI `hkexnews-track`, and saved
    `hkexnews_updates` report artifact; deterministic event typing landed; memo
    threading landed; catalyst-calendar threading and review-gated valuation
    hooks landed).
  - **Boundary now:** HKEX-derived impacts remain review-gated suggestions;
    no automatic target-price overwrite is applied.
  **Size:** 2 days.
- **P2.11** — License / BD event tracker into `event_impacts`.
  - **Status:** done (deterministic HKEX license/BD keyword tracker now emits
    review-gated event-impact suggestion rows in saved artifacts/manifest).
  **Size:** 2 days.
- **P2.12** — Peer valuation comparison (target + phase-matched HK
  biotech).
  - **Status:** done (deterministic peer-valuation baseline now writes a
    comparable peer set scaffold from competitive matches, review-gated).
  **Size:** 2 days.
- **P2.13** — Equity history / financing track with automatic
  `expected_dilution_pct` suggestion.
  - **Status:** done (financing-class HKEX announcements now emit
    review-gated `expected_dilution_pct` suggestions).
  **Size:** 2 days.

#### P3 — Strategic additions

- **P3.14** — `KlineTechnicalLLMAgent` (OHLCV + a few classic indicators;
  flags divergence vs fundamental / macro read; research-only).
  - **Status:** done (deterministic baseline via `technical-timing` command:
    SMA20/SMA60, RSI14, volatility, support/resistance, research-only output).
  **Size:** 3 days.
- **P3.15** — Historical memo diff (same slug, last two runs).
  - **Status:** done (CLI `memo-diff` landed, emits machine-readable unified diff).
  **Size:** 2 days.
- **P3.16** — Portfolio-level concentration checks (target / modality /
  catalyst density).
  - **Status:** done (watchlist guardrail now includes modality concentration
    and catalyst-density concentration counts/flags).
  **Size:** 1 day.
- **P3.17** — Bilingual memo output (EN + zh-CN; preserve English
  technical terms).
  - **Status:** done (CLI `memo-bilingual` writes EN + zh-CN draft memo with
    explicit review-gated translation label).
  **Size:** 1-2 days.
- **P3.18** — HTML / PDF memo export with pipeline gantt, catalyst
  timeline, rNPV stack chart.
  - **Status:** done (CLI `memo-export` now supports HTML export with inline
    pipeline gantt, catalyst timeline, and rNPV stack charts; optional PDF
    export remains available when `reportlab` is installed).
  **Size:** 3-5 days.

#### Execution order (historical, completed baseline)

Target sequence, optimised for earliest "the memo feels investable" moment:

1. P0.1 Default rNPV draft.
2. P0.2 Memo template rewrite.
3. P1.5 Cross-agent finding merge.
4. P0.3 `InvestmentThesisLLMAgent`.
5. P1.6 Catalyst roadmap priority.
6. P1.7 Scorecard transparency.
7. P0.4 Core Asset Deep Dive.
8. P1.8 Research-only action plan.
9. P2.* data breadth (pick based on the gap the P0 / P1 memo reveals).
10. P3.* strategic additions.

All steps above are completed at baseline level. Ongoing iteration prioritizes:

1. Currency/valuation traceability hardening (FX metadata, shared conversion path).
2. Chinese-first report quality hardening (residual English cleanup, section consistency).
3. Backlog depth tasks (higher-fidelity CDE normalization, optional hybrid fallback).

#### Cross-sprint invariants (Do Not Break)

- Deterministic report must still run when every LLM agent is skipped
  (`--no-llm` or missing LLM env + `--allow-no-llm`).
- All auto-generated assumptions remain `needs_human_review=true` until a
  curated override lands.
- Any new LLM agent must accept a per-agent model override.
- Every new field threading through the run must be represented in the
  manifest so a future run is reproducible.

### Sprint 6: Valuation Pod + Report Quality (Stage A)

**Sprint goal.** Decompose the monolithic `valuation-specialist` into a
four-agent valuation pod and add a standalone `report-quality-agent` that
owns the publish gate. Keep HK innovative-drug biotech as the only vertical.

**Sprint status:** in verification (core implementation landed; calibration
pending for biotech-specific valuation framing and cross-ticker quality-gate
consistency).

**Acceptance baseline.** A one-command run on `09606.HK`, `02142.HK`, and
`09887.HK` produces:

1. Four distinct valuation-pod findings per run, each with its own
   `method`, `scope`, `valuation_range`, and `confidence`.
2. One committee finding with `sotp_bridge`, `method_weights`, and
   `final_per_share_range`.
3. One `report-quality-agent` finding with `publish_gate` set to `pass` or
   `review_required` (never missing).
4. Deterministic `--no-llm` run still produces a valid memo with the
   existing rule-based `quality_gate` path unchanged.

**Design principles for Stage A.**

- Pod sub-agents do not invent numbers; they price from deterministic
  sources (`financials_snapshot`, `target_price_assumptions`,
  `valuation_snapshot`).
- LLM in these agents is used to select methods, cite assumption field
  names, assemble sensitivity, and produce conflict resolution prose, not
  to generate PoS or peak sales.
- `report-quality-agent` may NOT overwrite any upstream artifact; it can
  only emit `recommended_fixes`.
- Every new agent goes through `BudgetEnforcingLLMClient` with a
  per-agent budget; default per-agent budget for the pod is 1 call per
  run to keep Sprint-6 cost linear.
- Currency is always declared explicitly; when inputs are in RMB/CNY the
  balance-sheet agent must apply the existing `target_price.py`
  conversion path rather than inventing a new one.
- Conservative rNPV is a floor or cross-check, not the only fair-value anchor
  for pre-revenue innovative-drug companies. The committee must separate:
  conservative rNPV floor, market-implied value, and scenario repricing range.
- The pod must explain why a stock can sustain a valuation band above rNPV
  before labeling that gap as overvaluation.

**Model strategy for Stage A.** Keep `qwen3.5-plus` as the dev default.
Provide `LLMConfig.per_agent_models` plumbing so a production run can pin
`valuation-committee-agent` and `report-quality-agent` to a stronger
model (e.g. `qwen3-max`, `claude-3.5-sonnet`) without a code change.

#### S6.1 — Pod skeleton + committee passthrough

- **Status:** done.
- **What:** Add three sub-agent skeletons (`ValuationCommercialLLMAgent`,
  `ValuationPipelineRnpvLLMAgent`, `ValuationBalanceSheetLLMAgent`) and a
  thin `ValuationCommitteeLLMAgent` that simply concatenates sub-agent
  outputs into the pod contract (no weighting logic yet).
- **Shape:** every sub-agent emits the shared pod fields defined in
  `docs/AGENTS.md` and `docs/ARCHITECTURE_AUDIT.md`.
- **Wiring:** register in `SUPPORTED_LLM_AGENTS`, `company-report
  --llm-agents` choices, and quick `report` default stack (behind a
  feature flag until S6.2 lands).
- **Compatibility:** retain `valuation-specialist` in the default stack
  until the pod passes S6.4; do not delete it.
- **Done when:**
  1. `company-report --llm-agents valuation-commercial valuation-rnpv
     valuation-balance-sheet valuation-committee` runs end-to-end on
     `09606.HK` with all four agents producing schema-valid findings.
  2. Unit tests cover schema validation and schema drift rejection for
     each sub-agent.
  3. `valuation-specialist` still runs unchanged when requested.
- **Estimated size:** 3-4 days.

#### S6.2 — Committee SOTP logic

- **Status:** done (first production version; ongoing calibration).
- **What:** Replace passthrough committee with real SOTP bridge,
  currency reconciliation, method weighting, and conflict resolution.
  Committee must also consume `macro_context`, `pipeline_triage_payload`,
  and `competition_triage_payload`.
- **Currency rule:** if any sub-agent declares a currency different from
  the balance-sheet agent's declared currency, committee must convert
  using the existing `target_price.py` conversion helper and record the
  bridge in `conflict_resolution` + `assumptions`.
- **Weighting rule:** default weights are data-driven
  (`commercial` weight scales with revenue materiality; `rnpv` weight
  scales with pipeline asset count weighted by phase; `balance_sheet`
  always contributes its net cash/debt as an additive bridge).
- **Done when:**
  1. `final_equity_value_range.base` equals the sum of `sotp_bridge`
     component contributions.
  2. Currency conflict on a synthetic RMB-reporting / HKD-market fixture
     produces a recorded `conflict_resolution` entry.
  3. 09606.HK committee output produces a per-share range consistent
     with the existing catalyst-adjusted target price within +/-15%
     (committee is allowed to differ; the sanity threshold is there to
     catch 10x unit mistakes, not to force agreement).
- **Depends on:** S6.1.
- **Estimated size:** 3 days.

#### S6.3 — `report-quality-agent`

- **Status:** done (first production version; gate calibration ongoing).
- **What:** New LLM agent consuming the composed memo, every
  `AgentFinding`, run-level `scorecard`, `extraction_audit`,
  `input_validation`, and valuation pod outputs. Emits the contract
  defined in `docs/AGENTS.md` (publish gate + consistency / evidence /
  language / valuation coherence findings + recommended fixes).
- **Wiring:** new CLI name `report-quality`; appears last in the DAG
  layer. Quick `report` default stack enables it.
- **Gate defaults:** until the agent has been calibrated on at least
  three HK tickers, the gate MUST default to `review_required` when the
  LLM output is empty or schema-invalid, never to `pass`.
- **Persistence:** emit `<run_id>_report_quality.json` under the memo
  directory and attach to `manifest.artifacts.report_quality`. Summary
  payload adds `report_quality_gate` for downstream tools.
- **Memo rendering:** memo gains an `## 报告质量门` section summarizing
  the gate, critical issues, and recommended fixes. Deterministic
  fallback path leaves the section omitted rather than empty.
- **Done when:**
  1. Live run on 09606.HK emits a schema-valid finding with at least
     one `consistency_findings` or `valuation_coherence_findings` row
     (the pod will initially disagree; that's the point).
  2. `--no-llm` run still passes and omits the quality-agent section.
  3. Unit tests cover: happy path, empty memo input, schema drift,
     and the "never silently downgrade to pass" rule.
- **Depends on:** S6.1 (so pod findings exist to review).
- **Estimated size:** 2-3 days.

#### S6.4 — Deprecate monolithic `valuation-specialist`

- **Status:** done (default quick stack uses valuation pod; specialist retained
  as opt-in compatibility path).
- **What:** Move `valuation-specialist` out of the default stack behind
  an opt-in flag. Keep the class and tests so old manifests can still be
  reproduced.
- **Rollback safety:** if the pod's committee confidence drops below
  0.3 or `report-quality-agent` gates the run as `block`, fall back to
  `valuation-specialist` output for the memo's Valuation Detail section
  so the user still gets a coherent narrative.
- **Done when:**
  1. Quick `report` default stack omits `valuation-specialist`.
  2. `company-report --llm-agents valuation-specialist` still works for
     reproducibility.
  3. Tests confirm fallback-to-specialist path when the pod fails.
- **Depends on:** S6.1, S6.2, S6.3.
- **Estimated size:** 1 day.

#### S6.5 — Per-agent model override plumbing

- **Status:** done.
- **What:** Extend `LLMConfig` with `per_agent_models: dict[str, str]`
  resolved from env
  `BIOTECH_ALPHA_LLM_MODEL_<AGENT_NAME>` (agent name uppercased,
  hyphens -> underscores). `OpenAICompatibleLLMClient` and
  `AnthropicLLMClient` honour the override per call.
- **Done when:**
  1. Running with `BIOTECH_ALPHA_LLM_MODEL_REPORT_QUALITY=qwen-max`
     routes only that agent's calls to `qwen-max` while other agents
     continue on the default.
  2. Trace JSONL records the effective model per call.
  3. Unit test covers override resolution and default fallback.
- **Depends on:** none (can land in parallel with S6.1-S6.4).
- **Estimated size:** 1 day.

#### S6.6 — Biotech valuation framing calibration

- **Status:** next.
- **What:** Recalibrate valuation-pod prompts/contracts so they reflect
  biotech market structure rather than mature-company valuation defaults.
- **Why:** The latest acceptance sweep shows `commercial`, `rnpv`, and
  `balance_sheet` repeatedly collapse onto the same rNPV target-price range.
  This makes the system call persistent market valuation bands "wrong" without
  first explaining BD, retained economics, platform optionality when present,
  catalyst-window premiums, or sector liquidity.
- **Rules:**
  1. `valuation-commercial` must return no operating commercial value when
     product revenue is absent; it must not fall back to rNPV.
  2. `valuation-balance-sheet` must emit only net cash/debt/non-operating
     adjustments and method `balance_sheet_adjustment`.
  3. `valuation-committee` must distinguish `conservative_rnpv_floor`,
     `market_implied_value`, and `scenario_repricing_range`.
  4. `report-quality` must flag "rNPV treated as sole fair value" as a
     framing defect, while allowing `review_required` instead of `block` when
     the only problem is missing strategic/market-expectation context.
- **Done when:**
  1. Three-ticker canonical smoke no longer shows identical valuation ranges
     across commercial, rNPV, and balance-sheet components.
  2. `09887.HK` report explains the gap between conservative rNPV and current
     price through market-implied assumptions before concluding on valuation.
  3. `02142.HK` may still block for true data-quality failures, but not
     solely because market price exceeds rNPV.
  4. `09606.HK` report-quality JSON parses cleanly or falls back to
     `review_required` without hiding the raw critical issues.
- **Depends on:** S6.1-S6.5.
- **Estimated size:** 1-2 days.

#### Sprint 6 execution order

1. S6.5 (unblocks cheap experimentation with strong models for the new
   agents).
2. S6.1 (pod skeleton).
3. S6.3 (report-quality agent; can start once S6.1 lands because it
   only needs schema-valid pod outputs, not the real committee logic).
4. S6.2 (committee SOTP logic).
5. S6.4 (deprecate monolith).
6. S6.6 (biotech valuation framing calibration).

#### Sprint 6 validation

- Full unit-test suite green.
- `compileall` green on `src/` and `tests/`.
- Three-ticker canonical smoke:
  `09606.HK`, `02142.HK`, `09887.HK` each produce pod + committee +
  report-quality findings with `publish_gate` present.
- `--no-llm` smoke on `09606.HK` still produces a valid memo.
- Manifest for every run above carries:
  `artifacts.valuation_pod`, `artifacts.report_quality`, and a compact
  `valuation_pod_summary` plus `report_quality_gate` in the summary
  payload.
- Latest saved acceptance sweep (2026-04-24):
  - `09606.HK` run `20260424T094304Z`: `publish_gate=review_required`
  - `02142.HK` run `20260424T094508Z`: `publish_gate=block`
  - `09887.HK` run `20260424T094708Z`: `publish_gate=block`
- Follow-up calibration committed after that sweep:
  - `6207c61` exposes component methods/ranges and separates conservative
    rNPV floor, market-implied value, and scenario repricing range.
  - Live `09887.HK --json --no-save` smoke after calibration produced
    `publish_gate=review_required`, with no duplicate component ranges.
  - A fresh three-ticker saved acceptance sweep is optional before declaring a
    release tag, but it is no longer the next development blocker.

### Stage B Prework: Market Technical Feature Layer

**Sprint status:** implemented as deterministic baseline plus optional
yfinance adapter and report fact threading.

Build deterministic market features before adding the LLM timing agent. This
keeps provider volatility out of prompts and gives both
`market-expectations-agent` and `market-regime-timing-agent` a stable payload.

- **Done** — Provider-neutral input: historical OHLCV for the company and, when
  available, a benchmark such as HSI or Hang Seng Biotech.
- **Done** — Required initial outputs:
  - 1m/3m/6m/12m returns.
  - Drawdown from 52-week high.
  - Volume trend.
  - Moving-average state.
  - Volatility state.
  - Relative strength versus benchmark.
- **Done** — Source discipline: every payload carries provider label, source
  symbol, retrieved-at timestamp, window, and warnings.
- **Done** — Optional yfinance adapter prototype behind graceful import and the
  `market` optional dependency extra. It is not wired into the default report
  path yet.
- **Done** — First `market-regime-timing-agent` scaffold consumes macro
  context plus optional `technical_feature_payload` and emits research-only
  timing labels. It is opt-in, not quick-report default.
- **Done** — `company-report --technical-features yfinance` threads real
  technical-feature payloads into LLM facts when `market-regime-timing` or
  `market-expectations` is requested. Quick `report` remains unchanged.
- **Done** — First `market-expectations-agent` scaffold explains
  market-implied assumptions, valuation-band context, rNPV gaps,
  expectation-risk flags, and evidence gaps.
- **Done** — First `strategic-economics-agent` scaffold explains retained
  economics, BD validation, partner quality, commercialization path,
  value-capture score, premium/discount drivers, and evidence gaps.
- **Done** — First `catalyst-agent` scaffold ranks catalyst event quality,
  binary risk, expectation risk, repricing paths, and evidence gaps while
  keeping numerical deltas in `target_price.py`.
- **Next** — Calibrate an opt-in Stage B stack run, then start Stage C
  `data-collector-agent`.
- `TradingAgents` is not a dependency for this checkpoint. Keep using the
  current custom `AgentGraph`.

### Sprint 7: Strategic Economics + Market Context (Stage B)

**Sprint status:** scaffold-complete. Market-regime/timing,
market-expectations, strategic-economics, and catalyst scaffolds exist; default
quick-report inclusion still requires calibration.

- `strategic-economics-agent`: explains how a company captures value from its
  science through retained economics, BD/licensing, regional rights, partner
  quality, cost sharing, commercialization path, and platform reuse only when
  the company has platform evidence. First opt-in scaffold is implemented and
  feeds `market-expectations` and `valuation-committee` when requested.
- `catalyst-agent`: independent LLM narrative over deterministic catalyst
  calendar. It ranks clinical, regulatory, BD, and conference/data-readout
  events by evidence quality, binary risk, expectation risk, and repricing
  paths. Numerical deltas still come from `target_price.py`. First opt-in
  scaffold is implemented.
- `market-expectations-agent`: explains what the current market cap appears
  to imply. It asks why the stock has sustained its valuation band before the
  system labels the gap versus conservative rNPV as overvaluation, including
  which catalyst assumptions appear priced in. First opt-in scaffold is
  implemented and can consume strategic economics / catalyst payloads when
  requested in the same run.
- `market-regime-timing-agent`: combines the existing `macro-context` role,
  planned k-line framing, sector sentiment, liquidity, and fund-flow proxies
  into research-only timing labels (`favorable`, `neutral`, `fragile`,
  `avoid_chasing`, `de_risk_watch`). First opt-in scaffold is implemented;
  live technical-feature collection is available through the opt-in yfinance
  adapter.

Sprint-7 agent execution should keep two conclusions separate:

1. `Fundamental view`: whether the company belongs in avoid/watchlist/core
   research pools.
2. `Timing view`: whether the current market regime and price action support
   higher attention, patience, or de-risk monitoring.

### Sprint 8: Data Collector + Report Synthesizer (Stage C)

**Sprint status:** started. First data-collector scaffold exists; report
synthesizer is pending.

- `data-collector-agent`: LLM layer on top of existing deterministic
  ingestion that triages evidence quality, flags stale sources, and
  produces `publish_ready / needs_more_evidence / insufficient_data`
  verdicts per input domain. First opt-in scaffold is implemented and feeds
  the `report-quality-agent` when requested.
- `report-synthesizer-agent`: move the memo's Executive Verdict and
  section transitions from deterministic rendering to an LLM agent, with
  deterministic fallback preserved.

Next Sprint-8 task: add `report-synthesizer-agent` with deterministic fallback
preserved.
