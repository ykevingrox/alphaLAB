# Runbook

This runbook explains how to operate the current CLI research workflow. The
README gives the project overview; this file is the step-by-step operating
guide.

## Prerequisites

- Python 3.11 or newer.
- Network access for ClinicalTrials.gov calls.
- Commands are run from the repository root.

The package currently has no third-party runtime dependencies.

## Sanity Checks

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```

Check the CLI surface:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli --help
PYTHONPATH=src python3 -m biotech_alpha.cli research --help
PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank --help
PYTHONPATH=src python3 -m biotech_alpha.cli catalyst-alerts --help
PYTHONPATH=src python3 -m biotech_alpha.cli target-price-template --help
PYTHONPATH=src python3 -m biotech_alpha.cli target-price-validate --help
```

Check ClinicalTrials.gov access:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli clinical-trials-version
```

## Minimal Research Smoke Test

This runs only the company-level ClinicalTrials.gov search and does not write
artifacts:

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
  --target-price-assumptions data/input/akeso_target_price_assumptions.json \
  --limit 20
```

Useful options:

- `--search-term`: override the company-level ClinicalTrials.gov search term.
- `--no-asset-queries`: search only by company/search term, not asset aliases.
- `--max-asset-query-terms`: cap extra asset-name and alias searches.
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
- `<run_id>_memo.json`: structured memo.
- `<run_id>_memo.md`: human-readable memo.

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

- Pipeline, financial, competitor, valuation, and target-price assumption inputs
  are curated JSON files.
- Target-price output is a deterministic first-pass rNPV model. It does not yet
  include launch curves, patent cliffs, geography splits, or calibrated
  historical event-reaction backtests.
- Automatic PDF/report extraction is not implemented yet.
- China drug trial registry ingestion is not implemented yet.
- Competitive matching is deterministic and coarse: target and indication only.
- Cash runway is a first-pass estimate, not scenario modeling.
- The memo is deterministic and conservative; a full LLM investment committee is
  still pending.
- The skeptical review is deterministic and checklist-based; it does not yet
  evaluate trial design, endpoints, efficacy, or safety from source documents.
