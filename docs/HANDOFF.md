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
drug companies, where multiple LLM agents (data collection, cleansing,
K-line, financials, technicals, macro, skeptic) collaborate to produce
auditable investment analysis. HK biotech is the first vertical, not the
endgame.

Short-term deliverable remains the same one-command shape:

```text
company name or ticker in -> one-command report out
```

But the report is now produced by a typed AgentGraph with both deterministic
and LLM agents sharing the same contract. The near-term priority is still
HK biotech; future cross-market and cross-sector support should influence
design choices but must not distract from getting the HK biotech MVP stable.

## Planning Discipline

Every handoff must name one concrete next action. Do not leave the next step as
"continue" or as a stale housekeeping item when the working tree is clean.

Use this shape:

- Current task: the narrow objective for the next checkpoint.
- Next action: the single first action the next agent should take.
- Acceptance criteria: how to know the checkpoint is complete.
- Validation: commands or smoke tests required before handoff.
- Queue: short ordered list of follow-on tasks.

## Last Completed

- `company-report --auto-inputs` can resolve HKEX annual-results sources,
  download the source PDF, extract text, generate draft pipeline and financial
  inputs, validate them, and run the report.
- Cursor/Codex follow-up work added a conference-catalyst input layer:
  `conference-template`, `conference-validate`,
  `research --conference-catalysts`, and auto-drafted conference catalysts from
  HKEX annual-results text.
- Report summaries and saved manifests now include a `quality_gate`.
- `watchlist-rank` can filter entries by minimum quality gate.
- Manual curated inputs still override generated inputs.
- Auto-input generation is resilient: one-command reporting should continue
  even if auto input generation fails.
- Suggested rerun commands preserve `--auto-inputs` when the current run used
  automatic input generation.
- Auto-input source metadata can enrich company identity with HKEX stock-name
  aliases, so Chinese company input can still search English registry terms.
- Network-free fixture tests cover the `generate_auto_inputs` orchestration
  path.
- Generated pipeline extraction recognizes more oncology/immunology targets,
  richer phase strings, and filters payload-only mentions such as `P1021`.
- Generated pipeline extraction also avoids partial hyphen-code matches such as
  `C9074` from `BG-C9074`, and combination partner assets such as `BNT116`.
- Repeated asset mentions now enrich missing fields, so later detailed sections
  can fill phase or indication fields from earlier summary mentions.
- HKEX source discovery and PDF download use lightweight retries for transient
  request failures.
- Architecture and data-source docs now record that online ingestion is the
  product path, while offline fixtures are regression guards rather than stale
  fallback research inputs.
- Auto-input tests now include a second representative HK biotech fixture from
  Harbour BioMed (`02142.HK`) official HKEX annual-results text, covering USD
  thousand-unit financials, day-month dates, alias merging, local phase
  extraction, and packed-table noise such as `ADCHBM9033`.
- Live Harbour BioMed smoke reporting remains one-command and source-backed;
  `AZD5863` no longer appears as a standalone generated-asset warning when it
  is only a slash alias of `HBM7022`.
- Harbour BioMed packed-table triage now fills source-backed fields for
  `HBM2001`, `J9003`, `R2006`, `R7027`, and `HBM1020` from the immediate table
  row. Remaining warnings are intentional: missing phases or undisclosed
  targets/mechanisms that the source text does not reliably resolve.
- DualityBio `DB-1312/BG-C9074` indication triage is closed as source-backed:
  the latest HKEX annual-results source (`2026032301402.pdf`) includes packed
  table evidence for `MonoSolid Tumors` alongside `B7-H4DB-1312/BG-C9074`, and
  current extraction already captures `indication = solid tumors` in generated
  pipeline drafts.
- A first-pass market-data connector contract is in place:
  `biotech_alpha.market_data.normalize_hk_market_data` +
  `valuation_snapshot_payload_from_market_data` normalize provider payloads into
  valuation-snapshot-compatible dicts. `generate_auto_inputs` and
  `run_company_report` accept an optional `market_data_provider`; when supplied,
  a source-backed `<slug>_valuation.json` draft is written and registered in
  the source manifest and validation report. Without a provider, behavior is
  unchanged (no valuation draft, manual-template guidance still surfaces).
- Provider failures, `None`/non-dict responses, and missing fields degrade into
  warnings rather than breaking the one-command flow.
- CLI opt-in flag `company-report --market-data hk-public` wires a composite
  `biotech_alpha.market_data_providers.hk_public_quote_provider` into the
  auto-draft path. The composite provider queries Tencent's public
  `qt.gtimg.cn` feed first (which exposes share price, shares outstanding,
  total market cap, and currency without authentication) and falls back to
  Yahoo Finance when Tencent is unreachable. Default remains `none`.
- The earlier Yahoo-only wiring is preserved as a secondary fallback; the
  Yahoo v7 quote endpoint currently requires crumb auth and would otherwise
  degrade silently, but it remains usable where that auth is available.
- Missing-input copy for `valuation` now mentions the opt-in flag instead of
  claiming no connector exists.
- Live `company-report --auto-inputs --market-data hk-public` runs for both
  DualityBio (`09606.HK`) and Harbour BioMed (`02142.HK`) write
  `data/input/generated/<slug>_valuation.json` drafts sourced from the
  Tencent feed. `validate_valuation_snapshot_file` returns `has_snapshot=True`
  with no placeholder warnings (only the expected `revenue_ttm unavailable;
  revenue multiple not calculated` soft warning) and computes a real market
  cap and enterprise value from the live share price and shares outstanding.
- Tencent HK quote payloads now carry a structured `warnings` list covering
  staleness (quote older than a configurable freshness window, default 3
  days), halted/suspended rows (market cap and shares outstanding both zero),
  currency mismatches vs the expected HKD for HK identities, and sanity-check
  disagreement between reported market cap and share_price * shares
  outstanding. These warnings propagate through `normalize_hk_market_data`,
  `draft_valuation_snapshot`, and `AutoInputArtifacts.warnings` so the
  one-command report can surface them alongside other auto-input warnings.
- `draft_valuation_snapshot` now reports a ``writeable`` flag; halted or
  incomplete quotes keep bubbling their warnings but no longer write an
  unvalidatable `<slug>_valuation.json` draft.
- Multi-LLM-agent runtime skeleton (M1) is live:
  - `src/biotech_alpha/llm/` exposes `LLMConfig` (env-driven,
    `BIOTECH_ALPHA_LLM_API_KEY` with `DASHSCOPE_API_KEY` fallback,
    default model `qwen3.6-plus`, opt-in `enable_thinking`),
    `OpenAICompatibleLLMClient` (targets Bailian's
    `/compatible-mode/v1`; auto-sends `extra_body.enable_thinking` only on
    Bailian so OpenAI itself stays compatible), `FakeLLMClient`,
    `LLMTraceRecorder` (JSONL under `data/traces/`, gitignored),
    `StructuredPrompt` + lightweight JSON-schema validator.
  - `src/biotech_alpha/agent_runtime.py` implements `FactStore`, `Agent`,
    `DeterministicAgent`, and `AgentGraph` with topological layering,
    same-layer thread-pool parallelism, error isolation (failed agents
    skip descendants, siblings keep running), and cycle detection.
  - `src/biotech_alpha/agents_llm.py` ships the first real LLM agent:
    `ScientificSkepticLLMAgent`. Prompt forces a strict top-level JSON
    shape (summary / bull_case / bear_case / risks[] / needs_more_evidence
    / confidence) with per-risk severity enum and optional related_asset.
  - `company-report --llm-agents scientific-skeptic` opt-in CLI flag runs
    the agent after deterministic research, writes
    `data/memos/<run_id>_llm_findings.json` and a `data/traces/*.jsonl`
    trace, and surfaces a token/cost summary in the CLI JSON output.
    Omitting the flag preserves prior zero-network-LLM behaviour.
  - `pyproject.toml` now depends on `openai>=1.40`. `.gitignore` covers
    `.env`, `.env.*`, and `data/traces/`. `.env.example` documents every
    env knob (never holds a real key).
  - 149 tests pass (3 skipped: Yahoo / Tencent / Bailian online). New
    coverage: 20 LLM adapter tests, 8 agent-runtime tests, 5 scientific
    skeptic tests (including a schema-drift test and an in-graph test).
- Live Bailian Qwen smoke validated end-to-end on 2026-04-22:
  - Minimal ping (`scripts/llm_smoke.py`): 28 completion tokens, 3.0 s
    latency, strict JSON schema satisfied.
  - Full `company-report --ticker 09606.HK --auto-inputs --market-data
    hk-public --llm-agents scientific-skeptic` run: 1615+734=2349 tokens,
    15.5 s latency, 1 finding with 8 specific DualityBio bear-case risks
    including a correct callout that late-stage assets DB-1311 / DB-1310
    have no 12-24 month binary catalysts, and correct flagging of the
    known `DB-1312 milestone "in 2017"` pipeline extraction anomaly.
  - The run also exposed that `discover_company_inputs` can cross-match
    pipeline files across HK tickers when multiple are cached under
    `data/input/generated/`, so the smoke was temporarily validated by
    moving `02142_hk_*.json` aside. Files were restored immediately
    afterwards; see Queue for the fix task.

## Current Repo State

- Branch: `main`
- Remote: `origin https://github.com/ykevingrox/alphaLAB.git`
- Check `git log --oneline -1` for the latest committed baseline.
- Expected steady state after a handoff checkpoint is a clean working tree
  except for ignored generated runtime outputs.
- Generated runtime outputs are intentionally ignored by git:
  `data/raw/`, `data/input/generated/`, `data/processed/`, and `data/memos/`.

## Latest Validation

Last validated on 2026-04-22 after M1 LLM + Agent runtime rollout:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall -q src tests
git diff --check
awk 'length($0) > 88 { print FILENAME ":" FNR ":" length($0) }' \
  $(git ls-files '*.py' '*.md' '*.toml')
```

Latest result:

- 149 unit tests ran, 146 passed, 3 skipped (online Yahoo / online Tencent /
  online Bailian Qwen integration tests self-skip without the matching
  `BIOTECH_ALPHA_ONLINE_*_TESTS=1` env flag).
- Compile check passed on both `src` and `tests`.
- `git diff --check` passed.
- 88-character scan passed across `git ls-files '*.py' '*.md' '*.toml'` plus
  the new untracked `src/biotech_alpha/{llm,agent_runtime,agents_llm}*`,
  `tests/test_{llm_client,agent_runtime,scientific_skeptic_agent}.py`, and
  `.env.example`.
- Deterministic `company-report --auto-inputs --market-data hk-public`
  smoke still produces `research_ready_with_review` reports for
  DualityBio (`09606.HK`) and Harbour BioMed (`02142.HK`) with Tencent
  market data and empty `AutoInputArtifacts.warnings` during market hours
  (same behaviour as the prior validation).
- LLM ping `scripts/llm_smoke.py` (Bailian `/compatible-mode/v1`,
  `qwen3.6-plus`, `enable_thinking=False`): 1 call, 28 completion tokens,
  3.0 s latency, schema satisfied, trace recorded.
- LLM end-to-end `company-report --ticker 09606.HK --auto-inputs
  --market-data hk-public --llm-agents scientific-skeptic`: 1 LLM call,
  1615 prompt + 734 completion tokens, 15.5 s latency, `AgentRunResult`
  returned 1 `AgentFinding` with 8 DualityBio-specific bear-case risks
  and `confidence=0.75`. Strict JSON schema passed after the prompt was
  tightened to forbid wrapper keys like `counter_thesis` and to mandate
  top-level `summary` / `bear_case` / `risks`.

Latest smoke commands:

```bash
# Deterministic + market data (unchanged from prior validation)
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs --overwrite-auto-inputs \
  --market-data hk-public

# LLM + agent runtime opt-in (new)
set -a; source .env; set +a
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs \
  --market-data hk-public \
  --llm-agents scientific-skeptic

# One-shot LLM ping for provider/model smoke
PYTHONPATH=src .venv/bin/python scripts/llm_smoke.py
```

Latest smoke result:

- Deterministic layer unchanged from the prior handoff: valuation market cap
  and EV populated from `qt.gtimg.cn`; quality gate
  `research_ready_with_review`.
- LLM agent pipeline writes `data/memos/<run_id>_llm_findings.json` and
  `data/traces/<run_id>.jsonl`. The trace JSONL captures timestamp, agent,
  model, prompt_hash, token counts, latency, retries, and `ok`/`error`.
- Sample DualityBio LLM risks include:
  - `[high][DB-1312] past milestone date (2017) on a Phase 1 asset`
  - `[high][DB-1311, DB-1310] no 12-24 month binary catalysts, milestones
    only in 2026`
  - `[bear] Heavy dependence on partner BioNTech for lead assets`
- Qwen3's default implicit thinking is actively suppressed via
  `extra_body.enable_thinking=False` when the base URL matches Bailian;
  without this, the same ping burned 385 completion tokens at 10 s instead
  of 28 tokens at 3 s. `BIOTECH_ALPHA_LLM_ENABLE_THINKING=1` re-enables it.
- Known gap uncovered by the smoke: `discover_company_inputs` mis-matched
  `02142_hk_pipeline_assets.json` when querying `09606.HK`. The LLM smoke
  was validated by temporarily relocating the 02142 drafts; they were
  restored after verification. See Queue item #1 for the fix task.

## Execution Plan

### Current Task

Ship the **second** LLM agent in the AgentGraph — a `PipelineTriageAgent`
that consumes the deterministic pipeline + source-text window and produces a
per-asset structured triage (phase plausibility, milestone plausibility,
target/indication alignment with the source text, and a `confidence` per
asset) — and fix the `discover_company_inputs` cross-ticker mis-match that
today lets a stale `02142_hk_*.json` draft leak into a `09606.HK` run.

The skeptic agent is now the canary for all LLM agents; the next agent must
share the same contract so `AgentGraph` scheduling, tracing, cost summary,
and `AgentFinding` surfacing stay uniform.

### Next Action

1. Fix `discover_company_inputs` first. Reproduce with:

   ```bash
   PYTHONPATH=src .venv/bin/python -c \
     "from biotech_alpha.company_report import \
     discover_company_inputs, CompanyIdentity; \
     print(discover_company_inputs(CompanyIdentity(\
     company='DualityBio', ticker='09606.HK', market='HK'), \
     input_dir='data/input/generated').pipeline_assets)"
   ```

   Today this returns `data/input/generated/02142_hk_pipeline_assets.json`.
   Expected: only accept filenames whose slug (stem up to the first
   input-kind suffix like `_pipeline_assets`, `_financials`, `_valuation`,
   `_conference_catalysts`) matches `CompanyIdentity` slug tokens, not any
   filename that shares loose tokens with the company name. Add a
   regression test using two cached slugs under the same
   `generated_input_dir`.

2. Then add `PipelineTriageAgent` in `src/biotech_alpha/agents_llm.py`:
   - Declares `depends_on=('research_facts',)` and
     `produces='pipeline_triage'`.
   - Consumes the deterministic `pipeline_snapshot` (already in the
     `FactStore`) plus a new `source_text_excerpt` fact extracted from the
     latest HKEX annual-results text (cap at ~4k chars around the pipeline
     table).
   - Emits an `AgentFinding` per asset via `AgentFinding.details.assets`,
     with `severity` ∈ {"low","medium","high"} for each anomaly, and a
     top-level `coverage_confidence` 0-1.
   - Strict JSON schema enforced via `StructuredPrompt`.

3. Register it under `--llm-agents pipeline-triage` (composable, so
   `--llm-agents scientific-skeptic pipeline-triage` runs both in the
   AgentGraph; the skeptic can `depends_on=('pipeline_triage',)` so it sees
   triage findings through the `FactStore`).

4. Add `BIOTECH_ALPHA_LLM_DEBUG_PROMPT=1` env flag while you are here: when
   set, `_run_llm_agent_pipeline` writes the rendered system+user prompt to
   `data/traces/<run_id>_<agent>_prompt.txt` so prompt-drift issues are
   debuggable without re-guessing.

### Acceptance Criteria

- `discover_company_inputs` no longer cross-matches tickers; regression
  test exercises the `02142` vs `09606` scenario.
- `--llm-agents pipeline-triage` produces at least one `AgentFinding` with
  per-asset entries for DualityBio and Harbour BioMed smoke runs, and the
  run writes its `AgentFinding` JSON under `data/memos/`.
- Running both agents together still respects DAG ordering: triage runs
  first, skeptic consumes its findings, and the cost summary lists 2 calls.
- Strict JSON schema passes on the first try for both agents on Qwen3.6;
  if it fails, the error is captured in `AgentStepResult.error` without
  crashing the deterministic report.
- `BIOTECH_ALPHA_LLM_DEBUG_PROMPT=1` writes prompt files under
  `data/traces/`; unsetting it writes nothing.

### Validation

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall -q src tests
git diff --check
awk 'length($0) > 88 { print FILENAME ":" FNR ":" length($0) }' \
  $(git ls-files '*.py' '*.md' '*.toml')

# Live LLM smoke (requires .env with BIOTECH_ALPHA_LLM_API_KEY)
set -a; source .env; set +a
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs --market-data hk-public \
  --llm-agents pipeline-triage scientific-skeptic
```

### Queue

1. Fix `discover_company_inputs` cross-ticker mis-match (blocker; today
   requires manually relocating other tickers' drafts to get a clean LLM
   input for any one ticker).
2. Add `PipelineTriageAgent` + register under `--llm-agents pipeline-triage`.
3. Add `BIOTECH_ALPHA_LLM_DEBUG_PROMPT` env flag for prompt-drift debugging.
4. Expose `--market-data-freshness-days` on `company-report` so operators
   can tune Tencent staleness without patching code.
5. Add auto competitor drafts once pipeline extraction is reliable.
6. Keep broadening fixtures across representative HK biotech disclosure
   styles.
7. Tighten validator checks for stale placeholders and weak evidence
   metadata.
8. Add a US-market sibling market-data provider once HK freshness lands, so
   the auto-draft path is not HK-only.
9. After two LLM agents are stable, introduce a `FinancialTriageAgent`
   (burn-rate sanity + runway cross-check) and a `MacroContextAgent` so the
   multi-agent story has deterministic + LLM representation in each domain.

## Do Not Break

- `company-report` must accept either `--company` or `--ticker`.
- Manual input files in `data/input/` must override generated drafts in
  `data/input/generated/`.
- Generated input files are drafts and should remain human-review flagged.
- The one-command report should not fail just because auto-input generation
  fails.
- Saved reports should remain auditable through source links, manifests, and
  validation warnings.
- Do not replace online source collection with fixture data in live reports;
  fixtures are for regression tests.
- Do not commit generated PDFs, processed report outputs, memos, virtualenvs,
  cache files, `.env`, or `data/traces/`.
- Default behaviour of `company-report` must stay LLM-free; LLM agents only
  run when `--llm-agents <name>` is passed. A failure in any LLM agent must
  not fail the deterministic report — it must surface as an
  `AgentStepResult` with `ok=false`.
- `OpenAICompatibleLLMClient` must never read API keys from CLI arguments or
  log them; keys come from env (`BIOTECH_ALPHA_LLM_API_KEY` preferred,
  `DASHSCOPE_API_KEY` fallback) loaded from `.env` (gitignored).
- Qwen3 Bailian calls must explicitly pass `extra_body.enable_thinking`
  (True or False) controlled by `LLMConfig.enable_thinking`; do not omit
  the field or Qwen3 silently consumes extra completion tokens on thinking.
- `AgentFinding` remains the single contract every agent (deterministic or
  LLM) must emit; new agents must not invent parallel return types.
