# Product Requirements Document

## Product Name

Biotech Alpha Lab

## Purpose

Build an AI-assisted research system for long-term investing in innovative
drug companies, starting with Hong Kong-listed biotech names. The system should
help the user decide whether a company belongs in an observation pool, a core
candidate pool, or an exclusion pool. The system may also produce
catalyst-adjusted target price ranges when enough assumptions are available,
but it must remain a research and decision-support system.

The MVP remains focused on Hong Kong biotech companies. However, the product
should be designed so future market adapters and industry plugins can support
other Hong Kong sectors, US equities, and A-shares without rewriting the core
research orchestration.

## MVP Goal

Given one stock code or company name, generate a structured research memo that
covers:

1. Company overview
2. Financial summary
3. Cash runway
4. Pipeline table
5. Core asset analysis
6. Clinical trial progress
7. Competitive landscape
8. Catalyst calendar for the next 6-24 months
9. Key risks
10. Long-term investment score
11. Catalyst-adjusted valuation range when assumptions are available
12. Evidence links and confidence levels

Current implementation status:

- Implemented: one-command `company-report` entry that resolves a company
  identity, auto-discovers existing curated inputs, runs the current research
  pipeline, and writes a missing-input report.
- Implemented: first-pass HKEX annual-results source discovery and draft input
  generation for Hong Kong biotech pipeline assets and financial snapshots.
- Implemented: ClinicalTrials.gov search and normalization, including company,
  asset-name, and alias searches when curated assets are provided.
- Implemented: curated pipeline asset JSON input, validation, evidence capture,
  and deterministic asset-trial matching.
- Implemented: catalyst-calendar CSV from ClinicalTrials.gov primary completion
  dates and curated asset milestone windows.
- Implemented: curated financial snapshot JSON input, validation, and first-pass
  cash runway estimation.
- Implemented: curated competitor asset JSON input, validation, deterministic
  target/indication matching, and competitive landscape findings.
- Implemented: curated valuation snapshot JSON input, validation, enterprise
  value, and revenue multiple context where possible.
- Implemented: deterministic skeptical review that converts weak coverage,
  unmatched assets, short runway, valuation warnings, and input quality issues
  into counter-thesis risks.
- Implemented: deterministic watchlist scorecard with dimension scores, bucket,
  and monitoring rules for single-company follow-up prioritization.
- Implemented: local watchlist ranking, first-pass portfolio guardrails,
  latest-run filtering, and catalyst-change alerts across saved runs.
- Implemented: target-price assumption template, validation, deterministic
  rNPV scenario calculation, event-impact artifact output, and optional memo
  integration.
- Implemented: reproducible local artifacts, including manifest, raw responses,
  normalized records, CSV tables, memo JSON, and memo Markdown.
- Implemented: in-process `AgentGraph` + `FactStore` runtime with the
  following opt-in LLM agents — `provisional-pipeline`,
  `provisional-financial`, `pipeline-triage`, `financial-triage`,
  `competition-triage`, `strategic-economics`, `catalyst`, `data-collector`,
  `macro-context`, `scientific-skeptic`, `investment-thesis`, `valuation-commercial`,
  `valuation-rnpv`, `valuation-balance-sheet`, `valuation-committee`,
  `market-regime-timing`, `market-expectations`, `decision-debate`,
  `report-quality`,
  `report-synthesizer`, and compatibility-only `valuation-specialist` — with
  JSON schema validation,
  per-run and per-agent call budgets, and JSONL traces under `data/traces/`.
- Implemented: HK public market-data providers (Tencent / Yahoo) and macro
  live-signal providers (Yahoo / Stooq / HKMA) with disk cache and
  stale-if-error fallback.
- Implemented: ClinicalTrials.gov competitor discovery that feeds generated
  competitor candidate packs (review-gated, not treated as curated truth).
- Implemented: quick one-command `report "<company|ticker>"` entry that
  auto-enables auto-inputs, market data, macro signals, and the full LLM
  stack by default. When LLM env is missing or invalid the quick path
  auto-degrades to deterministic mode with an explicit terminal note;
  `company-report --llm-agents` still supports `--allow-no-llm` for the
  same fallback.
- Implemented (Stage A, Sprint 6; initial calibration complete): valuation pod
  decomposition into four specialist agents (commercial / pipeline-rNPV /
  balance-sheet / committee) and a standalone `report-quality-agent` that
  owns the publish gate. Biotech valuation framing now separates conservative
  rNPV floor, market-implied value, and scenario repricing; broader
  cross-ticker quality-gate review remains open.
- Implemented as opt-in scaffolds (Stage B, Sprint 7):
  `strategic-economics-agent`, `catalyst-agent`,
  `market-expectations-agent`, and `market-regime-timing-agent`.
- Implemented as opt-in scaffold (Stage C, Sprint 8):
  `data-collector-agent`, `report-synthesizer-agent`, and
  `decision-debate-agent`. Decision-debate output is artifact-only for now and
  can feed later same-company runs as lightweight decision-log memory.
  `report-quality-agent` now also receives a capped memo review excerpt plus
  synthesizer payload so it can review final report language for valuation,
  BD/platform, catalyst, timing, or trading-advice drift.
- Pending: broader company document ingestion beyond HKEX annual results,
  more robust financial statement parsing across interim/prospectus
  styles, US-market sibling market-data provider so auto-draft is not
  HK-only (explicit non-goal until after Stage C), automatic competitor
  discovery beyond ClinicalTrials.gov (company pages, filings), and
  calibrated historical catalyst-reaction backtests.

## Non-Goals For MVP

- No automatic order placement.
- No broker API integration.
- No high-frequency or intraday trading.
- No full-market stock screener.
- No uncited investment recommendation.
- No single-number target price without explicit assumptions and scenario
  range.

## Target User

A private investor who wants to use large language models to improve research
quality, reduce manual reading burden, and maintain a disciplined watchlist for
long-term biotech investing.

## Primary Use Cases

### Single Company Research

Input a company name or ticker. The system returns a structured memo with
pipeline, cash runway, catalysts, competition, and risks.

The high-level MVP command should work even when curated inputs are absent, but
the resulting report must clearly show which inputs were missing and which
conclusions require follow-up.

### Pipeline Tracking

Track all disclosed pipeline assets for a company, including target, mechanism,
indication, stage, region rights, partner, and next milestone.

### Catalyst Monitoring

Maintain a calendar of expected clinical readouts, regulatory decisions,
conference presentations, annual results, financing events, and business
development announcements.

### Catalyst-Adjusted Target Price Ranges

When a material catalyst changes, estimate how the event changes asset rNPV,
company equity value, and per-share target price ranges under bear, base, and
bull scenarios. The output should show assumptions, sensitivity, and confidence
before any price range.

### Contrarian Review

Generate a skeptical review that attacks the investment thesis, highlights weak
clinical evidence, crowded targets, cash burn, dilution risk, or valuation
overreach.

## Output Classification

Each company should be classified as one of:

- `core_candidate`: worth deeper monitoring and potential portfolio inclusion.
- `watchlist`: interesting but needs more evidence or better price.
- `avoid`: risk/reward is unattractive.
- `insufficient_data`: source coverage is not enough for a decision.

## Scoring Dimensions

- Pipeline quality
- Clinical progress
- Competitive position
- Commercialization potential
- Cash runway
- Management and execution
- Valuation reasonableness
- Catalyst-adjusted rNPV impact
- Catalyst visibility
- Risk asymmetry
- Evidence quality

## Required Evidence Standard

Each material claim should include:

- Claim
- Source URL or document ID
- Source date
- Extracted fact
- Confidence score
- Whether the claim is directly sourced or inferred

## Important Risks

- LLM hallucination
- Look-ahead bias in backtests
- Incomplete clinical trial registry data
- Company announcements that overstate pipeline potential
- False precision in target price outputs
- Crowded targets and fast-changing competitive landscapes
- Equity dilution risk in pre-profit biotech companies
- Regulatory and reimbursement uncertainty

## Success Criteria

The MVP is successful when it can produce a useful single-company memo for a
Hong Kong innovative drug company with:

- A pipeline table extracted from public sources
- At least one official clinical trial source where available
- A 6-24 month catalyst calendar
- A cash runway estimate
- A competition table for major assets
- A skeptical counter-thesis
- Catalyst-adjusted target price scenarios when assumptions are provided
- Clear confidence and evidence markers

Near-term success criteria for the current CLI slice:

- The user can generate and validate curated pipeline and financial input files.
- A research run can preserve raw ClinicalTrials.gov responses and normalized
  trial records.
- A research run can emit trial summary and catalyst calendar CSV files.
- A research run can produce a memo with source-backed evidence, key risks,
  curated competitive landscape findings, valuation context, skeptical review,
  watchlist scorecard, optional catalyst-adjusted valuation section, follow-up
  questions, and a manifest suitable for audit/reproduction.

Near-term success criteria for the target-price extension:

- The user can create and validate curated target-price assumption files.
- The system can calculate transparent asset rNPV values from those inputs.
- Catalyst alerts can be mapped to assumption deltas.
- The system can output bear, base, bull, and probability-weighted target price
  ranges.
- Every target-price output lists key assumptions, missing assumptions,
  sensitivity points, and human-review flags.
