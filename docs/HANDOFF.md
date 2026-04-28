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

Next action: add `report-synthesizer-agent` with deterministic fallback
preserved.

Recommended scope:

1. Add an LLM agent contract and prompt for `report-synthesizer-agent`.
2. Inputs: deterministic memo scaffold or memo markdown, upstream findings,
   data-collector payload, report-quality payload, scorecard/action-plan, and
   Stage B payloads.
3. Outputs should be limited to executive-verdict prose and section
   transition snippets; numeric tables and structured facts remain
   deterministic.
4. Keep deterministic memo rendering as the fallback and quick-report default
   until calibrated.
5. Tests should use `FakeLLMClient`; no live market or LLM calls.

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

1. `report-synthesizer-agent`.
2. Calibrate opt-in Stage B/C stack on 09606.HK / 09887.HK.
3. TradingAgents-inspired bull/bear debate and decision-log memory, after the
   Stage B agents have stable payloads.

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
