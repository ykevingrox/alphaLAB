# Product Requirements Document

## Product Name

Biotech Alpha Lab

## Purpose

Build an AI-assisted research system for long-term investing in innovative
drug companies, starting with Hong Kong-listed biotech names. The system should
help the user decide whether a company belongs in an observation pool, a core
candidate pool, or an exclusion pool.

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
11. Evidence links and confidence levels

## Non-Goals For MVP

- No automatic order placement.
- No broker API integration.
- No high-frequency or intraday trading.
- No full-market stock screener.
- No uncited investment recommendation.

## Target User

A private investor who wants to use large language models to improve research
quality, reduce manual reading burden, and maintain a disciplined watchlist for
long-term biotech investing.

## Primary Use Cases

### Single Company Research

Input a company name or ticker. The system returns a structured memo with
pipeline, cash runway, catalysts, competition, and risks.

### Pipeline Tracking

Track all disclosed pipeline assets for a company, including target, mechanism,
indication, stage, region rights, partner, and next milestone.

### Catalyst Monitoring

Maintain a calendar of expected clinical readouts, regulatory decisions,
conference presentations, annual results, financing events, and business
development announcements.

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
- Clear confidence and evidence markers
