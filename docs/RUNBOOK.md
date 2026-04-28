# Runbook

This runbook explains how to operate the current CLI research workflow. The
README gives the project overview; this file is the step-by-step operating
guide.

## Prerequisites

- Python 3.11 or newer.
- Network access for ClinicalTrials.gov calls, HKEX filings download, market
  data feeds (Tencent/Yahoo), and macro feeds (Yahoo/Stooq) when those options
  are enabled.
- Commands are run from the repository root.

Install runtime dependencies declared in `pyproject.toml`:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

Runtime dependencies: `anthropic`, `beautifulsoup4`, `openai`, `pypdf`,
`requests`. No other third-party runtime dependencies are required.

Optional market-history adapter:

```bash
.venv/bin/pip install -e ".[market]"
```

The `market` extra installs `yfinance` for historical OHLCV adapters. The core
CLI still works without it.

## LLM Setup

Quick-report (`report ...`) and full LLM agents require API credentials.

- Copy `.env.example` to `.env` and fill in the real values; `.env` is
  gitignored.
- Default provider is `openai-compatible` (Aliyun Bailian / DashScope). Set
  `BIOTECH_ALPHA_LLM_API_KEY` (or `DASHSCOPE_API_KEY`) and keep
  `BIOTECH_ALPHA_LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`.
- To use Anthropic, set `BIOTECH_ALPHA_LLM_PROVIDER=anthropic` and
  `ANTHROPIC_API_KEY`.
- Optional controls: `BIOTECH_ALPHA_LLM_MODEL` (default `qwen3.5-plus`),
  `BIOTECH_ALPHA_LLM_CALL_BUDGET`, `BIOTECH_ALPHA_LLM_PER_AGENT_CALL_BUDGET`,
  `BIOTECH_ALPHA_LLM_TRACE_DIR` (defaults to `data/traces/`, gitignored),
  `BIOTECH_ALPHA_LLM_DEBUG_PROMPT=1` to dump rendered prompts under
  `data/traces/`.
- `.env` values override shell environment when no explicit env dict is passed
  to `LLMConfig.from_env()`, to keep the project-local config predictable.

When LLM env is missing, quick `report` now auto-degrades to deterministic mode
by default and prints an explicit fallback note. `company-report --llm-agents`
continues to support `--allow-no-llm` for deterministic fallback behavior.

## Sanity Checks

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Check the CLI surface:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli --help
PYTHONPATH=src python3 -m biotech_alpha.cli report --help
PYTHONPATH=src python3 -m biotech_alpha.cli company-report --help
PYTHONPATH=src python3 -m biotech_alpha.cli research --help
PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank --help
PYTHONPATH=src python3 -m biotech_alpha.cli catalyst-alerts --help
PYTHONPATH=src python3 -m biotech_alpha.cli target-price-template --help
PYTHONPATH=src python3 -m biotech_alpha.cli target-price-validate --help
PYTHONPATH=src python3 -m biotech_alpha.cli conference-template --help
PYTHONPATH=src python3 -m biotech_alpha.cli conference-validate --help
```

Check ClinicalTrials.gov access:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli clinical-trials-version
```

## Minimal Research Smoke Test

The high-level command runs the current report pipeline, auto-discovers matching
curated inputs under `data/input`, and writes a missing-input report when inputs
are absent:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli company-report \
  --company "Akeso" \
  --ticker "9926.HK" \
  --limit 3
```

For one-command operator UX (company/ticker in, report out), use:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli report "DualityBio"
```

Quick-mode behavior:

- Prints progress stages, then a compact terminal summary with quality gate,
  decision, coverage counts, LLM status, and artifact paths. Use `--json` to
  print the compact machine-readable summary instead.
- Auto-enables draft input generation (`auto_inputs`).
- Auto-enables market data (`hk-public`) and macro live signals (`yahoo-hk`).
- Auto-enables ClinicalTrials.gov competitor discovery for generated
  competitor candidate packs.
- Auto-enables the full current LLM agent stack:
  `provisional-pipeline`, `provisional-financial`, `pipeline-triage`,
  `financial-triage`, `competition-triage`, `macro-context`,
  `scientific-skeptic`, `investment-thesis`, `valuation-commercial`,
  `valuation-rnpv`, `valuation-balance-sheet`, `valuation-committee`,
  `report-quality`.
- The monolithic `valuation-specialist` remains available for
  reproducibility via `company-report --llm-agents valuation-specialist`,
  but is no longer the default quick-report valuation path.
- `market-regime-timing` and `market-expectations` are available as opt-in
  Stage B scaffolds for `company-report --llm-agents ...`; they are not in
  quick `report` defaults yet.
- Auto-degrades to deterministic mode when LLM env is missing or invalid, with
  explicit terminal fallback output.

Architecture note:

- The target runtime is a multi-LLM-agent collaborative topology (see
  `docs/ARCHITECTURE_AUDIT.md`).
- Current quick `report` already runs a subset of specialist LLM agents.
- Planned next upgrades are biotech valuation framing calibration,
  `strategic-economics-agent`, `catalyst-agent`, and deeper Stage B
  market-context calibration.

Expected behavior:

- A memo is written under `data/memos/`.
- A run manifest is written under `data/processed/single_company/`.
- `<run_id>_missing_inputs_report.json` lists any missing curated inputs.
- The CLI output and missing-input report include `next_actions`,
  `template_command`, and `rerun_command` fields so the next step is explicit.
- `needs_human_review` may be `true` when important inputs are missing.

For the HK biotech MVP, use `--auto-inputs` when you want the system to create
draft pipeline, financial, and conference-catalyst inputs before running the
report:

```bash
.venv/bin/python -m biotech_alpha.cli company-report \
  --company "映恩生物" \
  --ticker "09606.HK" \
  --auto-inputs \
  --limit 20
```

This currently:

- Resolves the HKEX stock id from the ticker.
- Searches HKEXnews for the latest annual results announcement.
- Downloads the source PDF under `data/raw/hkex/`.
- Extracts text with `pypdf`.
- Writes draft inputs under `data/input/generated/`.
- Optionally writes a ClinicalTrials.gov competitor-discovery candidate pack
  when `--competitor-discovery clinicaltrials` is enabled.
- Runs `pipeline-validate` and `financial-validate` internally.
- Runs `conference-validate` internally.
- Runs the report with those generated inputs.

Generated inputs are drafts and remain `needs_human_review: true`.

The lower-level `research` command is still useful for debugging and exact
input control. This version runs only the company-level ClinicalTrials.gov
search and does not write artifacts:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli research \
  --company "Akeso" \
  --ticker "9926.HK" \
  --limit 3 \
  --no-save
```

Expected behavior:

- `trial_count` should be non-zero when ClinicalTrials.gov is reachable.
- `artifacts` should contain only `null` values because `--no-save` was used.
- `needs_human_review` may be `true` because curated pipeline, financial, and
  competitor inputs were not supplied.

## Prepare Curated Inputs

The current system uses curated JSON inputs for company-disclosed pipeline
assets, financial snapshot data, and competitor assets. These templates are
editable starter files, not final source data.

Create templates:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli pipeline-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_pipeline_assets.json

PYTHONPATH=src python3 -m biotech_alpha.cli financial-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_financials.json

PYTHONPATH=src python3 -m biotech_alpha.cli competitor-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_competitors.json

PYTHONPATH=src python3 -m biotech_alpha.cli valuation-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_valuation.json

PYTHONPATH=src python3 -m biotech_alpha.cli conference-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_conference_catalysts.json

PYTHONPATH=src python3 -m biotech_alpha.cli target-price-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_target_price_assumptions.json
```

Edit the generated files before using them for research:

- Replace `Example ...` placeholder values.
- Replace `YYYY-MM-DD` dates.
- Use source filenames, document IDs, or URLs in each evidence `source`.
- Add aliases and drug codes because these expand ClinicalTrials.gov searches.

Validate inputs:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli pipeline-validate \
  data/input/akeso_pipeline_assets.json

PYTHONPATH=src python3 -m biotech_alpha.cli financial-validate \
  data/input/akeso_financials.json

PYTHONPATH=src python3 -m biotech_alpha.cli competitor-validate \
  data/input/akeso_competitors.json

PYTHONPATH=src python3 -m biotech_alpha.cli valuation-validate \
  data/input/akeso_valuation.json

PYTHONPATH=src python3 -m biotech_alpha.cli conference-validate \
  data/input/akeso_conference_catalysts.json

PYTHONPATH=src python3 -m biotech_alpha.cli target-price-validate \
  data/input/akeso_target_price_assumptions.json
```

Validation returns exit code `1` for structural errors and exit code `0` when
the file can be loaded. Warnings are still important; they are also preserved in
the research run manifest.

## Full Single-Company Run

Run the current full workflow:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli research \
  --company "Akeso" \
  --ticker "9926.HK" \
  --pipeline-assets data/input/akeso_pipeline_assets.json \
  --financials data/input/akeso_financials.json \
  --competitors data/input/akeso_competitors.json \
  --valuation data/input/akeso_valuation.json \
  --conference-catalysts data/input/akeso_conference_catalysts.json \
  --target-price-assumptions data/input/akeso_target_price_assumptions.json \
  --limit 20
```

Useful options:

- `--search-term`: override the company-level ClinicalTrials.gov search term.
- `--no-asset-queries`: search only by company/search term, not asset aliases.
- `--max-asset-query-terms`: cap extra asset-name and alias searches.
- `--competitor-discovery clinicaltrials`: fill generated competitor
  candidate packs from ClinicalTrials.gov target discovery requests.
- `--competitor-discovery-max-requests`: cap how many target discovery
  requests are sent to ClinicalTrials.gov.
- `--output-dir`: write artifacts somewhere other than `data/`.
- `--no-save`: run without writing artifacts.

## Outputs

Saved runs use this shape:

```text
data/raw/clinicaltrials/<slug>/
data/processed/single_company/<slug>/
data/memos/<slug>/
```

Important files:

- `<run_id>_manifest.json`: run metadata, counts, artifact paths, source
  versions, search terms, and input validation reports.
- `<run_id>_missing_inputs_report.json`: one-command report completeness gaps
  and suggested curated input paths.
- `<run_id>_search.json`: raw ClinicalTrials.gov responses by search term.
- `<run_id>_trials.json`: normalized trial records.
- `<run_id>_trial_summary.csv`: review-friendly trial table.
- `<run_id>_catalyst_calendar.csv`: derived catalyst calendar.
- `<run_id>_pipeline_assets.json`: normalized curated pipeline input.
- `<run_id>_asset_trial_matches.json`: deterministic asset-trial matches.
- `<run_id>_competitor_assets.json`: normalized curated competitor input.
- `<run_id>_competitive_matches.json`: deterministic competitive matches.
- `<run_id>_cash_runway.json`: financial snapshot and runway estimate, when
  financial input was provided.
- `<run_id>_valuation.json`: market valuation snapshot and derived context
  metrics, when valuation input was provided.
- `<run_id>_scorecard.json`: watchlist score, bucket, dimension scores, and
  monitoring rules.
- `<run_id>_extraction_audit.json`: per-asset review reasons from
  auto-extraction, when `--auto-inputs` runs.
- `<run_id>_llm_findings.json` under `data/memos/<slug>/`: structured LLM agent
  outputs (risks, evidence, step issues) when LLM agents run.
- `<run_id>_memo.json`: structured memo.
- `<run_id>_memo.md`: human-readable memo (includes an LLM addendum when LLM
  agents ran).

Two additional top-level directories are written only when relevant:

- `data/traces/`: JSONL LLM traces per run and optional rendered-prompt dumps.
- `data/cache/`: macro-signals disk cache keyed on market/provider.

Both are gitignored.

The Markdown memo includes a `Skeptical Review` section. This section is
generated from deterministic checks over current inputs, including trial
coverage, unmatched pipeline assets, competitor coverage, cash runway,
valuation context, and validation warnings.

## How To Read The CLI Summary

The `research` command prints a compact JSON summary:

- `decision`: current conservative classification.
- `trial_count`: deduplicated normalized trials.
- `pipeline_asset_count`: curated company assets supplied.
- `asset_trial_match_count`: deterministic matches to registry records.
- `competitor_asset_count`: curated competitor assets supplied.
- `competitive_match_count`: competitor matches to company assets.
- `cash_runway_months`: runway estimate if financial input was supplied.
- `enterprise_value`: enterprise value if valuation input was supplied.
- `revenue_multiple`: revenue multiple if revenue was supplied.
- `probability_weighted_target_price`: target price if assumptions were
  supplied.
- `implied_upside_downside_pct`: implied move versus the supplied share price.
- `watchlist_score`: deterministic 0-100 follow-up priority score.
- `watchlist_bucket`: score bucket for single-company triage.
- `input_warning_count`: total validation warnings attached to the run.
- `needs_human_review`: whether any finding asks for review.
- `artifacts`: file paths when saving is enabled.

## Rank Saved Runs

After running more than one company, rank saved runs into a local watchlist:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank
```

The command scans `data/processed/single_company`, loads each run manifest,
reads the saved scorecard artifact, and prints ranked JSON rows. Each row
includes:

- `rank`: rank after sorting by descending `watchlist_score`.
- `company`, `ticker`, `market`, `run_id`, and `retrieved_at`.
- `watchlist_score`, `watchlist_bucket`, and `needs_human_review`.
- `sizing_tier` and `research_position_limit_pct`: conservative research-only
  position guardrails, not trading instructions.
- Trial, pipeline, competitor, match, catalyst, and input-warning counts.
- Optional `cash_runway_months`, `enterprise_value`, and `revenue_multiple`.
- `company_concentration_count` and `market_concentration_count`.
- `target_concentration_count` and `indication_concentration_count`, derived
  from saved pipeline asset targets and indications.
- `guardrail_flags`: reasons the position guardrail was capped, such as
  missing competitor input, short runway, high valuation multiple, or target
  concentration.
- `monitoring_rules`, `memo_markdown`, and `manifest_json`.

Write a reusable CSV table:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank \
  --format csv \
  --output data/processed/watchlist_rank.csv
```

Use `--processed-dir` when research artifacts were written somewhere other
than the default `data/processed/single_company` directory.

When a company has multiple historical runs, keep only the newest run per
company or ticker:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank --latest-only
```

The JSON output includes both `loaded_entry_count` and `entry_count`, so it is
clear how many historical runs were collapsed.

## Catalyst Change Alerts

After repeating research for the same company, compare the newest two saved
catalyst calendars:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli catalyst-alerts
```

The command scans `data/processed/single_company`, groups runs by company or
ticker, compares the latest two runs for each group, and reports:

- `added`: a catalyst appears in the newest run only.
- `removed`: a catalyst appeared in the previous run but not the newest run.
- `date_changed`: the catalyst's expected date changed.
- `window_changed`: the catalyst's expected window changed.
- `timing_changed`: both expected date and expected window changed.

Write CSV output:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli catalyst-alerts \
  --format csv \
  --output data/processed/catalyst_alerts.csv
```

## Target Price Workflow

The CLI can create, validate, and calculate catalyst-adjusted target-price
assumption files. Run the standalone event-impact command with a reviewed
assumption file:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli event-impact \
  --company "Akeso" \
  --assumptions data/input/akeso_target_price_assumptions.json
```

This writes:

- `data/processed/target_price/<company>/event_impact.json`
- `data/processed/target_price/<company>/target_price_scenarios.json`
- `data/processed/target_price/<company>/target_price_summary.csv`

The outputs include:

- Bear, base, bull, and probability-weighted target price ranges.
- Asset rNPV by scenario.
- Catalyst-driven valuation delta.
- Missing assumptions and human-review flags.
- Sensitivity to probability of success, peak sales, and discount rate.

These outputs should be used as research guidance only, not trading
instructions.

## Technical Feature Payload

The standalone `technical-timing` command converts OHLCV CSV files into the
deterministic market feature payload used by future Stage B market agents:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli technical-timing \
  --ohlcv data/input/09606_hk_ohlcv.csv \
  --symbol 09606.HK \
  --benchmark-ohlcv data/input/hsi_ohlcv.csv \
  --benchmark-symbol ^HSI
```

The payload is research-only and source-backed. It includes 1m/3m/6m/12m
returns, drawdown from 52-week high, volume trend, moving-average state,
volatility state, relative strength versus benchmark, warnings, and provider
metadata. Provider failures should be handled before this layer; this command
only computes features from rows it is given.

For code paths that already installed the optional `market` extra,
`biotech_alpha.yfinance_provider` can fetch yfinance history and feed the same
technical-feature layer. It is intentionally not wired into the default report
path yet; failures return `None` rather than aborting the report.

The opt-in report path is:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli company-report \
  --ticker 09606.HK \
  --auto-inputs \
  --llm-agents macro-context market-regime-timing market-expectations \
  --macro-signals yahoo-hk \
  --technical-features yfinance \
  --technical-benchmark-symbol ^HSI
```

The technical provider is only consulted when `market-regime-timing` or
`market-expectations` is requested. Quick `report` still does not fetch
yfinance history by default.

## Troubleshooting

If ClinicalTrials.gov calls fail:

- Run `clinical-trials-version` to separate network/API issues from research
  pipeline issues.
- Retry with a smaller `--limit`.
- Use `--no-save` while debugging.

If research returns no trials:

- Add pipeline assets with aliases and drug codes.
- Try a more specific `--search-term`.
- Remember that China-only trials may not appear in ClinicalTrials.gov.

If `needs_human_review` is `true`:

- Check the memo `Key Risks` section.
- Check `input_warning_count`.
- Open the manifest and inspect `input_validation`.
- Missing curated inputs intentionally trigger the `data_quality_agent`.
- The `scientific_skeptic_agent` is expected to flag counter-thesis points even
  when the run otherwise succeeds.

If validation warns about placeholders:

- Replace `Example ...` values.
- Replace `YYYY-MM-DD`.
- Replace template source filenames with actual source paths or URLs.

## Current Limits

- Pipeline, financial, competitor, valuation, and target-price assumption
  inputs are curated JSON files with optional auto-drafted fallbacks under
  `data/input/generated/`.
- Target-price output is a deterministic first-pass rNPV model. It does not
  yet include launch curves, patent cliffs, geography splits, or calibrated
  historical event-reaction backtests.
- Automatic PDF/report extraction is first-pass only (HKEX annual results).
  Broader document ingestion across interim reports, prospectuses, and
  investor presentations is pending.
- China drug trial registry ingestion is first-pass (deterministic feed +
  state tracker). Full CDE schema mirror is not implemented.
- Competitive matching is deterministic on target + indication, with a
  review-gated ClinicalTrials.gov discovery runner.
- Cash runway is a first-pass estimate, not scenario modeling.
- Valuation narrative currently comes from the Sprint 6 valuation pod
  (commercial / pipeline-rNPV / balance-sheet / committee). The next
  calibration task is to prevent conservative rNPV from being treated as the
  only fair-value anchor for pre-revenue biotech.
- `report-quality-agent` is wired in the LLM path, while the deterministic
  `--no-llm` path still uses the rule-based `quality_gate`.
- `scientific-skeptic` and `investment-thesis` agents produce LLM-backed
  counter-thesis and thesis summaries, but they do not yet evaluate trial
  design, endpoints, efficacy, or safety from source documents directly.
- No LLM `strategic-economics-agent`, `catalyst-agent`,
  `market-expectations-agent`, or `data-collector-agent` yet; tracked as
  Stage B / Stage C in `docs/ROADMAP.md`. `market-regime-timing` exists as an
  opt-in scaffold, but is not quick-report default yet.
