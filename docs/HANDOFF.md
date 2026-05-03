# Handoff

This file is the compact working-memory handoff for Codex, Cursor, or any other
agent editing this repository. Keep it current and short.

## Fixed Switch Prompt

Copy this when switching between tools:

```text
先读 docs/HANDOFF.md，然后检查 git status 和最近 diff。
不要重做已经完成的事，评估当前状态后继续 Next Best Action。
```

## Current Goal

Build an AI-assisted research system for long-term investing in innovative
drug companies. HK biotech remains the first vertical. The primary workflow is:

```text
company name or ticker in -> one-command source-backed report out
```

The runtime is a typed AgentGraph with deterministic modules and opt-in LLM
agents sharing `AgentFinding` / FactStore contracts. Current architecture is
LLM-first hybrid with deterministic backbone, not yet a fully role-complete
investment committee.

## Current Repository State

- Branch: `main`, tracking `origin/main`.
- Latest completed commits on `main`:
  - `5d197e4 Harden valuation LLM output compatibility`
  - `50d18f4 Merge decision log memory development`
  - `e1d477b Avoid negated rNPV sole-value review false positives`
  - `32ab47d Clean up Stage C review docs drift`
- Stage A is functionally closed for the next checkpoint:
  - Valuation pod is decomposed into commercial, rNPV, balance-sheet, and
    committee agents.
  - Report-quality agent is wired as the publish gate.
  - Biotech valuation calibration now separates conservative rNPV floor,
    market-implied value, and scenario repricing range.
  - A market-expectation gap alone should produce `review_required`, not a
    mechanical `block`.
- Stage B/C scaffold status:
  - `biotech_alpha.technical_features` computes provider-neutral technical
    payloads from OHLCV rows.
  - `technical-timing` CLI can attach symbol/provider metadata and optional
    benchmark OHLCV for relative strength.
  - `biotech_alpha.yfinance_provider` is an optional historical-data adapter
    behind graceful import and the `market` optional dependency extra.
  - Optional `market-regime-timing` LLM scaffold is wired for company-report.
  - Optional `market-expectations` LLM scaffold is wired for company-report.
  - Optional `strategic-economics` LLM scaffold is wired for company-report
    and feeds market expectations / valuation committee when requested.
    `company-report` can now discover optional
    `*_strategic_economics.json` inputs with source-backed BD, retained-rights,
    partner, milestone/royalty, and platform-evidence rows; these are threaded
    to the strategic-economics prompt ahead of inference from partner names.
  - Optional `catalyst` LLM scaffold is wired for company-report and consumes
    catalyst calendar plus target-price event-impact payloads.
  - Report-quality now receives `memo_review_payload` plus any
    `report_synthesizer_payload`, allowing it to inspect final report language
    for valuation, BD/platform, catalyst, timing, or trading-advice drift.
    Deterministic postprocessing forces review if trading-instruction wording
    appears or a decision log lacks observable next-review triggers.
  - Valuation sub-agent postprocessing records `role_boundary_flags` when
    commercial or balance-sheet agents are corrected away from rNPV leakage.
  - Valuation LLM output parsing uses a width-at-the-boundary posture for
    optional arrays: model `null` values for role-boundary / SOTP bridge
    fields are accepted and normalized to empty arrays before entering the
    FactStore.
  - `stage-c-review` reviews saved `report_quality`, `valuation_pod`,
    `decision_log`, and `_llm_findings` artifacts offline, with
    flag/severity filters, latest-per-identity mode, sorting, Markdown
    checklist output, and optional file output.
  - Optional `data-collector` LLM scaffold is wired for company-report and
    feeds per-domain evidence verdicts into report quality when requested.
  - `company-report --technical-features yfinance` now threads source-backed
    technical payloads into LLM facts when `market-regime-timing` or
    `market-expectations` is requested.
- Working tree should be clean before new development. Check with:

```bash
git status --short --branch
```

## External Repository Assessment

Two GitHub projects were reviewed as possible inspiration:

- `ranaroussi/yfinance`: useful as an optional market-data adapter for
  historical price, volume, market-cap, analyst, and sector data. It must not
  become a hard runtime dependency because it is an unofficial Yahoo Finance
  wrapper and should degrade gracefully under provider failure or terms/format
  drift.
- `TauricResearch/TradingAgents`: useful as architecture inspiration for
  analyst teams, bull/bear debate, risk review, memory, and checkpointing. Do
  not import or adopt it wholesale for the next sprint; the current custom
  `AgentGraph` is smaller, auditable, and already aligned with this project.

Decision for now:

- Keep `biotech_alpha.yfinance_provider` as an optional adapter behind the
  `market` extra and provider-neutral technical features. It must remain
  graceful on missing dependency, provider failure, or Yahoo format drift.
- Borrow **TradingAgents-style patterns** selectively: structured analyst
  roles, bull/bear debate, model-tier separation, and decision logs.
- Do not add LangGraph, TradingAgents, or new orchestration dependencies yet.

## Next Best Action

Current task: continue Stage C development while keeping `stage-c-review` as a
calibration instrument, not a blocker for weak-model prose quality.

Recent checkpoint: a 2026-05-03 isolated opt-in sweep loaded LLM configuration
explicitly from `.env` and wrote artifacts under `/tmp` only. `09606.HK`,
`09887.HK`, and `02142.HK` each completed the full Stage B/C stack with 17/17
LLM calls successful, including `data-collector`, `strategic-economics`,
`catalyst`, `market-regime-timing`, `market-expectations`, `decision-debate`,
`report-synthesizer`, and `report-quality`. Each ticker reviewed as
`review_required` / Stage C severity `review`, with no missing Stage B/C
agents, schema failures, duplicate valuation ranges, or committed runtime
artifacts.

Interpretation: current review flags are mostly data-quality and manual-review
gates, not architecture failures. Older saved local artifacts from 2026-04-24
still show `critical` because they predate the Stage B/C agents and decision
logs; do not treat those old artifacts as the current code baseline.

Recommended scope:

1. Continue high-leverage development after the curated strategic-economics
   input layer: improve catalyst evidence quality, source-backed
   market-expectations inputs, and decision-log memory.
2. Keep hardening model-invariant contracts when calibration exposes them:
   schema compatibility, numeric口径, artifact completeness, fact invention,
   duplicate valuation ranges, or rNPV leakage.
3. Do not overfit prompts to weak-model prose. Treat style / confidence /
   generic wording review flags as useful signals, but not primary blockers
   while the current LLM is intentionally weaker than the target model.
4. Keep quick `report` defaults unchanged until Stage B/C decision-support
   outputs are reviewed across more tickers and with a stronger model.
5. Tighten prompts/contracts if any agent invents facts or rewrites
   deterministic numbers.
6. No generated runtime files, caches, memos, traces, or raw downloads should
   be committed.

Acceptance criteria:

- `--no-llm` quick report still works.
- Existing technical feature and yfinance adapter outputs remain optional,
  deterministic, source-tagged, and warning-friendly.
- No generated runtime files, caches, memos, traces, or raw downloads are
  committed.
- Docs name how the feature feeds Stage B agents.

## Validation

Run before handoff or commit:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall -q src tests
git diff --check

# Deterministic-only smoke
.venv/bin/python -m biotech_alpha.cli report "09606.HK" --no-llm --no-save
```

Optional LLM smoke when `.env` has credentials:

```bash
.venv/bin/python -m biotech_alpha.cli report "09887.HK" --json --no-save
```

## Ordered Queue

1. Use `strategic-economics-template` / `strategic-economics-validate` to
   curate BD economics and retained-rights inputs for the three calibration
   tickers, then inspect how `strategic-economics`, `market-expectations`, and
   `valuation-committee` use them.
2. Improve catalyst timelines and source-backed market-expectations inputs.
3. Review whether the artifact-only decision log should gain a compact memo
   subsection once the decision memory shape stabilizes. Recent same-company
   logs already feed later `decision-debate` runs as lightweight memory.
4. Broaden calibration beyond `09606.HK`, `09887.HK`, and `02142.HK` before
   changing quick `report` defaults.
5. Use `decision-log --all` and `stage-c-review --latest-per-identity --sort
   severity --markdown` for local inspection, but remember that committed
   source should stay free of generated runtime artifacts.

## Do Not Break

- `company-report` must accept either `--company` or `--ticker`.
- Manual inputs in `data/input/` override generated drafts in
  `data/input/generated/`.
- Generated inputs remain human-review flagged.
- Live reports must not use offline fixtures as stale research inputs.
- Provider, LLM, and extraction failures must degrade into warnings or
  `AgentStepResult` errors, not crash the deterministic report.
- LLM agents remain opt-in for `company-report`; quick `report` may auto-enable
  LLM and auto-degrade when env is missing.
- Do not commit generated PDFs, processed reports, memos, caches, traces,
  virtualenvs, `.env`, or local credentials.
- `OpenAICompatibleLLMClient` must never read API keys from CLI args or log
  them.
- New agents should emit `AgentFinding` and structured payloads through the
  existing FactStore rather than inventing parallel contracts.
