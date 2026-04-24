# Architecture

## Design Principle

The system should separate deterministic data processing from language-model
reasoning. Traditional code should fetch, parse, normalize, calculate, and
backtest. LLM agents should read documents, extract facts, compare narratives,
and write evidence-grounded memos.

The current product focus remains the Hong Kong biotech MVP, but new code should
avoid making biotech or Hong Kong assumptions part of the core orchestration
layer. Market-specific source discovery and industry-specific analysis should
sit behind adapters or plugins as the system grows.

## Compatibility Boundaries

Keep these boundaries stable while iterating:

- `CompanyIdentity`: company name, ticker, market, sector, aliases, and search
  term resolution. It can be backed by a local registry today and market data
  adapters later.
- `MarketAdapter`: future boundary for HKEX, SEC, A-share exchange filings,
  currencies, calendars, and source discovery.
- `IndustryPlugin`: future boundary for biotech pipeline analysis, then other
  sectors such as semiconductors, consumer, internet, or financials.
- `ResearchInput`: curated or auto-extracted inputs that feed deterministic
  research modules.
- `Evidence`: all material extracted facts must preserve source, source date,
  retrieval time, confidence, and whether the value is inferred.
- `ResearchResult`: structured output that can be rendered by CLI now and UI or
  API later.

## High-Level Flow

```text
Data Sources
    |
    v
Raw Ingestion
    |
    v
Normalized Store
    |
    v
Feature and Evidence Layer
    |
    v
Specialized Agents
    |
    v
Investment Committee Agent
    |
    v
Research Memo + Watchlist Decision + Target Price Range
```

## Online Runtime And Offline Fixtures

The intended product path is online:

- Resolve the company identity.
- Fetch current source materials from official or licensed sources.
- Parse and normalize those materials into structured research inputs.
- Preserve source links, source dates, validation warnings, and generated
  artifacts in the run manifest.

Offline fixtures are not the normal product path and should not be treated as a
fallback research mode. They are a regression harness. Their job is to make sure
known parsing behavior does not silently drift when code, prompts, source
formats, or extraction rules change.

Use fixtures to lock in lessons from real source documents. For example, when a
HKEX annual-results PDF teaches the system that `P1021` is a payload, `C9074`
is a partial table artifact from `BG-C9074`, or `BNT116` is a combination
partner asset, capture a small network-free sample and assert the expected
output.

The durable pattern is:

```text
online ingestion for fresh research
offline fixtures for regression safety
validators for schema and evidence quality
manifests for auditability
```

AI extraction can improve coverage, but it does not remove the need for
fixtures. LLM behavior, PDF text extraction, website layouts, disclosure
language, and source availability can all drift. Representative fixtures should
therefore be added whenever the project fixes an extraction bug, adds a source
type, or supports a materially different company disclosure style.

## Data Layers

### Raw Data

Original downloaded files and API responses:

- HKEX filings
- Annual reports
- Prospectuses
- Investor presentations
- Clinical trial registry responses
- Regulatory announcements
- Market data snapshots

### Normalized Data

Structured records:

- Company
- Security
- Pipeline asset
- Clinical trial
- Regulatory event
- Competitor asset
- Financial statement summary
- Catalyst
- Evidence citation

### Feature Layer

Derived metrics:

- Cash runway months
- R&D intensity
- Pipeline stage distribution
- Number of active trials
- Competition density by target and indication
- Upcoming catalysts by time window
- Valuation multiples where applicable
- Asset rNPV and probability of success assumptions
- Catalyst-adjusted target price scenarios

## Suggested Storage

MVP can begin with local files:

- `data/input/` (curated inputs; committed when small and non-secret)
- `data/input/generated/` (auto-drafted inputs; gitignored)
- `data/raw/` (gitignored)
- `data/processed/` (gitignored)
- `data/memos/` (gitignored)
- `data/traces/` (LLM JSONL traces; gitignored)
- `data/cache/` (macro-signals disk cache; gitignored)

Current CLI runs write:

- Input validation reports, company, ticker, and market in the run manifest
- ClinicalTrials.gov raw responses under `data/raw/clinicaltrials/`
- Normalized trial JSON and trial-summary CSV under
  `data/processed/single_company/`
- Catalyst-calendar CSV under `data/processed/single_company/`
- Pipeline asset and asset-trial match JSON under
  `data/processed/single_company/`
- Competitor asset and competitive-match JSON under
  `data/processed/single_company/`
- Optional cash-runway JSON under `data/processed/single_company/`
- Optional valuation JSON under `data/processed/single_company/`
- Curated target-price assumptions under `data/input/`
- Optional event-impact and target-price scenario JSON/CSV artifacts under
  `data/processed/single_company/`
- Watchlist scorecard JSON under `data/processed/single_company/`
- Local ranked watchlist JSON or CSV under a user-selected output path,
  including research-only position and concentration guardrails
- Local catalyst-change alert JSON or CSV under a user-selected output path
- Memo JSON and Markdown under `data/processed/single_company/` and
  `data/memos/`

Later versions can use:

- PostgreSQL for structured data
- pgvector or Qdrant for document retrieval
- Object storage for reports and PDFs
- TimescaleDB or ClickHouse for market data

## Agent Layer

Agents should receive structured input and return JSON-like output. They should
not freely browse and decide on their own without preserving sources.

The runtime is a small in-process orchestrator, not a distributed framework:

- `AgentGraph` resolves a topological order over agent nodes, runs each layer
  with bounded parallelism, and isolates per-agent errors so one failure does
  not abort the rest of the graph.
- `FactStore` holds structured inputs and upstream agent outputs keyed by fact
  name. Downstream agents declare their dependencies, and the FactStore
  renders them into each prompt.
- Deterministic agents (pipeline, competition, financials, skeptic, scorecard,
  ...) still run first. Opt-in LLM agents
  (`pipeline-triage`, `financial-triage`, `competition-triage`,
  `macro-context`, `scientific-skeptic`) consume the deterministic outputs
  and return structured findings validated against JSON schema.
- Per-run total and per-agent call budgets are enforced pre-dispatch by
  `BudgetEnforcingLLMClient`, and every LLM call is appended as JSONL under
  `data/traces/` for audit.

Target agent topology (canonical):

- Layer 0 — Data collection:
  - `data-collector-agent` (Stage C)
- Layer 1 — Domain specialists:
  - `pipeline-clinical-agent` (currently `pipeline-triage`)
  - `competition-agent` (currently `competition-triage`)
  - `macro-agent` (currently `macro-context`)
  - `catalyst-agent` (Stage B)
  - `kline-agent` (Stage B)
- Layer 2 — Valuation pod (Stage A):
  - `valuation-commercial-agent`
  - `valuation-pipeline-rnpv-agent`
  - `valuation-balance-sheet-agent`
  - `valuation-committee-agent`
- Layer 3 — Decision and publishing:
  - `investment-thesis-agent` (retain)
  - `scientific-skeptic-agent` (retain)
  - `report-synthesizer-agent` (Stage C)
  - `report-quality-agent` (Stage A)

Deterministic backbone agents that feed the LLM layers:

- Clinical Trial Agent (deterministic registry matching)
- Cash Runway Agent (deterministic burn/runway)
- Watchlist Scorecard Agent (deterministic bucket + monitoring rules)
- Data Quality Agent (deterministic input validation)
- Research Action Plan Agent (deterministic research-only sizing)

Current architecture consistency note:

- See `docs/ARCHITECTURE_AUDIT.md` for the latest alignment audit against the
  target multi-LLM-agent design.
- Current runtime is a hybrid state: pipeline/competition/macro specialists,
  scientific-skeptic, and investment-thesis are already LLM-based; the
  monolithic `valuation-specialist` is being decomposed into the pod in
  Sprint 6; kline/catalyst/report-quality/data-collector remain mostly
  deterministic or partially implemented.

## MVP Runtime

The first implementation can run as a CLI:

```bash
biotech-alpha report "DualityBio"

biotech-alpha company-report \
  --company "Akeso" \
  --ticker "9926.HK"

biotech-alpha research \
  --company "Akeso" \
  --ticker "9926.HK" \
  --pipeline-assets data/input/akeso_pipeline_assets.json \
  --financials data/input/akeso_financials.json \
  --competitors data/input/akeso_competitors.json \
  --valuation data/input/akeso_valuation.json \
  --target-price-assumptions data/input/akeso_target_price_assumptions.json
```

Current helper commands:

- `report` (quick one-command operator entry)
- `clinical-trials`
- `clinical-trials-version`
- `company-report`
- `pipeline-template`
- `pipeline-validate`
- `financial-template`
- `financial-validate`
- `competitor-template`
- `competitor-validate`
- `valuation-template`
- `valuation-validate`
- `conference-template`
- `conference-validate`
- `target-price-template`
- `target-price-validate`
- `event-impact`
- `research`
- `watchlist-rank`
- `catalyst-alerts`

Future UI:

- Single-company research page
- Pipeline table
- Catalyst calendar
- Evidence browser
- Watchlist and portfolio view
- Memo history

## Reproducibility

Each memo should record:

- Input company and ticker
- Data source versions and timestamps
- Raw files used
- Search terms used for registry lookups
- Input validation warnings
- Derived artifact paths
- Agent or deterministic finding versions where applicable
- Model name when LLM agents are introduced
- Generation timestamp
- Confidence score

## Safety Boundary

The architecture intentionally ends at research and decision support. Any future
trading execution layer must be separate, rule-based, logged, and manually
confirmed unless the user explicitly designs a different risk regime.

Target-price outputs are scenario ranges. They must preserve assumptions,
sources, and sensitivity points, and they must not be treated as automatic
trading instructions.
