# Architecture Consistency Audit

## Scope

This audit checks whether the current design and implementation align with the
target product vision:

- A multi-LLM-agent collaborative stock research system.
- Specialized agents for valuation, technical timing (K-line), macro context,
  data collection, competition, catalysts, report synthesis, and report quality
  review.
- One-command UX (`company/ticker in -> report out`) remains primary.

Near-term product vertical stays **HK innovative-drug biotech**. Cross-market
and cross-sector expansion is an explicit non-goal for the next sprint so the
agent topology can stabilize on one disclosure style before generalization.

Audit date: 2026-04-24.

## Executive Conclusion

Current system is **partially aligned**:

- **Aligned:** AgentGraph runtime, FactStore collaboration, LLM specialist
  agents for pipeline/financial/competition/macro/skeptic/investment thesis,
  plus valuation-specialist narrative.
- **Partially aligned:** report synthesis and quality review exist, but still
  rely heavily on deterministic rendering and rule-based quality gates.
- **Not aligned yet:** no standalone LLM `kline-agent`, no standalone LLM
  `data-collector-agent`, no standalone LLM `catalyst-agent`, and no dedicated
  LLM `report-quality-agent`. The single `valuation-specialist` agent covers
  the full valuation surface and should be decomposed into a pod.

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
- `macro-agent` (LLM) — currently implemented as `macro-context`.
- `kline-agent` (LLM, long-horizon technical framing).
- `catalyst-agent` (LLM, catalyst ranking + probability/impact narrative).

### Layer 2: Valuation Pod (Multi-Agent)

- `valuation-commercial-agent`
  - Commercialized products / recurring revenue valuation.
- `valuation-pipeline-rnpv-agent`
  - Pipeline asset-level rNPV valuation.
- `valuation-balance-sheet-agent`
  - Net cash/debt/fixed-assets/non-operating adjustments.
- `valuation-committee-agent`
  - SOTP synthesis, weighting, conflict arbitration, final valuation range.

### Layer 3: Decision And Publishing

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
  - `valuation-specialist` (monolithic, to be decomposed)
- Deterministic modules still carrying responsibilities targeted for future
  dedicated LLM agents:
  - Technical timing (`technical-timing` command).
  - Catalyst generation/ranking (`target_price.py`, `pipeline.py`).
  - Data collection quality and source triage (extraction audit module).
  - Final report quality gating and release scoring (rule-based
    `quality_gate`).

## Consistency Scorecard (as of 2026-04-24)

- Runtime orchestration consistency: **High**
- Agent role completeness vs target vision: **Medium**
- Valuation architecture completeness: **Medium** (narrative specialist exists,
  but no valuation pod decomposition yet)
- Report synthesis/editorial separation: **Medium-Low**
- One-command UX consistency: **High**

## Key Gaps (Must Fix First)

1. Missing valuation pod decomposition (commercial/rNPV/balance-sheet/committee).
2. Missing standalone LLM report-quality reviewer.
3. Missing LLM catalyst specialist.
4. Missing LLM kline specialist.
5. Data-collector role not represented as an explicit LLM agent contract.

## Migration Plan

The staging below is the committed plan. Sprint-level execution lives in
`docs/ROADMAP.md` under Sprint 6, Sprint 7, Sprint 8.

### Stage A (Active in Sprint 6) — highest priority

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

### Stage B (Sprint 7)

- Add `catalyst-agent` and replace deterministic-only catalyst narrative
  blocks in final memo sections.
- Add `kline-agent` and integrate with thesis/risk conclusions as a
  secondary timing layer (research-only framing preserved).

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
  - Inputs: outputs of the three above + `macro_context` +
    `pipeline_triage_payload` + `competition_triage_payload`.
  - Output: SOTP aggregation with explicit weights and conflict
    resolution.

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
  vs scorecard direction sanity)
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

Execute Sprint 6 in `docs/ROADMAP.md`:

1. Land the three valuation sub-agent contracts and a thin committee that
   merely concatenates sub-agent outputs.
2. Land `report-quality-agent` with a `review_required`-by-default gate
   until calibration lands.
3. Re-run the canonical one-command smoke on `DualityBio` and at least one
   additional HK ticker (`02142.HK` or `09887.HK`) as acceptance baseline.
