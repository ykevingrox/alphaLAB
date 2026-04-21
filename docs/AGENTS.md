# Agent Contracts

Agents should behave like research specialists. Each agent must produce
structured output with citations and confidence, then the Investment Committee
Agent can combine their views.

## Shared Output Fields

Every agent output should include:

- `agent_name`
- `company`
- `as_of_date`
- `summary`
- `findings`
- `risks`
- `evidence`
- `confidence`
- `needs_human_review`

## Research Collector Agent

Purpose: collect public source material.

Inputs:

- Company name
- Stock ticker
- Market
- Date range

Outputs:

- Source list
- Download status
- Document type
- Publication date
- Reliability level

## Data Quality Agent

Purpose: flag missing curated inputs and validation warnings before a memo is
treated as decision-ready.

Current implementation note: the research pipeline emits a deterministic
`data_quality_agent` finding that checks whether pipeline asset, financial
snapshot, and competitor inputs were provided, and whether input validation
reported warnings.

Outputs:

- Missing input categories
- Input validation warning count
- Human-review flag

## Pipeline Agent

Purpose: extract pipeline assets from company documents.

Current implementation note: automatic document extraction is not implemented
yet. The CLI accepts curated JSON via `--pipeline-assets`, validates it with
`pipeline-validate`, and preserves evidence entries for each asset.

Outputs per asset:

- Drug or asset name
- Aliases or asset codes
- Modality
- Target
- Mechanism of action
- Indication
- Line of therapy
- Clinical stage
- Geography
- Commercial rights
- Partner
- Next expected milestone
- Evidence references

## Clinical Trial Agent

Purpose: match pipeline assets to clinical trial registry records.

Current implementation note: ClinicalTrials.gov search and trial normalization
are implemented. When curated assets are provided, the research pipeline also
searches by asset name and alias, deduplicates by registry ID, and creates
deterministic `TrialAssetMatch` records when asset terms appear in intervention
or title text.

Outputs per trial:

- Registry source
- Registry ID
- Trial title
- Sponsor
- Status
- Phase
- Conditions
- Interventions
- Enrollment
- Start date
- Primary completion date
- Completion date
- Endpoints
- Locations
- Results availability
- Matched pipeline asset
- Match confidence

## Regulatory Agent

Purpose: track regulatory progress.

Outputs:

- IND, NDA, BLA, or equivalent events
- Priority review, breakthrough therapy, fast track, orphan drug, or other
  designations
- Approval or rejection events
- Label expansion events
- Reimbursement and national drug list events where applicable

## Competitive Landscape Agent

Purpose: compare same-target and same-indication competitors.

Current implementation note: the CLI accepts curated competitor asset JSON via
`--competitors`, validates it with `competitor-validate`, matches competitor
assets to company pipeline assets by normalized target and indication, and emits
a `competitive_landscape_agent` finding.

Outputs:

- Competitor company
- Competitor asset
- Aliases or asset codes
- Target
- Indication
- Stage
- Differentiation
- Efficacy comparison
- Safety comparison
- Commercial position
- Threat level
- Match scope and confidence

## Cash Runway Agent

Purpose: estimate whether the company has enough capital to reach the next
meaningful milestone.

Current implementation note: the CLI accepts curated financial snapshot JSON via
`--financials`, validates it with `financial-validate`, estimates net cash,
monthly burn, and runway months, and emits a `cash_runway_agent` finding.

Outputs:

- Cash and equivalents
- Short-term debt
- Operating cash burn
- R&D expense
- Selling expense
- Estimated runway months
- Calculation method
- Human-review warnings
- Financing risk
- Dilution risk

## Valuation Agent

Purpose: provide valuation context, not a single magic price.

Current implementation note: the CLI accepts curated valuation snapshot JSON via
`--valuation`, validates it with `valuation-validate`, calculates market cap,
enterprise value, and revenue multiple where possible, and emits a
`valuation_agent` finding.

Outputs:

- Current market capitalization
- Enterprise value where available
- Revenue multiples where meaningful
- Calculation method
- Human-review warnings
- rNPV assumptions for key assets
- Scenario valuation
- Key assumptions
- Sensitivity points

## Technical Timing Agent

Purpose: support entry timing without overriding fundamental research.

Outputs:

- Trend state
- Support levels
- Resistance levels
- Volatility regime
- Liquidity warning
- Entry zone
- Stop invalidation level
- Confidence

## Scientific Skeptic Agent

Purpose: attack the thesis.

Current implementation note: the research pipeline emits a deterministic
`scientific_skeptic_agent` finding. It checks clinical coverage, unmatched
pipeline assets, missing competitor coverage, cash runway, valuation context,
and input validation warnings. It is a counter-thesis checklist, not an LLM
scientific review.

Outputs:

- Weakest evidence
- Trial design concerns
- Endpoint concerns
- Safety concerns
- Competition concerns
- Commercialization concerns
- Cash and dilution concerns
- What would falsify the bullish case

## Investment Committee Agent

Purpose: synthesize all agents into a decision-support memo.

Current implementation note: a full LLM committee agent is pending. The current
research pipeline creates a conservative deterministic memo from clinical trial
findings, pipeline matches, cash runway findings, catalysts, evidence, key
risks, and follow-up questions.

Outputs:

- Classification: `core_candidate`, `watchlist`, `avoid`, or
  `insufficient_data`
- Bull case
- Bear case
- Key assets
- Key catalysts
- Required follow-up research
- Suggested monitoring rules
- Portfolio fit notes
