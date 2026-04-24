# Agent Contracts

## Collaboration Handoff Protocol

This repository may be edited by multiple AI coding tools, including Codex and
Cursor. Treat the repository, tests, and handoff notes as the source of truth;
do not rely on chat history alone.

Before editing:

- Run `git status --short --branch`.
- Read `docs/HANDOFF.md`.
- Inspect uncommitted changes before touching related files.
- Do not revert user changes or another agent's work unless explicitly asked.

During work:

- Keep edits scoped to the current task.
- State the current task and exact next action before starting a substantive
  change.
- Prefer existing repo patterns over new abstractions.
- Preserve manual curated inputs as higher priority than generated drafts.
- Keep generated data under ignored paths such as `data/raw/`,
  `data/input/generated/`, `data/processed/`, and `data/memos/`.
- Update tests and docs when behavior changes.
- If the plan changes, update `docs/HANDOFF.md` in the same checkpoint.

Before handing off:

- Run the validation commands listed in `docs/HANDOFF.md`.
- Update `docs/HANDOFF.md` with current status and next best action.
- Leave a concise summary of changed files, validation results, and known
  blockers.
- Make the handoff plan concrete: one current task, one next action, acceptance
  criteria, and a short ordered queue. Avoid vague next steps such as
  "continue" or stale steps such as "commit current changes" when the working
  tree is already clean.
- If committing, make a small commit with a message that describes the completed
  behavior, not just the edited files.

Recommended fixed prompt when switching tools:

```text
先读 docs/HANDOFF.md，然后检查 git status 和最近 diff。
不要重做已经完成的事，评估当前状态后继续 Next Best Action。
```

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

## Watchlist Scorecard Agent

Purpose: turn the first-pass structured research package into a sortable
watchlist priority score.

Current implementation note: the research pipeline emits a deterministic
`watchlist_scorecard_agent` finding. It combines clinical progress,
pipeline-registry matching, cash runway, competition, valuation, data quality,
and skeptical review risks into a 0-100 score, bucket, and monitoring rules.

Outputs:

- Total score
- Bucket: `deep_dive_candidate`, `watchlist`, `needs_more_evidence`, or
  `low_priority`
- Dimension scores and rationales
- Monitoring rules
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

Purpose: provide valuation context and feed scenario valuation, not a single
magic price.

Current implementation note: the CLI accepts curated valuation snapshot JSON via
`--valuation`, validates it with `valuation-validate`, calculates market cap,
enterprise value, and revenue multiple where possible, and emits a
`valuation_agent` finding. Target-price scenario valuation is handled by
`event-impact` or `research --target-price-assumptions`.

Outputs:

- Current market capitalization
- Enterprise value where available
- Revenue multiples where meaningful
- Calculation method
- Human-review warnings
- Shares outstanding and current share price when available
- rNPV assumptions for key assets
- Scenario valuation
- Key assumptions
- Sensitivity points

## Catalyst Impact Agent

Purpose: translate catalyst changes into assumption deltas for valuation.

Current implementation note: the CLI can detect local catalyst calendar changes
with `catalyst-alerts`. Curated target-price assumptions can then map a catalyst
event to probability of success, launch timing, peak sales, or discount-rate
deltas through the `event-impact` command.

Outputs:

- Catalyst event type
- Affected asset
- Previous assumptions
- Updated assumptions
- Assumption deltas
- Evidence and rationale
- Human-review flag

## rNPV Scenario Agent

Purpose: convert asset assumptions and catalyst impacts into target price
ranges.

Outputs:

- Bear, base, and bull target prices
- Probability-weighted target price
- Asset rNPV by scenario
- Event value delta
- Implied upside or downside
- Key drivers
- Missing assumptions
- Sensitivity points
- Human-review flag

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
- Catalyst-adjusted target price range when assumptions are available

## Valuation Pod

Purpose: decompose valuation into specialist sub-agents that each own one
method, plus a committee agent that performs SOTP synthesis and conflict
arbitration.

The monolithic `valuation-specialist` remains available behind a
compatibility flag until the pod is fully validated on canonical HK tickers.

### Shared Pod Output Fields

All pod sub-agents (commercial, rNPV, balance-sheet) emit:

- `method`: one of `"multiple"`, `"dcf_simple"`, `"rNPV"`,
  `"balance_sheet_adjustment"`.
- `scope`: declared subset of the company this agent priced.
- `assumptions`: list of `{name, value, source, needs_human_review}`.
- `valuation_range`: `{bear, base, bull}` with declared `currency`.
- `sensitivity`: list of `{driver, delta, value_impact}`.
- `risks`: `AgentFinding.risks`-compatible.
- `evidence`: `AgentFinding.evidence`-compatible.
- `confidence`: float 0.0-1.0.
- `needs_human_review`: bool.

### Valuation Commercial Agent

Purpose: value commercialized products and recurring revenue.

Inputs:

- `financials_snapshot` (revenue, growth, gross margin, OPEX trend)
- `pipeline_triage_payload` (identify commercialized vs pipeline assets)
- `market_snapshot` (market cap, EV, shares outstanding, currency)
- Optional peer comparables from `peer_valuation` when present

Outputs (in addition to shared fields):

- `revenue_treatment`: `recurring`, `launch_ramp`, or `milestone_royalty`
- `comparable_peers`: list of `{company, method, multiple, source}`

Boundaries:

- Must NOT produce an rNPV for the same asset already priced by
  `valuation-pipeline-rnpv-agent`.
- Must NOT use preclinical or Phase 1 assets in commercial method.

### Valuation Pipeline rNPV Agent

Purpose: compute asset-level rNPV for pre-commercial pipeline assets.

Inputs:

- `pipeline_assets`
- `target_price_snapshot` including curated / auto-drafted
  `target_price_assumptions`
- `pipeline_triage_payload`

Outputs (in addition to shared fields):

- `asset_rnpv_rows`: list of `{asset, pos, peak_sales, launch_year,
  discount_rate, economics_share, rnpv_value}`
- `method_version`: `"default_rnpv_v1"` or curated override label

Boundaries:

- Must cite every PoS / peak sales / launch year assumption by field name
  pointing into `target_price_assumptions`.
- Must never invent numeric assumptions; if a required assumption is missing,
  mark `needs_human_review=true` and degrade the corresponding row.

### Valuation Balance Sheet Agent

Purpose: compute net cash, debt, and non-operating adjustments.

Inputs:

- `financials_snapshot` (cash, short-term debt, long-term debt,
  non-operating assets)
- `valuation_snapshot` (shares outstanding, market cap, currency)
- Currency of the reporting entity and of the market snapshot

Outputs (in addition to shared fields):

- `net_cash_adjustment`: signed amount in declared `currency`
- `debt_adjustment`: signed amount
- `non_operating_adjustments`: list of `{item, amount, source}`
- `fx_notes`: list of conversions applied, each with rate and source

Boundaries:

- Must honour the existing `RMB/CNY -> HKD` conversion used by
  `target_price.py` when the reporting currency differs from the market
  currency.
- Must NOT price operating assets; that is the commercial/rNPV agents'
  scope.

### Valuation Committee Agent

Purpose: synthesize the three pod sub-agents into an SOTP view with
explicit weights and conflict arbitration.

Inputs:

- Outputs of `valuation-commercial-agent`,
  `valuation-pipeline-rnpv-agent`, `valuation-balance-sheet-agent`
- `macro_context`
- `pipeline_triage_payload`
- `competition_triage_payload`

Outputs:

- `sotp_bridge`: ordered list of `{component, method, value_contribution}`
  that sums to `final_equity_value_range.base`.
- `method_weights`: `{commercial, rnpv, balance_sheet}` summing to 1.0.
- `conflict_resolution`: list of `{conflict, resolution, rationale}` when
  sub-agents disagree.
- `final_equity_value_range`: `{bear, base, bull}` in declared currency.
- `final_per_share_range`: `{bear, base, bull}` using
  committee-chosen share count.
- `currency`: explicit ISO code.
- `confidence`, `needs_human_review`.

Boundaries:

- Must NOT invent new numbers; every figure must trace to a pod sub-agent
  output or to a declared assumption.
- Must log weighting rationale so reviewers can reproduce the SOTP bridge.

## Report Synthesizer Agent

Purpose: produce the final committee-style report from all specialist
outputs. Deterministic-first by default; LLM writes transitions and the
Executive Verdict paragraph.

Inputs:

- All upstream agent findings
- Deterministic memo scaffold
- Current scorecard, action-plan, catalyst roadmap

Outputs:

- `executive_verdict_paragraph`: prose for the verdict section
- `section_transitions`: per-section opening sentences
- `needs_human_review`: true when any required input is missing

Boundaries:

- Must NOT change the memo's structural order.
- Must NOT change any numeric value rendered in deterministic sections.
- When upstream findings conflict, must surface the conflict rather than
  silently pick one side.

## Report Quality Agent

Purpose: independent editorial and consistency audit over the fully composed
report and every upstream agent finding. It is the publish gate.

Inputs:

- Composed memo markdown
- All `AgentFinding` entries from the run
- Run-level `scorecard`, `extraction_audit`, `input_validation` payloads
- Structured target-price and valuation pod outputs

Outputs:

- `publish_gate`: `pass`, `review_required`, or `block`
- `critical_issues`: list; any `block`-level reason appears here
- `consistency_findings`: cross-agent contradictions, currency drift,
  stale-evidence flags, bear vs bull logical inconsistency
- `missing_evidence_findings`: claims without an upstream evidence reference
- `language_quality_findings`: residual English fragments in zh-CN reports,
  over-claiming tone, removed disclaimer drift
- `valuation_coherence_findings`: committee vs per-share vs event-impact
  vs scorecard direction sanity
- `recommended_fixes`: list of concrete edits with target section path

Boundaries:

- Must NOT invent new market facts or new valuation numbers.
- Must NOT act as a second scientific-skeptic; the skeptic still owns the
  bear case.
- Must NOT silently overwrite any upstream finding. Any override must
  produce a `recommended_fixes` entry, not rewrite the original artifact.
- When the run uses `--no-llm`, the report quality agent is skipped; the
  existing rule-based `quality_gate` remains the deterministic fallback.

## Architecture Upgrade Target

To align with the multi-LLM-agent product direction, the next target agent
set is treated as the canonical role map. Sprint-level execution of this
topology is tracked in `docs/ROADMAP.md`.

- `data-collector-agent` (Stage C)
- `pipeline-clinical-agent` — currently `pipeline-triage`
- `competition-agent` — currently `competition-triage`
- `macro-agent` — currently `macro-context`
- `kline-agent` (Stage B)
- `catalyst-agent` (Stage B)
- Valuation pod (Stage A):
  - `valuation-commercial-agent`
  - `valuation-pipeline-rnpv-agent`
  - `valuation-balance-sheet-agent`
  - `valuation-committee-agent`
- `report-synthesizer-agent` (Stage C)
- `report-quality-agent` (Stage A)

Detailed gap analysis, contracts, and migration staging live in
`docs/ARCHITECTURE_AUDIT.md`.
