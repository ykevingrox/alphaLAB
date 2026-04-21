# Roadmap

## MVP Strategy

The near-term priority remains a working Hong Kong biotech MVP. Future expansion
to other Hong Kong sectors, US stocks, and A-shares should influence module
boundaries, but it should not distract the current implementation.

Design rules for new work:

- Keep core orchestration company-, market-, and sector-aware.
- Put biotech-specific concepts behind industry boundaries.
- Put HKEX-specific discovery and filing logic behind market boundaries.
- Preserve curated JSON contracts because future auto-extraction can populate
  the same contracts.
- Prefer one-command workflows for users, while keeping lower-level commands for
  debugging and reproducibility.

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

Status: planned.

- Discover HKEX announcements, annual reports, interim reports, results
  announcements, company investor pages, and trial registries.
- Save source manifests before extraction.
- Keep source discovery separate from biotech analysis.

## Milestone C: Auto-Extract Into Current Contracts

Status: planned.

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
risks, evidence, and follow-up questions. A deterministic data-quality finding
flags missing inputs and validation warnings. A deterministic skeptical review
finding now produces counter-thesis risks from current structured inputs.
When target-price assumptions are supplied, the memo includes a
`Catalyst-Adjusted Valuation` section. Deeper LLM scientific critique is
pending.

- Combine pipeline, trial, catalyst, competition, cash runway, and valuation
  outputs.
- Generate a memo with bull case, bear case, evidence table, and watchlist
  decision.

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
