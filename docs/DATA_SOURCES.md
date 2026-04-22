# Data Sources

## Official And Public Sources

## Current Local Input Contracts

The current CLI supports six curated local JSON inputs. The HK biotech MVP also
has first-pass automatic extraction from HKEX annual-results PDFs for draft
pipeline, financial, and conference-catalyst inputs; broader document ingestion
and higher-recall extraction are still pending:

- Pipeline assets: generated with `pipeline-template`, checked with
  `pipeline-validate`, and passed to `research --pipeline-assets`.
- Financial snapshots: generated with `financial-template`, checked with
  `financial-validate`, and passed to `research --financials`.
- Competitor assets: generated with `competitor-template`, checked with
  `competitor-validate`, and passed to `research --competitors`.
- Valuation snapshots: generated with `valuation-template`, checked with
  `valuation-validate`, and passed to `research --valuation`.
- Conference catalysts: generated with `conference-template`, checked with
  `conference-validate`, and passed to `research --conference-catalysts`.
- Target-price assumptions: generated with `target-price-template` and checked
  with `target-price-validate`. These inputs can be used by
  `event-impact --assumptions ...` and can also be passed to
  `research --target-price-assumptions`.

Research-run input types preserve source references and validation warnings in
the run manifest. Target-price assumptions feed deterministic event-impact and
rNPV scenario outputs, and those artifacts can be attached to research memos.

## Online Collection And Regression Fixtures

The system is designed to run online for real research. A normal report should
fetch or query current sources such as HKEXnews, ClinicalTrials.gov, company IR
pages, conference disclosures, regulatory databases, and future market-data
connectors.

Network-free fixtures serve a different purpose. They are small, frozen samples
used by tests to prevent parsing regressions. They are not a substitute for
fresh source collection and should not be used as stale research inputs for live
reports.

Fixture guidance:

- Add a fixture when a real source exposes an extraction edge case.
- Keep fixture content as small as possible while preserving the bug or behavior
  being tested.
- Assert both positive and negative behavior: what should be extracted, and
  what should not be extracted.
- Prefer source-backed examples over synthetic-only examples when possible.
- Keep generated runtime outputs out of git; commit only intentional fixtures
  and tests.

Target-price assumptions need curated inputs for:

- Current share price and shares outstanding
- Cash, debt, and expected dilution
- Asset-level peak sales assumptions
- Probability of success by asset, phase, and indication
- Economics share, royalties, or profit split
- Launch year and discount rate
- Event-impact assumptions for readouts, approvals, delays, financing, and
  competitor data changes

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
- Shares outstanding and financing terms for target-price assumptions

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

For target-price modeling, investor materials can provide management guidance
for addressable markets, launch timing, and pipeline milestones, but those
assumptions should be tagged as company-sourced and reviewed skeptically.

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

For target-price ranges, paid or enhanced data can also help with:

- Consensus forecasts
- Peer valuation multiples
- Epidemiology and addressable population estimates
- Historical probability-of-success benchmarks
- Historical catalyst-event price reactions

## Data Quality Rules

- Prefer official registry data over media summaries.
- Prefer filed documents over investor presentation claims.
- Preserve source date and retrieval timestamp.
- Mark inferred conclusions separately from directly sourced facts.
- Track stale data explicitly.
- Never let an LLM invent trial results, approval status, or market size.
- Never let a target-price model hide assumptions behind a single precise
  number.
