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

## Pipeline Agent

Purpose: extract pipeline assets from company documents.

Outputs per asset:

- Drug or asset name
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

Outputs:

- Competitor company
- Competitor asset
- Target
- Indication
- Stage
- Differentiation
- Efficacy comparison
- Safety comparison
- Commercial position
- Threat level

## Cash Runway Agent

Purpose: estimate whether the company has enough capital to reach the next
meaningful milestone.

Outputs:

- Cash and equivalents
- Short-term debt
- Operating cash burn
- R&D expense
- Selling expense
- Estimated runway months
- Financing risk
- Dilution risk

## Valuation Agent

Purpose: provide valuation context, not a single magic price.

Outputs:

- Current market capitalization
- Enterprise value where available
- Revenue multiples where meaningful
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
