# Architecture Consistency Audit

## Scope

This audit checks whether the current design and implementation align with the
target product vision:

- A multi-LLM-agent collaborative stock research system.
- Specialized agents for valuation, strategic economics, market expectations,
  market regime/timing, data collection, competition, catalysts, report
  synthesis, and report quality review.
- One-command UX (`company/ticker in -> report out`) remains primary.

Near-term product vertical stays **HK innovative-drug biotech**. Cross-market
and cross-sector expansion is an explicit non-goal for the next sprint so the
agent topology can stabilize on one disclosure style before generalization.

Audit date: 2026-04-27.

## Executive Conclusion

Current system is **partially aligned**:

- **Aligned:** AgentGraph runtime, FactStore collaboration, LLM specialist
  agents for pipeline/financial/competition/macro/skeptic/investment thesis,
  plus the first valuation pod and report-quality implementation.
- **Partially aligned:** report synthesis and quality review exist, but still
  rely heavily on deterministic rendering. Stage A+ valuation calibration now
  separates conservative rNPV floor, market-implied value, and repricing
  scenarios. Stage B has started with technical features, an optional
  yfinance history adapter, and an opt-in market-regime/timing scaffold.
- **Not aligned yet:** no `strategic-economics-agent`, no
  `market-expectations-agent`, no standalone LLM `data-collector-agent`, and
  no standalone LLM `catalyst-agent`.

The current architecture is best described as:
**LLM-first hybrid with deterministic backbone**, not yet a fully role-complete
multi-LLM investment committee.

## Target Agent Topology (Canonical)

### Layer 0: Data And Evidence Collection

- `data-collector-agent` (LLM + tools)
  - Source discovery, extraction sanity checks, evidence confidence tagging.
  - Structured output only; no direct memo writing.
- Deterministic providers remain (HKEX/CT.gov/market/macro feeds) and feed the
  same contracts.

### Layer 1: Domain Specialist Agents

- `pipeline-clinical-agent` (LLM) — currently implemented as
  `pipeline-triage` specialist plus deterministic pipeline module.
- `competition-agent` (LLM) — currently implemented as `competition-triage`.
- `catalyst-agent` (LLM, catalyst ranking + probability/impact narrative).
- `strategic-economics-agent` (LLM, value capture through rights, BD,
  commercialization path, partner quality, and platform reuse when evidenced).
- `market-expectations-agent` (LLM, market-implied assumptions and valuation
  band explanation).

### Layer 2: Market Context And Timing

- `market-regime-timing-agent` (LLM, research-only macro, technical, sector
  sentiment, liquidity, and fund-flow framing).

### Layer 3: Valuation Pod (Multi-Agent)

- `valuation-commercial-agent`
  - Commercialized products / recurring revenue valuation.
- `valuation-pipeline-rnpv-agent`
  - Pipeline asset-level rNPV valuation.
- `valuation-balance-sheet-agent`
  - Net cash/debt/fixed-assets/non-operating adjustments.
- `valuation-committee-agent`
  - SOTP synthesis, weighting, conflict arbitration, final valuation range.

### Layer 4: Decision And Publishing

- `investment-thesis-agent` (retain existing) — bull/bear drivers, assumptions,
  falsification watch. Feeds Executive Verdict.
- `scientific-skeptic-agent` (retain existing) — bear case + counter-thesis
  construction. Scoped to attacking the thesis; it is NOT a report quality
  reviewer.
- `report-synthesizer-agent`
  - Produces the final committee-style report from all specialist outputs.
  - Deterministic-first backbone; LLM only writes transitions and the
    executive verdict paragraph.
- `report-quality-agent`
  - Independent editorial/logic/consistency audit over the fully assembled
    report and every upstream finding.
  - Emits publish gate and hard-block reasons.

## Current Implementation Mapping

- Present LLM specialists:
  - `provisional-pipeline`
  - `provisional-financial`
  - `pipeline-triage`
  - `financial-triage`
  - `competition-triage`
  - `macro-context`
  - `scientific-skeptic`
  - `investment-thesis`
  - `valuation-commercial`
  - `valuation-rnpv`
  - `valuation-balance-sheet`
  - `valuation-committee`
  - `report-quality`
  - `valuation-specialist` (compatibility path, no longer default)
- Deterministic modules still carrying responsibilities targeted for future
  dedicated LLM agents:
  - Technical timing (`technical-timing` command).
  - Catalyst generation/ranking (`target_price.py`, `pipeline.py`).
  - Data collection quality and source triage (extraction audit module).
  - Strategic economics and market expectations.

## Consistency Scorecard (as of 2026-04-27)

- Runtime orchestration consistency: **High**
- Agent role completeness vs target vision: **Medium**
- Valuation architecture completeness: **High for Stage A** (pod exists and
  Stage A+ framing separates rNPV floor, market-implied value, and repricing)
- Report synthesis/editorial separation: **Medium**
- One-command UX consistency: **High**

## Key Gaps (Must Fix First)

1. Technical-feature payloads are threaded for opt-in company-report runs, but
   not yet quick-report defaults.
2. Missing strategic-economics and market-expectations layers, so reports
   cannot yet explain sustained biotech valuation bands above conservative
   rNPV.
3. Missing LLM catalyst specialist.
4. Market regime/timing scaffold exists but is not in quick-report defaults
   and still lacks sentiment/fund-flow payloads.
5. Data-collector role not represented as an explicit LLM agent contract.

## Migration Plan

The staging below is the committed plan. Sprint-level execution lives in
`docs/ROADMAP.md` under Sprint 6, Sprint 7, Sprint 8.

### Stage A (Sprint 6) — implemented baseline

- Add valuation pod contracts and wire into AgentGraph:
  - `valuation-commercial-agent`
  - `valuation-pipeline-rnpv-agent`
  - `valuation-balance-sheet-agent`
  - `valuation-committee-agent`
  - Deprecate the monolithic `valuation-specialist` behind a compatibility
    flag, not by immediate removal.
- Add `report-quality-agent`:
  - Independent audit over the fully composed report + every upstream
    finding.
  - Emits `publish_gate` and hard-block reasons.

### Stage A+ (Sprint 6 closeout) — implemented baseline

- Recalibrate the valuation pod so it stops treating conservative rNPV as
  the only fair-value anchor for pre-revenue innovative-drug companies.
- Enforce pod role boundaries:
  - `valuation-commercial-agent` returns no commercial operating value when
    recurring product revenue is absent; it must not fall back to rNPV.
  - `valuation-balance-sheet-agent` only emits deterministic net cash,
    debt, and non-operating adjustments.
  - `valuation-committee-agent` separates conservative rNPV floor,
    market-implied value, and scenario repricing range instead of collapsing
    all of them into a single target price.
- Update `report-quality-agent` to flag misuse of rNPV as the only biotech
  valuation standard, not merely numerical disagreement.

### Stage B data-feature prework (implemented baseline)

- Add a deterministic technical-feature layer before promoting the
  `market-regime-timing-agent` into default report flows.
- Keep the feature layer provider-neutral: it can consume historical OHLCV from
  raw Yahoo endpoints, future licensed feeds, or optional `yfinance`.
- Required initial outputs: 1m/3m/6m/12m returns, volume trend, 52-week
  drawdown, moving-average state, volatility state, and relative strength
  versus HSI when a benchmark series is present.
- Add optional yfinance history adapter behind graceful import and the
  `market` optional dependency extra.
- Do not introduce `TradingAgents` or LangGraph as runtime dependencies in this
  step. Borrow debate, memory, and checkpoint ideas later if the current
  `AgentGraph` becomes insufficient.

### Stage B (Sprint 7)

- Add `strategic-economics-agent`:
  - Explains how scientific assets become shareholder value through retained
    economics, regional rights, BD/licensing, partner quality, development
    cost sharing, commercialization path, and platform reuse only when
    platform evidence exists.
  - This is intentionally broader than a narrow BD extractor and replaces the
    earlier idea of a standalone platform agent.
- Add `catalyst-agent` as an independent event-quality layer:
  - Ranks clinical, regulatory, BD, and conference/data-readout events by
    evidence quality, binary risk, expectation risk, and plausible repricing
    paths.
  - Feeds market expectations, market-regime/timing, and valuation committee;
    it does not produce buy/sell timing by itself.
- Add `market-expectations-agent`:
  - Explains what the current market cap appears to imply and why the stock
    may have held a valuation band above conservative rNPV, including what
    catalyst assumptions appear priced in.
  - Compares market-implied assumptions against evidence instead of declaring
    the market wrong whenever rNPV is lower than price.
- Add `market-regime-timing-agent`:
  - Absorbs current `macro-context`, future k-line framing, sector sentiment,
    liquidity, and fund-flow signals.
  - Outputs research-only timing labels such as `favorable`, `neutral`,
    `fragile`, `avoid_chasing`, and `de_risk_watch`.
  - First opt-in scaffold is implemented; default report integration awaits
    broader calibration and sentiment/fund-flow inputs.

### Stage C (Sprint 8)

- Add `data-collector-agent` as explicit source-evidence triage layer over
  existing deterministic ingestion stack.
- Move final memo body composition from mixed deterministic rendering toward
  `report-synthesizer-agent` with deterministic fallback.

## Valuation Pod Contract (Required)

All valuation sub-agents must emit the same superset fields so the committee
can consume them uniformly:

- `method` (e.g. `"multiple"`, `"rNPV"`, `"balance_sheet_adjustment"`)
- `scope` (what subset of the company this agent priced)
- `assumptions` (list of `{name, value, source, needs_human_review}`)
- `valuation_range` (`{bear, base, bull}` in a declared currency)
- `sensitivity` (list of `{driver, delta, value_impact}`)
- `risks` (list of `AgentFinding.risks`-compatible items)
- `evidence` (list of `AgentFinding.evidence`-compatible items)
- `confidence` (float 0.0–1.0)
- `needs_human_review` (bool)

`valuation-committee-agent` additionally emits:

- `sotp_bridge` (commercial + pipeline + balance-sheet adjustments broken
  out with bridge deltas)
- `method_weights` (float weights per sub-agent, must sum to 1.0)
- `conflict_resolution` (list of `{conflict, resolution, rationale}`
  whenever sub-agents disagree)
- `final_equity_value_range` (committee bear/base/bull)
- `final_per_share_range` (committee bear/base/bull divided by
  committee-chosen share count)
- `currency` (explicit ISO code; conversion method recorded in
  `assumptions`)

### Pod Responsibility Boundaries

- `valuation-commercial-agent`
  - Inputs: `financials_snapshot`, `pipeline_triage_payload` (to identify
    commercialized products), `market_snapshot`, peer comparables when
    present.
  - Output method: `"multiple"` or `"dcf_simple"` depending on revenue
    maturity. Never produces an rNPV for the same asset.
- `valuation-pipeline-rnpv-agent`
  - Inputs: `pipeline_assets`, curated/auto-generated
    `target_price_assumptions`, `pipeline_triage_payload`.
  - Output method: `"rNPV"`. Must cite the PoS / peak sales / launch year
    assumptions it used by field name.
- `valuation-balance-sheet-agent`
  - Inputs: `financials_snapshot` (cash, short-term debt, long-term debt,
    non-operating assets), `valuation_snapshot.shares_outstanding`.
  - Output method: `"balance_sheet_adjustment"`. Must honour existing
    `RMB/CNY -> HKD` conversion path used by `target_price.py`.
- `valuation-committee-agent`
  - Inputs: outputs of the three above + `strategic_economics_payload` +
    `market_expectations_payload` + `market_regime_timing_payload` +
    `pipeline_triage_payload` + `competition_triage_payload`.
  - Output: SOTP aggregation plus explicit separation of conservative
    rNPV floor, market-implied value, and scenario repricing range.

## Strategic Economics Agent Contract (Required for Stage B)

`strategic-economics-agent` answers one question: how does this company
capture economic value from its science?

Inputs:

- `pipeline_assets` and `pipeline_triage_payload`
- Company disclosures and evidence excerpts containing BD, licensing,
  collaboration, NewCo, royalty, milestone, or regional-rights language
- `financials_snapshot` for cash impact and runway implications
- `competition_triage_payload` for partner and commercialization context

Outputs:

- `retained_economics_map`: asset/region/economics-share rows when evidence
  supports them
- `bd_validation_events`: list of collaborations, upfronts, milestones,
  royalties, cost-sharing terms, or partner validation events
- `partner_quality_assessment`: execution capability and strategic fit
- `commercialization_path`: self-commercialization, partner-led,
  region-split, royalty-only, or unclear
- `value_capture_score`: 0-100 score with evidence
- `strategic_premium_discount`: qualitative premium/discount drivers that
  the valuation committee may use, without inventing new market facts
- `needs_human_review`

Boundaries:

- Must not force a platform analysis when the company lacks platform evidence.
- Must not count headline milestone totals as guaranteed value.
- Must identify when BD validates science but caps retained economics.

## Market Expectations Agent Contract (Required for Stage B)

`market-expectations-agent` explains what the stock price appears to imply.
It is not a momentum or trading agent.

Inputs:

- `market_snapshot`, `valuation_snapshot`, historical price/market-cap
  context when available
- `target_price_scenarios`, valuation pod outputs, and scorecard
- `strategic_economics_payload`, catalyst calendar, macro/timing payloads

Outputs:

- `market_implied_assumptions`: what the current market cap seems to require
  for pipeline success, BD, platform repeatability, or catalyst execution
- `valuation_band_context`: whether price sits near historical floor,
  middle band, extended band, or unknown
- `rnpv_gap_explanation`: why conservative rNPV differs from observed price
  and what evidence supports or weakens the gap
- `expectation_risk_flags`: assumptions that could break the valuation band
- `evidence_gaps`
- `confidence`

Boundaries:

- Must not treat current price as proof of fair value.
- Must not call a stock "overvalued" solely because conservative rNPV is
  below price; it must first explain the market-implied premium.

## Market Regime Timing Agent Contract (Required for Stage B)

`market-regime-timing-agent` combines macro, technical, sentiment, and
fund-flow context into a research-only timing view.

Inputs:

- Existing `macro-context` output
- Deterministic technical timing outputs such as trend, support/resistance,
  moving averages, relative strength, and drawdown
- Sector sentiment, liquidity, valuation-band, and fund-flow proxies when
  available

Outputs:

- `timing_view`: `favorable`, `neutral`, `fragile`, `avoid_chasing`, or
  `de_risk_watch`
- `horizon`: `1-3 months`, `3-6 months`, or `6-12 months`
- `macro_regime`, `technical_state`, `sentiment_state`
- `key_triggers`
- `invalidation_signals`
- `confidence`

Boundaries:

- Must remain research-only and must not produce entry/exit orders.
- Must keep long-term fundamental view separate from current timing view.

## Report Quality Agent Contract (Required)

`report-quality-agent` must output:

- `publish_gate` (`pass` / `review_required` / `block`)
- `critical_issues` (list; any `block`-level issue must appear here)
- `consistency_findings` (cross-agent contradictions, currency drift,
  stale-evidence flags)
- `missing_evidence_findings` (claims with no upstream evidence reference)
- `language_quality_findings` (residual English fragments in zh-CN reports,
  over-claiming tone, removed-disclaimer drift)
- `valuation_coherence_findings` (committee vs per-share vs event-impact
  vs scorecard direction sanity; also flags treating conservative rNPV as the
  sole fair-value anchor for pre-revenue biotech)
- `recommended_fixes` (list of concrete edits with target section path)

Quality-agent scope MUST NOT include:

- Inventing new market facts or new valuation numbers.
- Acting as a second scientific-skeptic (skeptic still owns bear case).
- Silent overwrite of any upstream finding. Any override must produce a
  `recommended_fixes` entry, not rewrite the original artifact.

## Non-Negotiable Invariants

- Deterministic report path must remain runnable (`--no-llm`).
- All LLM-generated conclusions remain review-gated by default.
- Source/evidence traceability cannot be weakened.
- Research-only boundary remains explicit (no auto-trading instruction).
- Every new LLM agent must accept a per-agent model override
  (`LLMConfig.per_agent_models`) so costly agents can upgrade without a
  code change.
- Per-agent call budgets must wrap every new agent
  (`BudgetEnforcingLLMClient`).
- `AgentFinding` remains the single contract; no agent invents a parallel
  return type.

## Immediate Next Action

Execute S6.6 in `docs/ROADMAP.md`:

1. Tighten valuation-pod prompts/contracts so commercial, rNPV, and
   balance-sheet agents cannot all emit the same rNPV-derived range.
2. Add committee framing for conservative rNPV floor, market-implied value,
   and scenario repricing range.
3. Re-run the canonical smoke artifacts on `09606.HK`, `02142.HK`, and
   `09887.HK`; only true data-quality failures should remain eligible for
   `publish_gate=block`.
