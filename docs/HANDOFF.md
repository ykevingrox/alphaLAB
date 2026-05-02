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

- Branch: `main`, ahead of `origin/main` by local commits unless pushed.
- Latest completed commits:
  - `6207c61 Calibrate biotech valuation quality checks`
  - `5057d0f Reframe biotech valuation agent architecture`
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
  - Optional `catalyst` LLM scaffold is wired for company-report and consumes
    catalyst calendar plus target-price event-impact payloads.
  - Report-quality now receives `memo_review_payload` plus any
    `report_synthesizer_payload`, allowing it to inspect final report language
    for valuation, BD/platform, catalyst, timing, or trading-advice drift.
    Deterministic postprocessing forces review if trading-instruction wording
    appears or a decision log lacks observable next-review triggers.
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

- Consider a **small optional yfinance provider** only after the next plan is
  explicit.
- Borrow **TradingAgents-style patterns** selectively: structured analyst
  roles, bull/bear debate, model-tier separation, and decision logs.
- Do not add LangGraph, TradingAgents, or new orchestration dependencies yet.

## Next Best Action

Current task: continue Stage C without introducing unnecessary external
dependencies.

Recent checkpoint: opt-in Stage B/C stack calibration on `09606.HK` and
`09887.HK` passed when run with LLM configuration loaded explicitly from
`.env`, including the TradingAgents-inspired `decision-debate` scaffold. The
custom `AgentGraph` remains the orchestration layer.

Recommended scope:

1. Keep calibrating an opt-in company-report path that includes `data-collector`,
   `strategic-economics`, `catalyst`, `market-expectations`,
   `market-regime-timing`, `decision-debate`, `report-synthesizer`, and
   `report-quality` when LLM credentials are available.
2. Inspect whether the latest opt-in outputs still overstate current price, BD
   economics, platform claims, catalyst certainty, timing signals,
   decision-log confidence, or section prose.
3. Keep quick `report` defaults unchanged until Stage B/C decision-support
   outputs are reviewed across both tickers.
4. Tighten prompts/contracts if any agent invents facts or rewrites
   deterministic numbers.
5. No generated runtime files, caches, memos, traces, or raw downloads should
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

1. Review the new artifact-only decision log path
   (`<run_id>_decision_log.json`) and decide later whether a compact memo
   subsection is warranted. Recent same-company logs now feed later
   `decision-debate` runs as lightweight memory. Use
   `PYTHONPATH=src python3 -m biotech_alpha.cli decision-log 09606.HK` to
   inspect local history and latest-vs-previous changes without running a new
   report. Use `decision-log --all` for a portfolio-wide local index.
   Use `PYTHONPATH=src python3 -m biotech_alpha.cli stage-c-review 09606.HK`
   to review saved Stage B/C support artifacts without running LLMs.
2. Broaden calibration beyond 09606.HK / 09887.HK before changing quick
   report defaults.

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
