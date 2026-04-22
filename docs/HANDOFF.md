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
- Multi-anchor `source_text_excerpt` (M2.5) closed the "not in excerpt"
  false-positive gap:
  - `_build_source_text_excerpt` now walks every asset name, centres a
    small window on each hit, merges overlaps, caps total at 8k chars,
    and exposes `anchor_assets` / `missing_assets` / `truncated` flags.
  - Triage prompt tells the LLM not to penalise assets listed in
    `missing_assets` (extractor coverage limit, not a data bug).
  - Re-run on 09606.HK: triage confidence 0.6 -> 0.95, false-positive
    "not in excerpt" mediums 8 -> 0, skeptic confidence 0.3 -> 0.85.
    Triage additionally surfaced real cross-cutting issues: `BNT` vs
    `BioNTech` partner-naming inconsistency across multiple assets and
    a DB-1303 "Phase 3 but no next_milestone" flag that was invisible
    under the single-anchor window.
- Third LLM agent `FinancialTriageLLMAgent` is live (M3):
  - New fact `financials_snapshot`: one consolidated dict carrying
    `financial_snapshot`, `runway_estimate`, `market_snapshot`,
    `valuation_metrics`, and `financial_warnings`. Built in
    `_build_financials_snapshot` and threaded through
    `build_llm_agent_facts`.
  - `FINANCIAL_TRIAGE_PROMPT` / `FinancialTriageLLMAgent` output strict
    JSON: `runway_sanity` (enum:
    consistent/stretch/inconsistent/insufficient_data), `summary`,
    `findings[]` (each with `severity` low/medium/high, `description`,
    optional `metric` / `suggested_action`), plus optional
    `implied_runway_months` and `confidence`.
  - `--llm-agents financial-triage` registers the agent; it is
    composable with both `pipeline-triage` and `scientific-skeptic`.
    The skeptic `depends_on` every requested triage agent and the
    skeptic prompt renders both triage payloads in dedicated blocks.
  - New tests `tests/test_financial_triage_agent.py`: happy-path with
    per-metric risk tagging, missing-snapshot skip, schema violation,
    bad-enum rejection, and a triple-agent in-graph chain.
- Live Bailian Qwen triple-agent smoke validated on 2026-04-22:
  - `company-report --ticker 09606.HK --auto-inputs --market-data
    hk-public --llm-agents pipeline-triage financial-triage
    scientific-skeptic`: 3 LLM calls, 3 OK, 8502 prompt + 2013
    completion tokens = 10515 total, 42.3 s combined latency (8 s
    financial triage and 20 s pipeline triage in parallel, then 14 s
    skeptic).
  - Financial triage confirmed the deterministic ~98-month runway is
    internally consistent (confidence 0.95) and surfaced only genuinely
    second-order issues: RMB financial_snapshot vs HKD market_snapshot
    currency mismatch, and market-data provider not aggregating
    balance-sheet cash.
  - Skeptic (confidence 0.75) consumed all three upstream findings and
    added analyst-grade observations: "Heavy reliance on a single
    partner (BioNTech) for key late-stage assets creates concentration
    risk", "DB-1303 is in Phase 3 but lacks a defined next milestone
    despite reported primary endpoint achievement". No hallucinated
    financial risks, because `financial-triage` had already vetted the
    runway.
- `company-report --market-data-freshness-days N` now tunes the Tencent
  staleness window without patching code. Implemented by wrapping
  `hk_public_quote_provider` with `functools.partial` when the flag is
  set; positional-only `provider(identity)` contract is preserved.
  Fractional days accepted; non-positive values and the flag paired
  with `--market-data none` are rejected up front.
- Per-agent LLM call budget caps (M4a) are live:
  - `LLMConfig.per_agent_call_budget` (env
    `BIOTECH_ALPHA_LLM_PER_AGENT_CALL_BUDGET`) caps calls any single
    agent can make within one client lifetime.
  - `OpenAICompatibleLLMClient` tracks both total and per-agent
    counters and raises `LLMBudgetError` (subclass of `LLMError`) pre-
    dispatch when either cap is exhausted, so no token is spent and no
    trace entry is written for the refused call.
  - New provider-agnostic `BudgetEnforcingLLMClient` wrapper can sit in
    front of any `LLMClient` (real or fake) to apply the same logic,
    usable for tests or adapters that lack native budget support.
- Fourth LLM agent `MacroContextLLMAgent` is live (M4b):
  - New fact `macro_context`: minimal deterministic stub carrying
    market, sector, report-run date, `financial_as_of_date`, source
    publication dates / titles / types, plus an explicit
    `known_unknowns` list naming the macro signals the
    deterministic layer cannot yet provide (HSI trend, rates/FX,
    news titles, regulatory posture).
  - `MACRO_CONTEXT_PROMPT` / `MacroContextLLMAgent` output strict JSON:
    `macro_regime` ∈
    {"expansion","contraction","transition","insufficient_data"},
    `summary`, `sector_drivers[]`, `sector_headwinds[]`, optional
    `confidence`. Prompt mandates returning `insufficient_data` when
    the stub is too thin to form a view, so the agent cannot
    hallucinate macro themes during the current stub-only phase.
  - `--llm-agents macro-context` registers the agent, composable with
    the other three. Skeptic `depends_on` it when requested and
    renders a `macro_context` block in its prompt.
- Live Bailian Qwen four-agent smoke validated on 2026-04-22:
  - `company-report --ticker 09606.HK --auto-inputs --market-data
    hk-public --llm-agents pipeline-triage financial-triage
    macro-context scientific-skeptic`: 4 LLM calls, 4 OK, 9571 prompt
    + 2348 completion tokens = 11919 total, 52.4 s combined latency
    (financial 8 s, macro 5.8 s, pipeline 22 s in parallel, then
    skeptic 16.6 s).
  - Macro agent correctly returned `macro_regime = insufficient_data`
    with three factually-framed headwinds (rate env unknown, HSI
    trend unavailable, HK biotech IPO sentiment unclear), instead
    of inventing macro prints.
  - Skeptic consumed the macro finding honestly and surfaced it as
    a distinct medium-severity risk: "Macro regime is undefined due
    to missing interest rate and regulatory data, increasing
    uncertainty around cost of capital and approval pathways".
- Macro-signals live feed (M4c) is live:
  - New module `src/biotech_alpha/macro_signals_providers.py` with a
    `MacroSignalsProvider` protocol (`provider(market) -> dict|None`)
    and a first implementation `hk_macro_signals_yahoo` that pulls
    HSI level / 30-day return and USD/HKD spot from Yahoo's public
    `v8/finance/chart` endpoint. All transport/decode failures
    degrade a sub-signal to `None` with a human-readable note,
    never raise.
  - `_build_macro_context` accepts an optional `live_signals` dict,
    attaches it under a `live_signals` key, and prunes the HSI /
    USD-HKD entries from `known_unknowns` so the macro agent knows
    exactly what is still missing (HIBOR, news, FDA/NMPA posture).
  - `build_llm_agent_facts` → `_run_llm_agent_pipeline` →
    `run_company_report` all thread `macro_signals_provider`
    through. When `macro-context` is not in `--llm-agents` the
    provider is skipped. Any provider exception is swallowed so a
    live-feed failure never breaks the one-command run.
  - CLI gains `--macro-signals {none,yahoo-hk}` (default `none`)
    and `_resolve_macro_signals_provider`. `MACRO_CONTEXT_PROMPT`
    now instructs the model to cite `live_signals.hsi` /
    `live_signals.hkd_usd` values by field name and to prefer a
    concrete regime when at least one sub-field is non-null.
  - Tests: `tests/test_macro_signals_providers.py` exercises the
    parser against hand-crafted chart payloads, fake-session
    transport with happy, degraded-one-feed, and all-feeds-failed
    shapes, and integration against `_build_macro_context`.
    `tests/test_cli.py` covers `--macro-signals yahoo-hk`
    threading and default-off behaviour.
  - Live Yahoo probe from this IP is currently rate-limited (429
    from both `query1` and `query2`). The graceful-`None` path
    keeps the old stub-only macro answer; when Yahoo becomes
    reachable again the agent will produce a concrete regime with
    no further code changes.
- Macro-signals disk cache is live:
  - New `CachingMacroSignalsProvider` wraps any `MacroSignalsProvider`
    and keys the cache on `(market, provider_label)`. Same-market
    requests from different companies reuse one successful fetch
    (end-to-end dry run: 3 back-to-back HK requests → 1 upstream
    call). Default TTL 6 hours, default location
    `data/cache/macro_signals/` (gitignored).
  - Stale-if-error: upstream failure with an expired cache on disk
    returns the stale cache with a
    `cache: stale (served on upstream failure...)` note, converting
    a transient Yahoo 429 into slightly-stale regime read instead of
    losing the live feed. Upstream with no cache falls back to
    `None` as before.
  - Writes are atomic (tempfile + rename); disk write failures are
    swallowed so caller never sees a cache-layer error.
  - CLI: `--macro-signals yahoo-hk` returns the caching wrapper by
    default; `--macro-signals-cache-ttl-hours FLOAT` tunes the TTL;
    `--no-macro-signals-cache` bypasses the cache entirely.
  - `.gitignore` adds `data/cache/`.
- Anthropic provider adapter is live:
  - New `src/biotech_alpha/llm/anthropic.py` implements
    `AnthropicLLMClient` over the Messages API and emits the same
    `LLMCall` + `LLMTraceRecorder` fields used by existing agents.
  - `LLMConfig` now supports
    `BIOTECH_ALPHA_LLM_PROVIDER=openai-compatible|anthropic`,
    provider-specific default base URL/model, and
    `ANTHROPIC_API_KEY` env parsing.
  - CLI `_build_llm_client` routes by `LLMConfig.provider`; existing
    openai-compatible path remains default and unchanged.
  - Added offline tests for Anthropic config parsing, client success /
    failure behavior, CLI routing, and macro-context online self-skip
    gate (`BIOTECH_ALPHA_ONLINE_ANTHROPIC_TESTS=1` + key).
- Multi-source macro fallback is live:
  - New `FallbackMacroSignalsProvider` chains
    `Yahoo -> Stooq -> stale cache` while preserving the
    `macro_context.live_signals` shape (`provider`, `hsi`, `hkd_usd`,
    `fetched_at`, `notes`).
  - New fallback source `hk_macro_signals_stooq` provides a no-key
    public backup for HSI level and USD/HKD spot when Yahoo is
    unavailable.
  - CLI `--macro-signals yahoo-hk` now resolves to a cached composite
    provider (`yahoo-hk+stooq-hk`) instead of Yahoo-only.
  - Offline tests now cover Stooq parsing, fallback selection order,
    and resolver behavior under cache/no-cache modes.
- Macro signal breadth is expanded:
  - `live_signals` now carries optional `hsbio` (Hang Seng Biotech
    level snapshot) and `hibor` (overnight / 1M / 3M tenor snapshot
    from HKMA public feed when reachable).
  - `_build_macro_context` now tracks separate unknowns for
    `HSI`, `HSBIO`, and `HIBOR`, then prunes each independently when
    corresponding live signals are present.
  - Yahoo and Stooq providers both attempt HKMA HIBOR snapshot so the
    fallback chain still preserves the broader macro shape.
  - `live_signals.news` is now present when a compact source-tagged
    RSS fetch succeeds (Google News query: "Hong Kong biotech"), and
    `_build_macro_context` removes the "recent sector-relevant news
    titles" unknown when news payload is present.
- Extraction quality hardening landed for milestone leakage:
  - `auto_inputs._draft_asset_from_context` now derives
    `next_milestone` from `local_context` (asset-local window)
    instead of broad context, reducing cross-asset contamination.
  - `_milestone_from_context` now requires milestone-like trigger
    terms and filters stale years against source publication year
    (e.g. prevents spurious `in 2017` leakage into 2026 reports).
  - Regression test now asserts `DB-1312.next_milestone is None`
    while preserving valid `DB-1311 = planned to start in 2026`.
- Pipeline validator hardening landed for weak metadata detection:
  - `validate_pipeline_asset_file` now warns when
    `next_milestone` contains newline/control characters.
  - Validator flags likely stale milestone years relative to evidence
    source date (e.g. `in 2017` under 2026 evidence context).
  - Validator warns on non-positive evidence confidence and inferred
    evidence entries missing `source_date`.

## Current Repo State

- Branch: `main`
- Remote: `origin https://github.com/ykevingrox/alphaLAB.git`
- Check `git log --oneline -1` for the latest committed baseline.
- Expected steady state after a handoff checkpoint is a clean working tree
  except for ignored generated runtime outputs.
- Generated runtime outputs are intentionally ignored by git:
  `data/raw/`, `data/input/generated/`, `data/processed/`, and `data/memos/`.

## Latest Validation

Last validated on 2026-04-22 after M4c macro-signals + disk-cache
rollout (`--macro-signals yahoo-hk` attaches HSI / USD-HKD live data
to the `macro_context` fact and now reuses a single fetch across
every company in the same market via a TTL disk cache; M4 four-agent
runtime, per-agent LLM budget caps, and `--market-data-freshness-days`
unchanged):

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall -q src tests
git diff --check
awk 'length($0) > 88 { print FILENAME ":" FNR ":" length($0) }' \
  $(git ls-files '*.py' '*.md' '*.toml')
```

Latest result:

- 246 unit tests ran, 239 passed, 7 skipped (online Yahoo / online
  Tencent / four online Bailian Qwen integration tests plus the new
  Anthropic macro-context online self-skip; all guarded behind
  `BIOTECH_ALPHA_ONLINE_*_TESTS=1`). The +37 from the previous
  checkpoint cover macro-signals parser + cache + multi-source
  fallback work, Anthropic provider routing/config/client tests, and
  the new `competition-triage` LLM agent coverage. The latest +2 cover
  reusing an existing generated pipeline draft during
  `generate_auto_inputs` while still returning source documents, and
  automatically refreshing old generated drafts when pipeline
  validation flags malformed/stale milestone values.
- Extraction hardening and validator checks are covered by
  `tests/test_auto_inputs.py` and `tests/test_pipeline.py` and
  included in the same 233-test baseline.
- Compile check passed on both `src` and `tests`.
- `git diff --check` passed.
- 88-character scan passed across `git ls-files '*.py' '*.md' '*.toml'`
  plus the four new test files `tests/test_pipeline_triage_agent.py`,
  `tests/test_financial_triage_agent.py`,
  `tests/test_macro_context_agent.py`, and
  `tests/test_macro_signals_providers.py`.
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

# LLM + agent runtime opt-in (four agent)
set -a; source .env; set +a
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs \
  --market-data hk-public \
  --llm-agents pipeline-triage financial-triage macro-context \
    scientific-skeptic

# Same as above, plus live HSI / USD-HKD feed for macro-context
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs \
  --market-data hk-public \
  --macro-signals yahoo-hk \
  --llm-agents pipeline-triage financial-triage macro-context \
    scientific-skeptic

# Tuning Tencent staleness without code changes
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs \
  --market-data hk-public --market-data-freshness-days 0.5

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
- Four-agent DualityBio smoke (`pipeline-triage` + `financial-triage`
  + `macro-context` + `scientific-skeptic`):
  - 4 LLM calls, 4 OK, 9571 prompt + 2348 completion tokens (11919
    total), 52.4 s combined latency (financial 8 s, macro 5.8 s,
    pipeline 22 s ran in parallel in the same DAG layer; skeptic
    16.6 s).
  - Financial triage confirmed deterministic runway is consistent and
    flagged only the expected RMB/HKD currency mismatch caveat.
  - Pipeline triage surfaced the DB-1312 "in 2017" milestone, the
    malformed `\n2026` strings, and the DB-1303 "Phase 3 with no
    next_milestone" cross-asset flag.
  - Macro agent correctly returned `macro_regime =
    insufficient_data` (stub-only phase, no live feeds yet) with
    factually-framed headwinds instead of inventing rate or index
    prints.
  - Skeptic (confidence 0.7) consumed all three upstream findings
    and added analyst-grade observations including the macro
    uncertainty as a distinct medium-severity risk.
- Qwen3's default implicit thinking remains actively suppressed via
  `extra_body.enable_thinking=False` on Bailian; that continues to keep
  completion token usage low.
- `--macro-signals yahoo-hk` is wired end-to-end and now shares a
  single fetch across every company in the same market through
  `CachingMacroSignalsProvider`. Because macro signals (HSI,
  USD/HKD) are per-market, not per-ticker, the analyst running
  back-to-back reports on several HK biotech names in the same
  session hits Yahoo exactly once per TTL (default 6h). Stale-if-
  error semantics turn a transient Yahoo 429 into a slightly-stale
  regime read plus a cache note, instead of losing the live feed.
- Quick `report "<company|ticker>"` terminal output is now
  operator-facing by default: four progress stages, a compact result
  summary, LLM step/cost status, and key artifact paths. `report --json`
  preserves the machine-readable compact summary.
- Live quick-report smoke on 2026-04-22 found and fixed a cached
  generated-input bug: when `<slug>_pipeline_assets.json` already
  existed and `overwrite=False`, `generate_auto_inputs` called a
  missing `_read_json` helper, fell back to discovered inputs, and
  starved pipeline triage of source text. Fixed in
  `src/biotech_alpha/auto_inputs.py`; regression test added in
  `tests/test_auto_inputs.py`.
- Post-fix live smoke:
  `report "09606.HK"` wrote run `20260422T110958Z`, produced
  `research_ready_with_review`, ran 6/6 graph steps OK, 0 skipped,
  used 19096 total LLM tokens, and restored source-grounded pipeline
  triage confidence to 0.95. The same run auto-drafted 8 competitor
  seeds, so `competition-triage` and the final skeptic both ran.
- Macro live-smoke status: `macro-context` returned a concrete
  qualitative regime view from live sector news rather than
  `insufficient_data`; Yahoo/Stooq chart and HKMA HIBOR subfeeds were
  unavailable from this network, so HSI/HSBIO/USD-HKD/HIBOR remained
  `null`. Cache reuse is confirmed: the cache file is
  `data/cache/macro_signals/HK_yahoo-hk_stooq-hk.json` and subsequent
  provider calls return `cache: hit (...)` in `live_signals.notes`.
- Deterministic milestone cleanup is closed for the known quick-report
  false positives:
  - `_milestone_from_context` now normalizes whitespace in year phrases,
    so `planned to start in \n2026` becomes `planned to start in 2026`.
  - Existing generated pipeline drafts are refreshed from the latest
    source when validation sees `next_milestone contains newline/control`
    or `next_milestone year looks stale`.
  - No-LLM quick smoke after the fix:
    `report "09606.HK" --json --no-llm --no-save` refreshed
    `data/input/generated/09606_hk_pipeline_assets.json` and left
    pipeline warnings empty. `report "02142.HK" --json --no-llm
    --no-save` removed stale milestone warnings; remaining warnings are
    unresolved packed-table fields (missing phase / target) that the
    source text does not yet resolve reliably.

## Execution Plan

### Current Task

`--macro-signals yahoo-hk` now threads a broader source-tagged macro
block into `macro_context`: HSI, HSBIO, USD/HKD, HIBOR tenors, and
compact sector news (all optional, all degradable), through a
multi-source chain
`Yahoo -> Stooq -> stale cache`. The disk-backed TTL cache
(`CachingMacroSignalsProvider`) keeps back-to-back HK biotech runs to
one upstream fetch per TTL. Anthropic provider support is implemented
through the same `LLMClient` protocol; remaining M4 work is live smoke
validation and extraction-quality hardening.

Two immediate tracks:

- Extraction-quality hardening. Continue reducing packed-table
  phase/target gaps that inflate triage false positives.
- Macro-signals resiliency check. News-backed non-`insufficient_data`
  macro context and cache reuse are confirmed; quantitative chart/HIBOR
  subfeeds still need a follow-up when provider access recovers.

### Next Action

1. Improve packed-table extraction for the remaining Harbour BioMed
   generated warnings: `HAT001`, `HBM2001`, `J9003`, `R2006`,
   `R7027`, and `HBM1020` still lack reliable phase and/or
   target/mechanism fields.
2. Keep Yahoo retry/backoff intentionally out-of-scope for now (per
   operator preference). Re-check quantitative HSI/HSBIO/USD-HKD/HIBOR
   subfeeds later; for now sector news plus cache-hit fallback are
   working.
3. Expand competitor seed dictionaries + fixture coverage so
   auto-drafted competitors cover more HK biotech target families.
4. Keep quick CLI UX stable: `report "<company|ticker>"` must remain
   one-command with default LLM-on behavior and explicit opt-out only.

### Acceptance Criteria

- `--macro-signals yahoo-hk` live smoke keeps producing non-
  `insufficient_data` when live sector news is available, and
  subsequent same-market runs show `cache: hit` in
  `macro_context.live_signals.notes`.
- Multi-source fallback path keeps one-command runs resilient under
  single-provider outages and still writes stable
  `macro_context.live_signals` keys.
- Anthropic implementation remains test-covered offline; online smoke
  is deferred until an API key is available.
- No regression on the existing four-agent Qwen smoke or on the
  macro-signals offline tests.

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
  --llm-agents pipeline-triage financial-triage macro-context \
    scientific-skeptic
```

### Queue

1. Improve packed-table extraction for remaining Harbour BioMed
   phase/target gaps without inventing source-unsupported fields.
2. Re-check quantitative macro feeds from a fresh network or after
   provider rate limits recover; no retry/backoff work for now.
3. Keep broadening fixtures across representative HK biotech disclosure
   styles.
4. Tighten validator checks for stale placeholders and weak evidence
   metadata.
5. Add a US-market sibling market-data provider, so the auto-draft path
   is not HK-only.
6. Consider a deterministic post-processor that turns LLM findings into
   an `InvestmentMemo.llm_addendum` so memo downstream consumers do not
   need to parse `data/memos/*_llm_findings.json` separately.
7. Consider a `K-line technical agent` (name TBD) that reads a
   small window of OHLCV plus a few classic indicators and flags
   technical divergences vs the fundamental / macro read. Useful as
   an entry / exit sanity layer.

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
