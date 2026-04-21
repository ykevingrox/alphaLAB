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
- `<run_id>_memo.json`: structured memo.
- `<run_id>_memo.md`: human-readable memo.

## How To Read The CLI Summary

The `research` command prints a compact JSON summary:

- `decision`: current conservative classification.
- `trial_count`: deduplicated normalized trials.
- `pipeline_asset_count`: curated company assets supplied.
- `asset_trial_match_count`: deterministic matches to registry records.
- `competitor_asset_count`: curated competitor assets supplied.
- `competitive_match_count`: competitor matches to company assets.
- `cash_runway_months`: runway estimate if financial input was supplied.
- `input_warning_count`: total validation warnings attached to the run.
- `needs_human_review`: whether any finding asks for review.
- `artifacts`: file paths when saving is enabled.

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

If validation warns about placeholders:

- Replace `Example ...` values.
- Replace `YYYY-MM-DD`.
- Replace template source filenames with actual source paths or URLs.

## Current Limits

- Pipeline, financial, and competitor inputs are curated JSON files.
- Automatic PDF/report extraction is not implemented yet.
- China drug trial registry ingestion is not implemented yet.
- Competitive matching is deterministic and coarse: target and indication only.
- Cash runway is a first-pass estimate, not scenario modeling.
- The memo is deterministic and conservative; a full LLM investment committee is
  still pending.
