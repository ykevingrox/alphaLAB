# Input Files

This directory is for curated single-company inputs that are not downloaded
automatically yet.

The high-level `company-report` command scans this directory for matching files
by company name, ticker, aliases, and expected suffixes:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli company-report \
  --company "Akeso" \
  --ticker "9926.HK"
```

If a matching file is missing, the run still completes and writes a
`missing_inputs_report.json` with suggested paths.

Generate starter files with:

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

Validate before running research:

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

Then run:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli research \
  --company "Akeso" \
  --ticker "9926.HK" \
  --pipeline-assets data/input/akeso_pipeline_assets.json \
  --financials data/input/akeso_financials.json \
  --competitors data/input/akeso_competitors.json \
  --valuation data/input/akeso_valuation.json \
  --target-price-assumptions data/input/akeso_target_price_assumptions.json
```

After several companies have saved runs, rank the local watchlist with:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank
```

After rerunning research for the same company, check catalyst calendar changes:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli catalyst-alerts
```

You can also calculate target-price scenarios directly from the curated
assumption file:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli event-impact \
  --company "Akeso" \
  --assumptions data/input/akeso_target_price_assumptions.json
```

For the model design, see:

```text
docs/TARGET_PRICE_MODEL.md
```

Keep source filenames or URLs in each evidence entry so generated memos remain
auditable.
