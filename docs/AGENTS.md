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

Stage B implementation note: optional `catalyst` is wired for
`company-report --llm-agents ...` as an independent input layer, not a final
decision layer. It consumes `catalyst_calendar_payload`, `event_impact_payload`,
`target_price_snapshot`, pipeline facts, source-text excerpts, and optional
strategic/market/timing payloads. It evaluates event quality before
`market-expectations-agent`, `market-regime-timing-agent`, and
`valuation-committee-agent` consume the catalyst payload.

Outputs:

- Catalyst event type
- Affected asset
- Previous assumptions
- Updated assumptions
- Assumption deltas
- Evidence and rationale
- Human-review flag

Stage B LLM outputs:

- `catalyst_events`: event, asset, date/window, binary/non-binary type, and
  source evidence.
- `expected_value_direction`: positive, negative, mixed, or unclear.
- `event_confidence`: confidence in event timing and relevance.
- `expectation_risk`: whether the event appears crowded, underappreciated, or
  already priced in.
- `repricing_paths`: success, failure, delay, and ambiguous-readout scenarios.
- `valuation_inputs_to_update`: which PoS, launch timing, peak sales, discount
  rate, or retained-economics assumptions may change.

Boundaries:

- Must not issue entry/exit instructions.
- Must not invent event probabilities when deterministic assumptions are
  absent; it can label direction and evidence quality.
- Must feed downstream expectation, timing, and valuation agents rather than
  replacing them.

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
explicit weights, conflict arbitration, and biotech-specific valuation
framing.

Inputs:

- Outputs of `valuation-commercial-agent`,
  `valuation-pipeline-rnpv-agent`, `valuation-balance-sheet-agent`
- `strategic_economics_payload` when available
- `market_expectations_payload` when available
- `market_regime_timing_payload` when available
- `pipeline_triage_payload`
- `competition_triage_payload`

Outputs:

- `sotp_bridge`: ordered list of `{component, method, value_contribution}`
  that sums to `final_equity_value_range.base`.
- `method_weights`: `{commercial, rnpv, balance_sheet}` summing to 1.0.
- `conservative_rnpv_floor`: cash-adjusted value range from core assets
  under conservative assumptions.
- `market_implied_value`: explanation of what the current market value appears
  to price in; can be qualitative when data is insufficient.
- `scenario_repricing_range`: plausible value change under catalyst, BD,
  financing, or sector-regime changes.
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
- Must NOT describe conservative rNPV as the only fair value for a
  pre-revenue biotech. It must explain any market premium or state that the
  premium is unexplained.

## Strategic Economics Agent

Purpose: explain how a biotech company captures shareholder value from its
science. This role is broader than a BD extractor and only analyzes platform
reuse when there is company-specific evidence.

Current implementation note: the first LLM scaffold is wired as optional
`strategic-economics`. It consumes pipeline facts, optional pipeline and
competition triage payloads, financial/valuation snapshots, macro context,
source-text excerpts, and fallback evidence. Its payload is available to
`market-expectations` and `valuation-committee` when requested in the same
company-report run.

Inputs:

- `pipeline_assets` and `pipeline_triage_payload`
- Evidence excerpts with BD, licensing, regional-rights, NewCo, royalty,
  milestone, cost-sharing, or commercialization language
- `financials_snapshot`
- `competition_triage_payload`

Outputs:

- `retained_economics_map`: asset, region, partner, and economics-share rows
  when disclosed or inferable from explicit evidence.
- `bd_validation_events`: collaborations, upfronts, milestones, royalties,
  cost-sharing, or partner-validation events.
- `partner_quality_assessment`: partner execution capability and strategic
  fit.
- `commercialization_path`: self-commercialization, partner-led,
  region-split, royalty-only, or unclear.
- `value_capture_score`: 0-100 evidence-backed score.
- `strategic_premium_discount`: premium/discount drivers for the valuation
  committee.
- `needs_human_review`.

Boundaries:

- Must NOT count headline milestone totals as guaranteed value.
- Must distinguish "science validated by partner" from "economics retained by
  the listed company".
- Must NOT force a platform thesis when the company has no platform evidence.

## Market Expectations Agent

Purpose: explain what the current market cap appears to imply before any
agent declares the stock cheap or expensive.

Current implementation note: the first LLM scaffold is wired as optional
`market-expectations`. It consumes valuation snapshot, valuation pod and
committee payloads, macro context, optional `technical_feature_payload`, and
optional `market_sentiment_payload` / `market_regime_timing_payload`.
`company-report --technical-features yfinance` can thread the technical payload
when `market-expectations` or `market-regime-timing` is requested.

Inputs:

- `market_snapshot`, `valuation_snapshot`, historical price and market-cap
  context when available
- `target_price_scenarios` and valuation pod outputs
- `strategic_economics_payload`
- Catalyst calendar and market-regime/timing payload when available

Outputs:

- `market_implied_assumptions`: assumptions needed to justify observed market
  value.
- `valuation_band_context`: historical floor, mid-band, extended band, or
  unknown.
- `rnpv_gap_explanation`: why observed price differs from conservative rNPV.
- `expectation_risk_flags`: assumptions that could break the valuation band.
- `evidence_gaps`.
- `confidence`.

Boundaries:

- Must NOT treat current price as proof of fair value.
- Must NOT call a stock overvalued solely because conservative rNPV is below
  price.

## Market Regime Timing Agent

Purpose: combine macro, technical, sector sentiment, and fund-flow context into
a research-only timing view. This absorbs the current `macro-context` role and
the planned k-line specialist into one timing layer.

Current implementation note: the first LLM scaffold is wired as optional
`market-regime-timing`. It consumes existing `macro_context`, optional
`macro_context_payload`, optional `technical_feature_payload`, and optional
`market_sentiment_payload`.
`company-report --technical-features yfinance` can thread the technical payload
when `market-regime-timing` or `market-expectations` is requested. It is not
yet in the quick-report default stack because technical payload collection is
still opt-in.

Inputs:

- Existing `macro-context` output
- Deterministic technical feature payloads (returns, volume trend,
  moving-average state, volatility state, relative strength, drawdown)
- `market_sentiment_payload`: deterministic proxy assembled from existing macro
  and technical payloads, including sentiment state, liquidity proxy, relative
  strength, and fund-flow proxy state.
- External sector sentiment, liquidity, valuation-band, and real fund-flow
  feeds when available later.

Outputs:

- `timing_view`: `favorable`, `neutral`, `fragile`, `avoid_chasing`, or
  `de_risk_watch`.
- `horizon`: `1-3 months`, `3-6 months`, or `6-12 months`.
- `macro_regime`, `technical_state`, `sentiment_state`.
- `key_triggers`.
- `invalidation_signals`.
- `confidence`.

Boundaries:

- Must remain research-only and must NOT produce entry/exit orders.
- Must keep long-term fundamental view separate from current timing view.
- Must not fetch market data directly. It consumes source-backed provider
  payloads and deterministic feature outputs so provider failures stay outside
  the prompt.

## Decision Debate Agent

Purpose: add a TradingAgents-inspired bull/bear debate and decision log without
adding a new orchestration framework. It records why the research view stays
avoid/watchlist/core-research/insufficient-data and keeps that fundamental view
separate from market timing.

Current implementation note: optional `decision-debate` is wired for
`company-report --llm-agents ...`. It consumes data quality, strategic
economics, catalyst, valuation pod, market expectations, market-regime/timing,
scorecard, and deterministic memo scaffold payloads. It can feed
`report-synthesizer` and `report-quality` when requested in the same run. When
saved, it writes an artifact-only `<run_id>_decision_log.json`; memo prose is
not changed yet. Future runs for the same company can feed recent decision-log
artifacts back into this agent as lightweight memory so it can distinguish a
real view change from repeated unresolved evidence gaps.

Outputs:

- `bull_case` and `bear_case`: concise source-keyed debate claims.
- `fundamental_view`: `avoid`, `watchlist`, `core_research`, or
  `insufficient_data`.
- `timing_view`: `favorable`, `neutral`, `fragile`, `avoid_chasing`,
  `de_risk_watch`, or `unknown`.
- `decision_log`: assumptions, revisit reasons, invalidation triggers,
  evidence gaps, and next review triggers.
- Prior decision-log memory, when available, is used only for changed
  assumptions, repeated gaps, and invalidated triggers.

Boundaries:

- Must NOT output buy/sell/entry/exit/position-size instructions.
- Must NOT change deterministic memo decisions or numeric valuation outputs.
- Must keep debate claims tied to supplied payload keys.

## Report Synthesizer Agent

Purpose: produce the final committee-style report from all specialist
outputs. Deterministic-first by default; LLM writes transitions and the
Executive Verdict paragraph.

Current implementation note: optional `report-synthesizer` is wired for
`company-report --llm-agents ...`. It consumes a deterministic
`memo_scaffold_payload`, upstream finding snapshots, Stage B/C payloads,
scorecard, target-price snapshot, and valuation committee payload. When its
payload is present during saved LLM runs, the memo renderer inserts only the
executive verdict paragraph and configured section transitions.

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

## Data Collector Agent

Purpose: audit whether deterministic ingestion and source evidence are good
enough to support publication. It does not fetch new data and does not rewrite
investment conclusions.

Current implementation note: optional `data-collector` is wired for
`company-report --llm-agents ...`. It consumes `input_validation_payload`,
source-text excerpts, fallback source documents, pipeline/financial/valuation
snapshots, competition, catalyst calendar, target-price snapshot, and macro
context. Its payload feeds `report-quality` when both agents are requested.

Outputs:

- `run_verdict`: `publish_ready`, `needs_more_evidence`, or
  `insufficient_data`.
- `domain_verdicts`: per-domain verdicts with evidence quality, stale sources,
  missing evidence, and rationale.
- `priority_gaps`: highest-priority evidence gaps.
- `confidence`.
- `needs_human_review`.

Boundaries:

- Must NOT invent missing source dates, trial IDs, financial values, or
  catalyst dates.
- Must NOT block on ordinary soft warnings; classify the domain and explain
  review burden.
- Must NOT change upstream facts or memo text.

## Report Quality Agent

Purpose: independent editorial and consistency audit over the fully composed
report and every upstream agent finding. It is the publish gate.

Inputs:

- Composed memo markdown
- All `AgentFinding` entries from the run
- Run-level `scorecard`, `extraction_audit`, `input_validation` payloads
- Structured target-price and valuation pod outputs
- `decision_debate_payload`, when present, so timing labels and decision-log
  triggers can be checked for trading-language drift or missing observability
- `memo_review_payload` and `report_synthesizer_payload`, when present, so the
  quality gate can inspect final report language for overstated price, BD,
  platform, catalyst, timing, or trading-advice drift without rewriting prose

Outputs:

- `publish_gate`: `pass`, `review_required`, or `block`
- `critical_issues`: list; any `block`-level reason appears here
- `consistency_findings`: cross-agent contradictions, currency drift,
  stale-evidence flags, bear vs bull logical inconsistency
- `missing_evidence_findings`: claims without an upstream evidence reference
- `language_quality_findings`: residual English fragments in zh-CN reports,
  over-claiming tone, removed disclaimer drift
- `valuation_coherence_findings`: committee vs per-share vs event-impact
  vs scorecard direction sanity; also flags treating conservative rNPV as the
  sole fair-value anchor for pre-revenue biotech
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
- `strategic-economics-agent` (Stage B)
- `catalyst-agent` (Stage B)
- `market-expectations-agent` (Stage B)
- `market-regime-timing-agent` (Stage B; absorbs current `macro-context`
  plus the planned k-line role)
- Valuation pod (Stage A):
  - `valuation-commercial-agent`
  - `valuation-pipeline-rnpv-agent`
  - `valuation-balance-sheet-agent`
  - `valuation-committee-agent`
- `decision-debate-agent` (Stage C; bull/bear debate and decision log)
- `report-synthesizer-agent` (Stage C)
- `report-quality-agent` (Stage A; reviews memo language context plus
  decision/synthesizer payloads when available)

Detailed gap analysis, contracts, and migration staging live in
`docs/ARCHITECTURE_AUDIT.md`.
