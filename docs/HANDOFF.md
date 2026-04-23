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
  `HAT001/HBM9013`, `HBM7004`, `HBM2001`, `J9003`, `R2006`,
  `R7027`, and `HBM1020`: `anti-CRH` is preferred for HAT001,
  B7H4/CD3 context no longer leaks the next numbered section,
  undisclosed rows keep `target = null` plus an `undisclosed target`
  mechanism, and target-backed rows no longer carry
  undisclosed-mechanism noise. Remaining warnings are intentional:
  missing phases or indications that the source text does not reliably
  resolve.
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
- Auto competitor seed drafting now has a versioned extractor and broader
  conservative target-overlap coverage for Harbour BioMed-style targets:
  BCMA/CD3, CTLA-4, FcRn, TSLP, and normalized B7H4/B7-H4 composite
  matching. Existing generated competitor drafts refresh when their
  extractor version is stale. Target-overlap seeds keep competitor
  indication as `to_verify` so the pipeline asset's indication is not
  misrepresented as a competitor label.
- Global competitor discovery ingestion is now wired into the same generated
  competitor draft path. If
  `data/input/generated/<slug>_competitor_discovery_candidates.json` exists,
  `draft_competitor_assets` review-gates each candidate before adding it:
  source URL, source date, evidence snippet, rationale, non-self company, and
  deterministic target-family match are required. Accepted rows remain
  `needs_human_review` / `is_inferred` and carry the candidate's evidence URL;
  rejected candidates are counted in `candidate_ingest`.
- ClinicalTrials.gov competitor discovery is the first live source connected
  to that candidate path. Quick `report "<company|ticker>"` enables it by
  default; `company-report` exposes `--competitor-discovery clinicaltrials`.
  The runner is bounded and conservative: trial text must mention the full
  target family before it becomes a review-gated candidate.
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
    default model `qwen3.5-plus`, opt-in `enable_thinking`),
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
- Historical Bailian Qwen four-agent smoke validated on 2026-04-22:
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
- Fifth LLM agent `CompetitionTriageLLMAgent` is live:
  - `--llm-agents competition-triage` audits deterministic competitor
    matching outputs and writes `competition_triage_llm_finding`.
  - When chained with `scientific-skeptic`, the skeptic consumes
    competition findings alongside pipeline, financial, and macro payloads.
  - The quick `report "<company|ticker>"` path now enables all five LLM
    agents by default unless `--no-llm` is passed.
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
- Extraction audit visibility and persistence are live for quick reports:
  - `company_report_summary` now includes `extraction_audit`, with per-asset
    source support, missing-field reasons, evidence snippets, source-anchor
    metadata, and top review assets.
  - Quick terminal output prints `Extraction audit` plus `Audit focus`, so an
    operator can see immediately whether extraction was clean, merely
    review-gated, or missing source anchors.
  - Saved quick reports write
    `data/processed/single_company/<slug>/<run_id>_extraction_audit.json`,
    print that path in the terminal artifact list, and attach it to
    `manifest.artifacts.extraction_audit`.
  - Repeated-asset `source_text_excerpt` selection now ranks every mention and
    prefers phase / IND / BLA / trial-rich windows instead of blindly using the
    first mention. `anchor_details` exposes hit counts and signal scores to the
    pipeline-triage prompt.
  - ClinicalTrials.gov version/search failures now degrade to
    `input_validation["clinical_trials"]` warnings instead of aborting the
    one-command report when one upstream query disconnects.
- Third HK biotech source-snapshot fixture is live for Leads Biolabs
  (`09887.HK`, 維立志博):
  - `PIPELINE_EXTRACTOR_VERSION = 9` refreshes stale generated drafts.
  - The fixture guards source-scoped extraction, not current live truth:
    LBL-024 BLA-submission status, LBL-047/DNTH212 aliasing, BDCA2/TACI
    fusion-protein modality, TCE-ADC targets, PCC milestones, and listing-rule
    warning / abbreviation-table leakage are now regression-tested.
  - The parser now prefers stronger repeated evidence for target, modality,
    indication, and phase; ignores generic pipeline table phase ladders; treats
    `known as ... outside of China` as an alias relation; and parses BLA/PCC
    milestone phrases from source text.
- Fourth representative HK disclosure-style fixture coverage is now added in
  offline tests for Innovent Biologics (`01801.HK` style text) under
  `tests/test_auto_inputs.py`: HKD thousand-unit financial parsing, mixed
  Phase 3 / Phase 1b / IND-enabling extraction, anti-target parsing
  (`anti-LAG-3`), and milestone phrase normalization (`planned to start in
  2027`). Existing behavior is unchanged; this is regression coverage only.
- Sprint 5 "From Data Sheet To Investment Memo" planned in
  `docs/ROADMAP.md`. The plan covers P0.1 default rNPV draft, P0.2 memo
  template rewrite, P0.3 `InvestmentThesisLLMAgent`, P0.4 Core Asset
  Deep Dive, P1.5-1.8 cross-agent merge / catalyst ranking / scorecard
  transparency / action plan, P2 data breadth, and P3 strategic
  additions. Design principles, acceptance criteria per task, and a
  concrete execution order are recorded there. `docs/HANDOFF.md`
  Current Task, Next Action, Acceptance Criteria, Validation, and
  Queue now all point to Sprint 5 P0.1 as the next work unit.
- Documentation drift pass on 2026-04-23: `README.md`, `docs/RUNBOOK.md`,
  `docs/DATA_SOURCES.md`, `docs/ARCHITECTURE.md`, `docs/PRD.md`, and
  `docs/ROADMAP.md` were reconciled with the current codebase.
  - `README.md` Repository Layout now lists `agent_runtime.py`,
    `agents_llm.py`, `llm/`, `market_data.py`, `market_data_providers.py`,
    `macro_signals_providers.py`, and every current test file. Quick Start
    adds the install step, runtime dependency list, and `.env` guidance.
  - `RUNBOOK.md` drops the stale "no third-party runtime dependencies"
    claim, documents the runtime deps, adds an LLM Setup section covering
    provider switching / call budgets / trace dir / `--allow-no-llm`, and
    lists `_extraction_audit.json`, `_llm_findings.json`, `data/traces/`,
    and `data/cache/` under Outputs.
  - `DATA_SOURCES.md` removes the empty `Official And Public Sources`
    heading and adds dedicated `Market Data Providers`, `Macro Signal
    Providers`, and `LLM Providers` subsections.
  - `ARCHITECTURE.md` documents `AgentGraph` / `FactStore` / opt-in LLM
    agent layering, lists `data/input/generated/`, `data/traces/`, and
    `data/cache/` under Suggested Storage, and adds `report` to the MVP
    Runtime CLI list.
  - `PRD.md` moves the LLM agent runtime, market-data providers, macro
    signals, ClinicalTrials.gov competitor discovery, and the quick
    `report` entry into Implemented, and rewrites the Pending list around
    US-market coverage, broader document ingestion, and technical / K-line
    timing.
  - `ROADMAP.md` bumps the last status-pass stamp to 2026-04-23 and folds
    the Innovent Biologics (`01801.HK`) fixture into Sprint 1 status.
- Sprint 5 P0.1/P0.2/P0.3 landed in code and tests:
  - default target-price assumption draft is auto-generated in
    `data/input/generated/<slug>_target_price_assumptions.json` and consumed
    by report paths unless a curated override exists.
  - memo rendering is now investment-first (Executive Verdict -> Investment
    Thesis -> Core Asset Deep Dive -> Catalyst Roadmap -> Competition ->
    Financials -> Valuation -> Scorecard Transparency -> Key Risks -> Evidence).
  - `InvestmentThesisLLMAgent` is wired into the AgentGraph and CLI
    (`--llm-agents investment-thesis`, quick `report` default stack).
- Sprint 5 P1 implementation progress:
  - P1.6 Catalyst Roadmap now includes deterministic time buckets
    (0-6m / 6-18m / 18m+) and value-weighted ranking by `impact_score`.
  - P1.7 scorecard transparency is improved via explicit per-dimension score
    lines in scorecard findings.
  - P1.8 memo now includes a dedicated `## Research-Only Action Plan` section
    with sizing tier, entry focus, and de-risk triggers, explicitly labeled as
    research support only.
- Sprint 5 follow-up implementations landed and are covered by tests:
  - P0.4 deep dive now supports structured `clinical_data` datapoints
    (`metric/value/unit/sample_size/context`) with backward-compatible loading
    for legacy string rows.
  - Memo `Core Asset Deep Dive` now renders structured clinical datapoints and
    key assets are ranked by Phase 2+ priority plus trial-match strength.
  - P1.8 now has a dedicated deterministic module
    `src/biotech_alpha/position_action.py` and emits a structured
    `research_action_plan_agent` finding that feeds the memo section.
  - P1.7 transparency follow-up is now end-to-end:
    `result_summary` + saved run manifest include per-dimension
    `score/weight/contribution/rationale`, and `watchlist-rank` supports
    `--with-scorecard-dimensions` to expand JSON rows and CSV columns.
- P0.4 extraction evaluation harness landed:
  - Added canonical ground-truth case set at
    `tests/fixtures/p0_4_ground_truth_cases.json` to benchmark
    `regulatory_pathway` and `next_binary_event`.
  - Added deterministic evaluator module
    `src/biotech_alpha/p0_4_ground_truth.py` plus script
    `scripts/eval_p0_4_ground_truth.py` for CI/local threshold checks.
  - Added regression gate test `tests/test_p0_4_ground_truth.py` and expanded
    extraction patterns for BLA filing/acceptance phrasing and
    topline/interim/readout event phrasing.
- P1.8 edge-case hardening progressed:
  - `position_action.py` now forces conservative `0.0%` sizing when valuation
    anchors are incomplete/invalid.
  - Memo action-plan rendering now preserves the explicit
    "research support only" disclaimer even when risk bullets are truncated.
  - Non-finite valuation anchors (`NaN/inf`) now degrade safely to
    `entry zone unavailable` + `0.0%` sizing, and findings now include
    `guidance_type=research_only` for explicit downstream labeling.
  - `result_summary` and saved manifest now include a structured
    `research_action_plan` payload, preserving `guidance_type`,
    entry-zone bounds, trigger list, and review flags.
- P0/P1 remaining closures landed in deterministic path:
  - Scorecard transparency now includes `### Path to Core Candidate` with
    top-3 lowest-contribution dimensions and concrete evidence-to-improve lines.
  - Core Asset Deep Dive now adds deterministic competitor-linked
    differentiation lines when curated competitive matches exist.
  - Key Risks rendering now tags medium/high LLM triage risks
    (`confidence >= 0.4`) as `source: llm[agent_name]`.

## Current Repo State

- Branch: `main`
- Remote: `origin https://github.com/ykevingrox/alphaLAB.git`
- Check `git log --oneline -1` for the latest committed baseline.
- Expected steady state after a handoff checkpoint is a clean working tree
  except for ignored generated runtime outputs.
- Generated runtime outputs are intentionally ignored by git:
  `data/raw/`, `data/input/generated/`, `data/processed/`, and `data/memos/`.

## Latest Validation

Last validated on 2026-04-23 after switching the development/default Bailian
model to `qwen3.5-plus`, cleaning up LLM-agent documentation drift, Leads
Biolabs (`09887.HK`) fixture hardening, extraction-audit persistence,
repeated-anchor source excerpt ranking, and ClinicalTrials.gov failure
degradation. Extractor versions: `PIPELINE_EXTRACTOR_VERSION = 9` and
`COMPETITOR_EXTRACTOR_VERSION = 5`:

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall -q src tests
git diff --check
awk 'length($0) > 88 { print FILENAME ":" FNR ":" length($0) }' \
  $(git ls-files '*.py' '*.md' '*.toml')
```

Latest result:

- 262 unit tests ran, 255 passed, 7 skipped (online Yahoo / online
  Tencent / Bailian Qwen integration tests plus Anthropic online
  self-skips; all guarded behind `BIOTECH_ALPHA_ONLINE_*_TESTS=1`).
  The latest coverage adds the Leads Biolabs source-snapshot fixture, saved
  extraction-audit artifact wiring, extraction-audit summary assertions,
  repeated-asset excerpt ranking, and ClinicalTrials.gov per-term failure
  degradation.
- Competitor draft generation now emits `discovery_requests` for each
  pipeline target, ingests local LLM/web discovery candidate packs from
  `*_competitor_discovery_candidates.json`, and can fill that candidate pack
  from ClinicalTrials.gov. Offline tests cover accepting a source-backed
  GPRC5D/CD3 global candidate for Leads Biolabs, rejecting self-company /
  loose-target / no-source candidates, and turning a CT.gov HER2 trial into a
  review-gated competitor candidate. Candidate packs also carry
  `rejection_summary`, including generic-target-intervention rejections so
  background therapies such as HSCT are not mistaken for competitor assets.
- Extraction hardening and validator checks are covered by
  `tests/test_auto_inputs.py` and `tests/test_pipeline.py` and
  included in the same full-test validation baseline.
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
- Quick no-LLM smoke:
  `report "09606.HK" --json --no-llm --no-save` leaves pipeline
  warnings empty and auto-drafts 8 competitor seeds.
  `report "02142.HK" --json --no-llm --no-save` auto-drafts 7
  competitor seeds, refreshes pipeline drafts to v6, and leaves only
  source-unsupported pipeline warnings: `HAT001` missing indication
  and phase; `HBM2001`, `J9003`, `R2006`, `R7027`, and `HBM1020`
  missing phase.
- Quick 02142 extraction-audit smoke:
  `report "02142.HK" --json --no-llm --no-save` returns
  `extraction_audit.status = review_required`, 6/12 assets supported,
  6 review-gated, 0 missing anchors, and 12 source anchors. The terminal
  path prints the same signal as:
  `Extraction audit: 6/12 supported, 6 need review, 0 missing anchors`.
  Saved mode also writes and prints
  `data/processed/single_company/02142-hk/<run_id>_extraction_audit.json`,
  and the manifest carries the same path under
  `artifacts.extraction_audit` plus a compact manifest audit summary.
- Full 02142 quick-report smoke:
  `report "02142.HK" --json --no-save` completed 6/6 graph steps OK
  on 2026-04-23 with quality gate `research_ready_with_review`, 12
  assets, 19 trials, 7 competitors, and 2 catalysts. Pipeline triage now
  sees the later HBM7020 Phase I source window, and the remaining
  HBM7020 concern is substantive field mismatch review
  (`autoimmune diseases` vs source text pointing to oncology Phase I),
  not a source-excerpt coverage miss.
- Quick Leads Biolabs (`09887.HK`) smoke:
  `report "09887.HK" --json --no-llm --no-save` now returns 12 assets,
  22 trials, 1 competitor, 13 catalysts, 3 input warnings, and extraction
  audit `10/12 supported`, `2 need review`, `0 missing anchors`. The remaining
  review assets are `LBL-056` and `LBL-082`, both missing target/mechanism
  because the source gives modality descriptions but not molecular targets.
  After the ClinicalTrials.gov competitor-discovery runner landed, a broader
  smoke using `company-report --ticker 09887.HK --auto-inputs
  --overwrite-auto-inputs --competitor-discovery clinicaltrials
  --competitor-discovery-max-requests 3 --no-asset-queries --limit 1
  --no-save` completed in 8.8 s. It accepted ABL Bio `ABL503`
  (NCT04762641), Janssen `Talquetamab` (NCT04773522), and `QLS32015`
  as review-gated CT.gov candidates; rejected 5 non-target-family records
  and 2 generic target interventions; and refreshed the generated competitor
  draft to 4 rows with `candidate_ingest = 3 accepted / 0 rejected`.
  Full quick-report LLM smoke (`report "09887.HK" --json --no-save`) completed
  6/6 graph steps OK with 17,371 total LLM tokens. Pipeline triage now says the
  snapshot largely aligns with source text; remaining issues are real research
  gaps: LBL-024 non-standard phase wording / competitive context, LBL-056 and
  LBL-082 null targets, and sparse competitor benchmarking.
- LLM default model is now `qwen3.5-plus` for development and compatibility
  smoke testing. The previous LLM ping (`scripts/llm_smoke.py`, Bailian
  `/compatible-mode/v1`, `qwen3.6-plus`, `enable_thinking=False`) used
  1 call, 28 completion tokens, 3.0 s latency, satisfied the schema, and
  recorded a trace. Run live smoke whenever it is needed to validate behavior.
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

# LLM + agent runtime opt-in (five agents)
set -a; source .env; set +a
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs \
  --market-data hk-public \
  --llm-agents pipeline-triage financial-triage competition-triage \
    macro-context scientific-skeptic

# Same as above, plus live HSI / USD-HKD feed for macro-context
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs \
  --market-data hk-public \
  --macro-signals yahoo-hk \
  --llm-agents pipeline-triage financial-triage competition-triage \
    macro-context scientific-skeptic

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
- Historical four-agent DualityBio smoke (`pipeline-triage` +
  `financial-triage` + `macro-context` + `scientific-skeptic`):
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
- Current development/default model is `qwen3.5-plus`. Use
  `BIOTECH_ALPHA_LLM_MODEL=qwen3.6-plus` or another stronger model whenever
  the research task needs it.
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
- Harbour BioMed packed-table target/mechanism cleanup landed:
  - Generated pipeline drafts now carry
    `generated_extractor_version = 6`; older generated drafts refresh
    automatically so stale local generated files pick up extractor fixes.
  - Generated competitor drafts now carry
    `generated_extractor_version = 4`; stale target-overlap seed drafts
    refresh automatically.
  - HAT001/HBM9013 now prefers the nearby `anti-CRH` target instead of
    leaking BCMA/CD3 from the following HBM7020 paragraph.
  - HBM7004/B7H4-CD3 context now stops at the next numbered section,
    so Metabolic Disease / obesity text no longer contaminates the
    oncology indication.
  - Phase extraction no longer treats `Phase 3.0 strategic era` as a
    clinical Phase 3. BLA statuses and IND approvals are now preferred
    when the source text states them directly.
  - Partner extraction now uses an asset-local window with a small left
    context and truncates inline numbered sections, so HBM9378 keeps
    `Kelun; Windward` without swallowing HAT001's Spruce deal.
  - HBM7020 now resolves to `Phase I` / `Otsuka`; HBM9161 to
    `BLA under review`; HBM4003 to partner `Solstice`; HBM7575 to
    `IND approved`.
  - `J9003` and `R7027` preserve `target = null` because the source says
    `Undisclosed`, but now set `mechanism = "undisclosed target"` so the
    validator no longer reports missing target/mechanism.
  - `HBM2001` and `R2006` keep their source-backed targets without an
    `undisclosed target` mechanism.
  - Competitor seeds now include BCMA/CD3, CTLA-4, FcRn, TSLP, and
    normalized B7H4/B7-H4 matching. Seed indications are `to_verify`;
    the pipeline asset indication appears only in the evidence claim as
    context, not as a competitor fact.
  - No-LLM quick smoke after the fix:
    `report "02142.HK" --json --no-llm --no-save` now leaves only
    source-unsupported warnings: `HAT001` missing indication and phase;
    `HBM2001`, `J9003`, `R2006`, `R7027`, and `HBM1020` missing phase.
- Extraction-audit UX landed:
  - `report "02142.HK" --no-llm` prints four progress stages,
    the operator result summary, artifact paths, and:
    `Extraction audit: 6/12 supported, 6 need review, 0 missing anchors`.
  - `Audit focus` lists the first review assets and reasons, currently
    `HAT001`, `HBM2001`, and `J9003` for Harbour BioMed.
  - Saved runs write a dedicated extraction-audit artifact and attach it to
    the manifest. JSON output also carries the full
    `extraction_audit.assets[]` table for downstream scripts or UI work.
  - Live LLM quick smoke completed 6/6 steps OK after the excerpt-ranking
    change; HBM7020 moved from an excerpt visibility problem to a real
    target/indication consistency review.

## Execution Plan

### Current Task

Continue **Sprint 5: From Data Sheet To Investment Memo** after deterministic
P0/P1 closure:
**P2.x Data breadth (next phase pick by highest memo gap)**.

Current baseline now has target-price defaults, investment-thesis integration,
value-weighted catalyst ranking, structured scorecard transparency, structured
research-only action planning, and deep-dive clinical datapoint rendering. P0.4
ground-truth expansion is now intentionally deprioritized to unblock other
Sprint 5 workstreams first.

### Next Action

1. Start P2 with the highest-impact data gap visible in current memo quality
   (China CDE or HKEXnews RSS first).
2. Keep optional `AssetDeepDiveLLMAgent` as a non-blocking enhancement track.
3. Re-open deeper P0.4 source-like expansion only if deterministic extraction
   quality regresses on canonical fixtures.

### Acceptance Criteria

- Sprint 5 P0/P1 deterministic checkpoints: done.
  1. `position_action.py` handles absent/invalid/non-finite anchors with
     conservative degradation.
  2. Suggested sizing falls back to `0.0%` when entry-zone anchors are
     unavailable.
  3. Memo/finding text keeps explicit research-only framing and
     `guidance_type=research_only`.
  4. Unit tests cover absent share price, inverted ranges, non-signal language,
     and non-finite valuation inputs.
  5. Summary/manifest expose structured `research_action_plan` payload.
  6. Scorecard section includes deterministic top-3 lift targets.
  7. Core asset deep-dive includes deterministic competitor-linked
     differentiation lines when match evidence exists.
  8. LLM triage medium/high risks are tagged with source in Key Risks rendering.
- Sprint 5 global invariants (all tasks): deterministic report still
  runs under `--no-llm`; every auto-generated assumption carries
  `needs_human_review=true` until a curated override lands; every new
  LLM agent accepts a per-agent model override.

### Validation

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m compileall -q src tests
git diff --check
awk 'length($0) > 88 { print FILENAME ":" FNR ":" length($0) }' \
  $(git ls-files '*.py' '*.md' '*.toml')

# After P0.1 lands, check the canonical tickers for a populated
# Catalyst-Adjusted Valuation section.
for ticker in 09887.HK 09606.HK 02142.HK 01801.HK; do
  .venv/bin/python -m biotech_alpha.cli report "$ticker" --no-llm --no-save
done

# Live LLM smoke still available (requires .env with BIOTECH_ALPHA_LLM_API_KEY)
.venv/bin/python -m biotech_alpha.cli company-report \
  --ticker 09606.HK --auto-inputs --market-data hk-public \
  --llm-agents pipeline-triage financial-triage competition-triage \
    macro-context scientific-skeptic
```

### Queue

Sprint 5 execution order (full detail in `docs/ROADMAP.md`):

1. **P2.x** Data breadth: China CDE registry, HKEXnews RSS, License/BD
   events, peer valuation, equity history (pick based on the gap the
   P0 / P1 memo reveals).
2. **P3.x** Strategic additions: K-line agent, historical memo diff,
    portfolio concentration, bilingual memo, HTML/PDF export.
3. Optional enhancement backlog: `AssetDeepDiveLLMAgent`, deeper source-like
   ground-truth expansion, and additional cross-agent merge heuristics.

Pre-Sprint 5 backlog retained for later:

- Run live `qwen3.5-plus` smoke when provider/model compatibility or
  end-to-end behavior needs validation.
- Re-check quantitative macro feeds when provider rate limits recover.
- Add one more representative HK biotech disclosure-style fixture
  (distinct from DualityBio, Harbour BioMed, Leads Biolabs, Innovent).
- Tighten validator checks for stale placeholders and weak evidence
  metadata.
- Add a US-market sibling market-data provider so auto-draft is not
  HK-only.

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
- Sprint 5 adds: auto-generated target-price assumptions, thesis findings,
  action-plan fields, and any other inferred content must carry
  `needs_human_review=true` / `inferred_by=...` until a curated override
  lands. Action-plan / position-plan output must be framed as research
  support only — never as a trading instruction.
- `OpenAICompatibleLLMClient` must never read API keys from CLI arguments or
  log them; keys come from env (`BIOTECH_ALPHA_LLM_API_KEY` preferred,
  `DASHSCOPE_API_KEY` fallback) loaded from `.env` (gitignored).
- Qwen3 Bailian calls must explicitly pass `extra_body.enable_thinking`
  (True or False) controlled by `LLMConfig.enable_thinking`; do not omit
  the field or Qwen3 silently consumes extra completion tokens on thinking.
- `AgentFinding` remains the single contract every agent (deterministic or
  LLM) must emit; new agents must not invent parallel return types.
