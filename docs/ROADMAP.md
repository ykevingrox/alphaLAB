# Roadmap

## Phase 0: Repository Foundation

- Define project scope.
- Document agent contracts.
- Create lightweight Python package.
- Verify ClinicalTrials.gov access.

## Phase 1: Single Company Clinical Trial Research

- Search ClinicalTrials.gov by company and asset.
- Normalize trial records.
- Extract trial status, dates, phase, condition, and intervention.
- Produce a trial summary table.

## Phase 2: Pipeline Extraction

- Add document ingestion for company presentations and reports.
- Extract pipeline assets into structured records.
- Match assets against trial records.
- Store evidence references.

## Phase 3: Catalyst Calendar

- Generate expected catalyst windows from:
  - Primary completion dates
  - Company guidance
  - Regulatory milestones
  - Conferences
  - Earnings and annual results

## Phase 4: Cash Runway

- Parse financial statements.
- Estimate quarterly and annual cash burn.
- Calculate runway under base, optimistic, and conservative assumptions.

## Phase 5: Competitive Landscape

- Group assets by target, mechanism, indication, and geography.
- Compare stage, data maturity, safety, efficacy, and commercialization status.
- Mark crowded targets and weak differentiation.

## Phase 6: Investment Memo

- Combine pipeline, trial, catalyst, competition, cash runway, and valuation
  outputs.
- Generate a memo with bull case, bear case, evidence table, and watchlist
  decision.

## Phase 7: Portfolio Layer

- Add watchlist scoring.
- Add position sizing guardrails.
- Track concentration by target, indication, company, and market.
- Add alerting for catalyst changes.

## Phase 8: Technical Timing And Backtesting

- Add market data ingestion.
- Add long-term technical trend analysis.
- Backtest watchlist entry rules.
- Avoid look-ahead bias by using historical source snapshots.
