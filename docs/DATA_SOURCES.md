# Data Sources

## Official And Public Sources

## Current Local Input Contracts

The current CLI supports two curated local JSON inputs while automatic document
extraction is still pending:

- Pipeline assets: generated with `pipeline-template`, checked with
  `pipeline-validate`, and passed to `research --pipeline-assets`.
- Financial snapshots: generated with `financial-template`, checked with
  `financial-validate`, and passed to `research --financials`.
- Competitor assets: generated with `competitor-template`, checked with
  `competitor-validate`, and passed to `research --competitors`.

All local input types preserve source references and validation warnings in the run
manifest.

### ClinicalTrials.gov

Use for global clinical trial records. The API endpoint is:

```text
https://clinicaltrials.gov/api/v2/studies
```

Useful fields:

- NCT ID
- Sponsor
- Official title
- Overall status
- Phase
- Conditions
- Interventions
- Enrollment
- Start date
- Primary completion date
- Completion date
- Locations
- Endpoints
- Results

The `/api/v2/version` endpoint returns the API version and data timestamp.

Current implementation:

- Queries ClinicalTrials.gov by company search term.
- When pipeline assets are supplied, also queries by asset name and aliases.
- Deduplicates normalized trial records by registry ID.
- Preserves raw query responses and normalized trial summaries in local
  artifacts.

### China Drug Clinical Trial Registration Platform

URL:

```text
https://www.chinadrugtrials.org.cn/
```

Use for China domestic drug trial registration and public disclosure. It is
maintained by the Center for Drug Evaluation under China's National Medical
Products Administration.

Expected use:

- Search trial registrations by company, drug, indication, or registration ID.
- Cross-check China-specific clinical progress.
- Preserve source screenshots or downloaded pages when automatic extraction is
  unstable.

### HKEX And HKEXnews

Use for:

- Prospectuses
- Annual reports
- Interim reports
- Announcements
- Investor disclosures
- Listing status and Chapter 18A identifiers

HKEX Chapter 18A is especially relevant for biotech companies because listing
documents must disclose core product details, regulatory status, and R&D stage.

Access note:

- HKEX main pages are accessible in the current environment.
- Direct command-line access to HKEXnews may be blocked by edge protection.
  Browser automation or a licensed data provider may be needed for reliable
  ingestion.

### Company Investor Relations

Use for:

- Pipeline charts
- Investor presentations
- Corporate updates
- Conference decks
- Product strategy
- Partnering announcements

Company materials must be treated as promotional until cross-checked against
trial registries, regulatory disclosures, and independent data.

### Regulatory Agencies

Useful sources:

- NMPA/CDE
- FDA
- EMA

Use for approval status, special designations, labels, and review milestones.

### Scientific Literature And Conferences

Useful sources:

- PubMed
- ASCO
- ESMO
- AACR
- WCLC
- Company posters and abstracts

Conference data can be market-moving but should be tagged by maturity:

- Abstract only
- Poster
- Oral presentation
- Peer-reviewed paper
- Regulatory label

## Paid Or Enhanced Sources To Consider Later

- Wind
- Bloomberg
- FactSet
- Refinitiv
- 医药魔方
- Insight
- 药智数据
- Cortellis
- Evaluate Pharma
- IQVIA

These are not required for the MVP, but they can substantially improve coverage
for competitive landscape, sales estimates, drug approval history, and market
data.

## Data Quality Rules

- Prefer official registry data over media summaries.
- Prefer filed documents over investor presentation claims.
- Preserve source date and retrieval timestamp.
- Mark inferred conclusions separately from directly sourced facts.
- Track stale data explicitly.
- Never let an LLM invent trial results, approval status, or market size.
