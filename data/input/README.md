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
```

Validate before running research:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli pipeline-validate \
  data/input/akeso_pipeline_assets.json

PYTHONPATH=src python3 -m biotech_alpha.cli financial-validate \
  data/input/akeso_financials.json

PYTHONPATH=src python3 -m biotech_alpha.cli competitor-validate \
  data/input/akeso_competitors.json
```

Then run:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli research \
  --company "Akeso" \
  --ticker "9926.HK" \
  --pipeline-assets data/input/akeso_pipeline_assets.json \
  --financials data/input/akeso_financials.json \
  --competitors data/input/akeso_competitors.json
```

Keep source filenames or URLs in each evidence entry so generated memos remain
auditable.
