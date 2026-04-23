# Biotech Alpha Lab

Biotech Alpha Lab is an AI-assisted investment research workspace focused on
Hong Kong-listed innovative drug companies. The first version is deliberately
research-first: it helps collect evidence, structure pipeline data, track
clinical catalysts, compare competitors, produce long-term investment memos,
and generate first-pass catalyst-adjusted target price ranges when curated
assumptions are supplied. It does not place trades.

The current MVP stays focused on Hong Kong biotech, while keeping the
orchestration layer compatible with future market adapters and industry
plugins.

## Initial Scope

- Market: Hong Kong equities first, with A-share and US references as needed.
- Sector: innovative drug and biotech companies, especially HKEX Chapter 18A
  issuers.
- Style: long-term portfolio research, not short-term automated trading.
- Workflow: single-company research before portfolio ranking.
- Decision mode: decision support only; no broker integration in MVP.
- Price guidance: scenario target-price ranges only; no single-number price
  promise.

## Core Idea

Innovative drug companies cannot be evaluated only with classic cash-flow
metrics. The research object should be decomposed like this:

```text
Company -> Pipeline asset -> Target -> Indication -> Trial phase
        -> Competitive landscape -> Catalyst -> Probability-adjusted value
        -> Catalyst-adjusted target price range
```

The system treats pipeline quality, clinical progress, competitive intensity,
cash runway, upcoming catalysts, and explicit valuation assumptions as
first-class data.

## Repository Layout

```text
docs/
  PRD.md              Product definition and MVP boundaries
  ARCHITECTURE.md     System architecture and data flow
  AGENTS.md           Agent roles and structured output contracts
  DATA_SOURCES.md     Data sources and access notes
  ROADMAP.md          Suggested implementation sequence
  RUNBOOK.md          Step-by-step CLI operating guide
  TARGET_PRICE_MODEL.md
                      Catalyst-adjusted target price design
src/biotech_alpha/
  alerts.py          Local catalyst-calendar change alerts across saved runs
  auto_inputs.py     HKEX source discovery and draft input generation
  clinicaltrials.py   Minimal ClinicalTrials.gov API client
  company_report.py   One-command report orchestration
  competition.py      Competitive landscape inputs and deterministic matching
  conference.py       Conference catalyst inputs and validation
  financials.py       Financial snapshot loading and cash runway estimation
  models.py           Domain models for trials, pipeline assets, and memos
  pipeline.py         Pipeline asset loading and deterministic trial matching
  research.py         Single-company research pipeline orchestration
  scorecard.py        Deterministic watchlist scoring and monitoring rules
  skeptic.py          Deterministic skeptical counter-thesis review
  target_price.py     Target-price assumptions, rNPV, and scenarios
  valuation.py        Valuation snapshot loading and context metrics
  watchlist.py        Local ranking over saved single-company research runs
  agents.py           Agent interface sketches
  cli.py              Small command-line entry point
tests/
  test_alerts.py
  test_auto_inputs.py
  test_cli.py
  test_clinicaltrials.py
  test_company_report.py
  test_competition.py
  test_conference.py
  test_financials.py
  test_pipeline.py
  test_research.py
  test_scorecard.py
  test_skeptic.py
  test_target_price.py
  test_valuation.py
  test_watchlist.py
```

## Quick Start

For the full operating guide, see [docs/RUNBOOK.md](docs/RUNBOOK.md).

Run the test suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Try the ClinicalTrials.gov client:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli clinical-trials Akeso --limit 3
```

Run a one-command first-pass report. It uses any matching curated inputs found
under `data/input`, still runs when inputs are missing, and writes a
`missing_inputs_report.json` for the next pass:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli company-report \
  --company "Akeso" \
  --ticker "9926.HK" \
  --limit 20
```

For the fastest UX ("company name in, report out"), use the new quick command:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli report "DualityBio"
```

Quick-mode defaults:

- Prints progress stages, a compact result summary, and the main artifact paths.
  Use `--json` when you need the compact machine-readable summary instead.
- Enables `--auto-inputs`.
- Enables `hk-public` market data auto-draft.
- Enables macro live-signals (`yahoo-hk`) with cache.
- Enables ClinicalTrials.gov competitor discovery for generated competitor
  candidate packs.
- Enables the full LLM stack by default:
  `pipeline-triage`, `financial-triage`, `competition-triage`,
  `macro-context`, `scientific-skeptic`.
- If LLM client initialization fails (for example missing API key), the command
  fails fast by default. Use `--allow-no-llm` only when you explicitly want to
  continue in deterministic-only mode.

For the HK biotech MVP, add `--auto-inputs` to let the system discover the
latest HKEX annual results announcement, download the source PDF, extract text,
generate draft pipeline, financial, and conference-catalyst input files,
validate them, and then run the report:

```bash
.venv/bin/python -m biotech_alpha.cli company-report \
  --company "映恩生物" \
  --ticker "09606.HK" \
  --auto-inputs \
  --limit 20
```

Create and validate curated input files:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli pipeline-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_pipeline_assets.json

PYTHONPATH=src python3 -m biotech_alpha.cli pipeline-validate \
  data/input/akeso_pipeline_assets.json

PYTHONPATH=src python3 -m biotech_alpha.cli financial-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_financials.json

PYTHONPATH=src python3 -m biotech_alpha.cli financial-validate \
  data/input/akeso_financials.json

PYTHONPATH=src python3 -m biotech_alpha.cli competitor-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_competitors.json

PYTHONPATH=src python3 -m biotech_alpha.cli competitor-validate \
  data/input/akeso_competitors.json

PYTHONPATH=src python3 -m biotech_alpha.cli valuation-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_valuation.json

PYTHONPATH=src python3 -m biotech_alpha.cli valuation-validate \
  data/input/akeso_valuation.json

PYTHONPATH=src python3 -m biotech_alpha.cli conference-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_conference_catalysts.json

PYTHONPATH=src python3 -m biotech_alpha.cli conference-validate \
  data/input/akeso_conference_catalysts.json

PYTHONPATH=src python3 -m biotech_alpha.cli target-price-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_target_price_assumptions.json

PYTHONPATH=src python3 -m biotech_alpha.cli target-price-validate \
  data/input/akeso_target_price_assumptions.json

PYTHONPATH=src python3 -m biotech_alpha.cli event-impact \
  --company "Akeso" \
  --assumptions data/input/akeso_target_price_assumptions.json
```

Run the first single-company research pipeline:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli research \
  --company "Akeso" \
  --ticker "9926.HK" \
  --pipeline-assets data/input/akeso_pipeline_assets.json \
  --financials data/input/akeso_financials.json \
  --competitors data/input/akeso_competitors.json \
  --valuation data/input/akeso_valuation.json \
  --conference-catalysts data/input/akeso_conference_catalysts.json \
  --target-price-assumptions data/input/akeso_target_price_assumptions.json \
  --limit 20
```

Rank saved single-company runs into a local watchlist:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank

PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank --latest-only

PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank \
  --format csv \
  --output data/processed/watchlist_rank.csv

PYTHONPATH=src python3 -m biotech_alpha.cli catalyst-alerts
```

The first-pass pipeline searches ClinicalTrials.gov, normalizes trial records,
optionally loads disclosed pipeline assets from JSON, matches assets to trial
interventions or titles, derives clinical catalysts from future primary
completion dates and disclosed milestones, creates a conservative memo, and
saves reproducible artifacts under:

```text
data/raw/clinicaltrials/
data/processed/single_company/
data/memos/
```

Each saved run includes a manifest JSON, raw registry responses, normalized
trial JSON, a trial-summary CSV table, catalyst-calendar CSV table, pipeline
asset JSON, asset-trial match JSON, competitor asset JSON, competitive-match
JSON, optional cash-runway JSON, optional valuation JSON, optional
event-impact JSON, optional target-price scenario JSON and CSV, and memo
outputs. The manifest also records input validation reports so placeholder
fields and other data-quality warnings remain attached to the run.

When `--pipeline-assets` is provided, the pipeline searches ClinicalTrials.gov
by the company search term plus each asset `name` and `aliases`, then deduplicates
trials by registry ID before matching assets to trials. Use `--no-asset-queries`
to restrict a run to the company-level search only.

Pipeline asset JSON can be manually curated first and later generated by a
document extraction step:

```json
{
  "assets": [
    {
      "name": "Ivonescimab",
      "aliases": ["AK112", "SMT112"],
      "target": "PD-1/VEGF",
      "indication": "NSCLC",
      "phase": "Phase 3",
      "next_milestone": "2026 readout",
      "evidence": [
        {
          "claim": "Ivonescimab appears in the disclosed pipeline table.",
          "source": "company-presentation.pdf",
          "confidence": 0.8
        }
      ]
    }
  ]
}
```

Financial snapshot JSON is also intentionally small at first:

```json
{
  "as_of_date": "2025-12-31",
  "currency": "HKD",
  "cash_and_equivalents": 1200000000,
  "short_term_debt": 300000000,
  "quarterly_cash_burn": 150000000,
  "operating_cash_flow_ttm": -650000000,
  "source": "annual-report.pdf",
  "source_date": "2026-03-28"
}
```

`quarterly_cash_burn` is used first when provided. If it is omitted, negative
`operating_cash_flow_ttm` is converted into monthly burn.

Competitive landscape JSON follows the same curated-first pattern:

```json
{
  "competitors": [
    {
      "company": "Competitor Bio",
      "asset_name": "Rival Drug",
      "aliases": ["RVD-001"],
      "target": "PD-1/VEGF",
      "indication": "NSCLC",
      "phase": "Phase 3",
      "differentiation": "Comparable target and indication; confirm data maturity.",
      "evidence": [
        {
          "claim": "Rival Drug is disclosed as a Phase 3 PD-1/VEGF program.",
          "source": "competitor-presentation.pdf",
          "source_date": "2026-03-28",
          "confidence": 0.7
        }
      ]
    }
  ]
}
```

Competitor assets are matched to company pipeline assets by normalized target
and indication, then surfaced as competitive landscape findings and risks.

Valuation snapshot JSON provides market context without creating a target price:

```json
{
  "as_of_date": "2026-04-20",
  "currency": "HKD",
  "market_cap": 25000000000,
  "cash_and_equivalents": 1200000000,
  "total_debt": 300000000,
  "revenue_ttm": 1500000000,
  "source": "market-data-snapshot",
  "source_date": "2026-04-20"
}
```

If `market_cap` is omitted, provide `share_price` and `shares_outstanding`.
The current valuation agent calculates enterprise value and revenue multiple
when revenue is available.

Target-price work is intentionally separated from the current valuation
snapshot. The model is documented in
[docs/TARGET_PRICE_MODEL.md](docs/TARGET_PRICE_MODEL.md). The CLI can generate
and validate curated target-price assumption files, then calculate event-impact
deltas, asset rNPV, bear/base/bull ranges, and a probability-weighted target
price through `event-impact` or `research --target-price-assumptions`.

The memo also includes a deterministic skeptical review. It turns missing
inputs, weak clinical coverage, unmatched assets, short runway, high valuation
multiples, and crowded competition into explicit counter-thesis risks.

The CLI also emits a deterministic watchlist scorecard. It combines clinical
progress, pipeline-registry matching, cash runway, competition, valuation, data
quality, and skeptical review risks into a `watchlist_score` and
`watchlist_bucket`, plus monitoring rules in the saved scorecard artifact.
Saved run manifests can then be ranked with `watchlist-rank`, which reads each
manifest's scorecard and optional pipeline, runway, and valuation artifacts to
produce a JSON or CSV watchlist table. The ranked table includes conservative,
research-only position guardrails such as `research_position_limit_pct`,
`sizing_tier`, concentration counts, and data-quality flags. Use
`--latest-only` to keep only the newest saved run per company or ticker.

The `catalyst-alerts` command compares each company's latest two saved catalyst
calendars and reports added, removed, date-changed, and window-changed
catalysts.

## Current Data Reality

Free and official data is enough for a useful MVP:

- ClinicalTrials.gov provides a structured API for global clinical trials.
- China's drug clinical trial registration platform is useful for domestic
  trial disclosure.
- HKEX filings, annual reports, prospectuses, and announcements are critical
  for pipeline and capital market disclosures.

Professional coverage will eventually need paid or semi-paid data sources for
cleaner market data, drug databases, and full competitive landscape coverage.

## Guardrails

- Every conclusion should cite evidence.
- Each agent should return structured data, not only prose.
- The system should preserve data snapshots used for each memo.
- Backtests must avoid look-ahead bias.
- LLM output should support research decisions, not execute trades.
- Target-price outputs should be ranges with assumptions, not precise
  predictions or automatic trading instructions.
