# Roadmap

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
Scenario valuation and deeper LLM scientific critique are pending.

- Combine pipeline, trial, catalyst, competition, cash runway, and valuation
  outputs.
- Generate a memo with bull case, bear case, evidence table, and watchlist
  decision.

## Phase 7: Portfolio Layer

Status: partially implemented. The current CLI emits a deterministic
single-company watchlist scorecard with dimension scores, a bucket, and
monitoring rules. It can also rank saved single-company runs into a local JSON
or CSV watchlist table with first-pass research-only position sizing and
concentration guardrails. Alerting and more advanced portfolio controls are
pending.

- Add watchlist scoring.
- Add local cross-run watchlist ranking.
- Add first-pass position sizing guardrails.
- Track first-pass concentration by target and indication.
- Track concentration by company and market.
- Add alerting for catalyst changes.

## Phase 8: Technical Timing And Backtesting

Status: not started.

- Add market data ingestion.
- Add long-term technical trend analysis.
- Backtest watchlist entry rules.
- Avoid look-ahead bias by using historical source snapshots.
