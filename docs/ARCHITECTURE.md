# Architecture

## Design Principle

The system should separate deterministic data processing from language-model
reasoning. Traditional code should fetch, parse, normalize, calculate, and
backtest. LLM agents should read documents, extract facts, compare narratives,
and write evidence-grounded memos.

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
Research Memo + Watchlist Decision
```

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

## Suggested Storage

MVP can begin with local files:

- `data/input/`
- `data/raw/`
- `data/processed/`
- `data/memos/`

Current CLI runs write:

- Input validation reports in the run manifest
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

Recommended agents:

- Research Collector Agent
- Pipeline Agent
- Clinical Trial Agent
- Regulatory Agent
- Competitive Landscape Agent
- Cash Runway Agent
- Valuation Agent
- Technical Timing Agent
- Risk Agent
- Scientific Skeptic Agent
- Investment Committee Agent

## MVP Runtime

The first implementation can run as a CLI:

```bash
biotech-alpha research \
  --company "Akeso" \
  --ticker "9926.HK" \
  --pipeline-assets data/input/akeso_pipeline_assets.json \
  --financials data/input/akeso_financials.json \
  --competitors data/input/akeso_competitors.json \
  --valuation data/input/akeso_valuation.json
```

Current helper commands:

- `clinical-trials`
- `clinical-trials-version`
- `pipeline-template`
- `pipeline-validate`
- `financial-template`
- `financial-validate`
- `competitor-template`
- `competitor-validate`
- `valuation-template`
- `valuation-validate`
- `research`

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
