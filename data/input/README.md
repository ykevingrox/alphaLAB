# Input Files

This directory is for curated single-company inputs that are not downloaded
automatically yet.

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
  --valuation data/input/akeso_valuation.json
```

After several companies have saved runs, rank the local watchlist with:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli watchlist-rank
```

After rerunning research for the same company, check catalyst calendar changes:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli catalyst-alerts
```

Target-price assumption inputs are available for validation, but event-impact
modeling is still planned. For the design, see:

```text
docs/TARGET_PRICE_MODEL.md
```

Keep source filenames or URLs in each evidence entry so generated memos remain
auditable.
