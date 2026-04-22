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
- `discover_company_inputs` cross-ticker leak is fixed: `_select_input_file`
  now requires all numeric `ticker_tokens` (derived from
  `CompanyIdentity.ticker`) to appear in the filename stem, so
  `09606.HK` no longer pulls `02142_hk_*.json` drafts. Regression test
  covers the 02142 vs 09606 scenario.
- `BIOTECH_ALPHA_LLM_DEBUG_PROMPT=1` env flag writes rendered system+user
  prompts to `data/traces/<run_id>_<agent>_prompt.txt` so prompt-drift is
  debuggable without re-guessing.
- Second LLM agent `PipelineTriageLLMAgent` is live (M2):
  - New fact `source_text_excerpt`: a ~4k-char window of the latest HKEX
    source document anchored on the first pipeline-asset name mention
    (falls back to the first 4k chars when no anchor is found). Built by
    `_build_source_text_excerpt` in `company_report.py` and included in
    `build_llm_agent_facts` output.
  - `PIPELINE_TRIAGE_PROMPT` / `PipelineTriageLLMAgent` triage each asset
    for phase / milestone / target-indication plausibility vs the source
    text, emitting a strict per-asset JSON (`name`, `severity`,
    `issues[]`, optional `suggested_fixes[]` / `confidence`) plus
    top-level `coverage_confidence` and `global_warnings`.
  - `AgentGraph` wiring: `--llm-agents pipeline-triage scientific-skeptic`
    runs triage first; the skeptic `depends_on` triage in combined mode
    so its `FactStore` view already includes `pipeline_triage_payload`
    and its prompt now renders the triage payload in a dedicated block.
    Running only `--llm-agents scientific-skeptic` keeps the skeptic
    independent of triage.
  - CLI `--llm-agents` choices updated to
    `('scientific-skeptic', 'pipeline-triage')`; help text documents the
    DAG ordering.
  - New tests `tests/test_pipeline_triage_agent.py` cover happy-path
    finding construction, empty-pipeline skip, schema-drift error
    capture, in-graph chain with the skeptic, and the skeptic-is-skipped
    propagation when triage fails. Also a self-skipping
    `PipelineTriageOnlineTest`.
- Live Bailian Qwen dual-agent smoke validated on 2026-04-22:
  - `company-report --ticker 09606.HK --auto-inputs --market-data hk-public
    --llm-agents pipeline-triage scientific-skeptic`: 2 LLM calls, 2 OK,
    5549 prompt + 1749 completion tokens = 7298 total, 35.3 s combined
    latency.
  - Triage finding (confidence 0.6) flagged `DB-1312`'s `"in 2017"`
    milestone as high-severity and surfaced 8 medium-severity assets
    whose source coverage was lost to the excerpt window.
  - Skeptic finding (confidence 0.3) consumed those triage findings and
    produced a sharper bear case ("validation confidence critically low
    for 8 assets", "data quality failures indicate poor corporate
    governance or outdated reporting"), demonstrating real multi-agent
    collaboration.

## Current Repo State

- Branch: `main`
- Remote: `origin https://github.com/ykevingrox/alphaLAB.git`
- Check `git log --oneline -1` for the latest committed baseline.
- Expected steady state after a handoff checkpoint is a clean working tree
  except for ignored generated runtime outputs.
- Generated runtime outputs are intentionally ignored by git:
  `data/raw/`, `data/input/generated/`, `data/processed/`, and `data/memos/`.

## Latest Validation

Last validated on 2026-04-22 after M2 dual-agent rollout (pipeline triage
+ scientific skeptic running together in the AgentGraph):

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall -q src tests
git diff --check
awk 'length($0) > 88 { print FILENAME ":" FNR ":" length($0) }' \
  $(git ls-files '*.py' '*.md' '*.toml')
```

Latest result:

- 157 unit tests ran, 153 passed, 4 skipped (online Yahoo / online Tencent /
  online Bailian Qwen integration tests self-skip without the matching
  `BIOTECH_ALPHA_ONLINE_*_TESTS=1` env flag).
- Compile check passed on both `src` and `tests`.
- `git diff --check` passed.
- 88-character scan passed across `git ls-files '*.py' '*.md' '*.toml'`
  plus `tests/test_pipeline_triage_agent.py` (new).
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

# LLM + agent runtime opt-in (dual agent)
set -a; source .env; set +a
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs \
  --market-data hk-public \
  --llm-agents pipeline-triage scientific-skeptic

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
- Dual-agent DualityBio smoke (`pipeline-triage` + `scientific-skeptic`):
  - 2 LLM calls, 2 OK, 5549 prompt + 1749 completion tokens (7298 total),
    35.3 s combined latency.
  - Triage finding (confidence 0.6): 3 data-quality issues high-severity,
    8 medium-severity missing-source-coverage flags, including the
    correct `DB-1312 next_milestone "in 2017"` callout.
  - Skeptic finding (confidence 0.3) consumed those triage findings and
    produced a sharper bear case: "validation confidence critically low
    for 8 assets", "absence of TTM revenue prevents valuation
    benchmarking", "heavy concentration in solid tumor ADCs/bispecifics
    exposes the company to crowded competitive landscapes".
- Qwen3's default implicit thinking remains actively suppressed via
  `extra_body.enable_thinking=False` on Bailian; that continues to keep
  completion token usage low.

## Execution Plan

### Current Task

Broaden the multi-agent graph in two directions and tighten what we have:

- Lift the `source_text_excerpt` window strategy so triage can cover all
  pipeline assets (today the 4k-char anchor is pinned to the first asset,
  which leaves later-listed assets with only `medium` "not in excerpt"
  warnings).
- Introduce a `FinancialTriageLLMAgent` that cross-checks burn rate,
  runway months, and cash-vs-debt sanity. This is the third agent and the
  first non-pipeline domain, so it's the real test that `AgentGraph` is
  domain-agnostic.

Both tasks build on the stable M1/M2 foundation (runtime + pipeline
triage + skeptic) and must not regress the current dual-agent smoke.

### Next Action

1. Rework `_build_source_text_excerpt` in `company_report.py` to support
   multiple anchors: when there are N assets, try to produce one excerpt
   window per asset name (or one combined deduped concatenation capped at
   ~8k chars total), so the triage agent doesn't need to flag "not in
   excerpt" for assets that do appear in the source. Add a unit test that
   exercises a fixture with two assets far apart in the text.

2. Add `FinancialTriageLLMAgent` in `src/biotech_alpha/agents_llm.py`:
   - Inputs: `valuation_snapshot`, `trial_summary`, `input_warnings`,
     plus a new `financials_snapshot` fact (burn-rate estimate, last
     cash, last debt, revenue TTM, the deterministic cash-runway
     estimate, and any auto-input warnings relevant to financials).
   - Output: strict JSON with `summary`,
     `runway_sanity ∈ {"consistent","stretch","inconsistent"}`, per-line
     anomalies, and `confidence`.
   - Register under `--llm-agents financial-triage`, composable with the
     other two agents. Skeptic should optionally `depends_on` it too so
     it sees financial anomalies.

3. After financial triage is live, expose
   `--market-data-freshness-days` on `company-report` so operators can
   tune Tencent staleness without patching code.

### Acceptance Criteria

- `source_text_excerpt` contains all pipeline assets that actually appear
  in the source text (verified by a unit test with two distant anchors).
  The live DualityBio smoke should drop at least two of the existing
  "not in excerpt" mediums.
- `--llm-agents financial-triage` produces an `AgentFinding` with at
  least one concrete numeric anomaly on the DualityBio smoke.
- Running `--llm-agents pipeline-triage financial-triage
  scientific-skeptic` together keeps strict JSON schema passing on the
  first try, shows 3 calls in the cost summary, and preserves DAG order
  (triage agents first, skeptic last).
- Deterministic report path is unchanged without `--llm-agents`.

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
  --llm-agents pipeline-triage financial-triage scientific-skeptic
```

### Queue

1. Multi-anchor `source_text_excerpt` so triage coverage is not
   first-asset-only.
2. Add `FinancialTriageLLMAgent` (burn rate / runway / cash-debt sanity).
3. Expose `--market-data-freshness-days` on `company-report` so operators
   can tune Tencent staleness without patching code.
4. Per-agent LLM call budget cap in `LLMConfig` so no single agent can
   blow the daily token budget on its own.
5. Claude adapter alongside the OpenAI-compatible adapter so the runtime
   is not single-vendor.
6. Add auto competitor drafts once pipeline extraction is reliable.
7. Keep broadening fixtures across representative HK biotech disclosure
   styles.
8. Tighten validator checks for stale placeholders and weak evidence
   metadata.
9. Add a US-market sibling market-data provider once HK freshness lands,
   so the auto-draft path is not HK-only.
10. `MacroContextAgent` once financial triage stabilises, so macro drivers
    (rate environment, HK biotech sentiment, policy) enter the graph.

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
