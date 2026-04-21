# Catalyst-Adjusted Target Price Model

## Purpose

The target-price layer should convert catalyst changes into research-grade
valuation ranges. It should not output a single precise price or pretend to
forecast short-term trading moves.

The intended output is:

```text
catalyst event -> asset assumption change -> rNPV delta
               -> equity value range -> per-share target range
```

## Safety Boundary

This module is decision support only.

- It does not place trades.
- It does not produce automatic buy or sell instructions.
- It must show assumptions and confidence before showing price outputs.
- It should prefer ranges and scenarios over a single point estimate.
- It should flag human review when key assumptions are missing or stale.

## Core Outputs

The module should produce:

- `bear_target_price`
- `base_target_price`
- `bull_target_price`
- `probability_weighted_target_price`
- `implied_upside_downside_pct`
- `event_value_delta`
- `asset_value_delta`
- `key_drivers`
- `sensitivity_points`
- `missing_assumptions`
- `needs_human_review`

## Valuation Structure

Company equity value should be decomposed as:

```text
equity value =
  cash and equivalents
+ commercial business value
+ sum(pipeline asset rNPV)
+ platform or optionality value
- debt
- expected dilution
```

Then:

```text
target price = equity value / shares outstanding
```

For pre-profit biotech companies, the pipeline rNPV block will often dominate
the target-price range. For revenue-stage companies, revenue multiple context
can be used as a cross-check, not as the only valuation method.

The current deterministic implementation keeps commercial business value and
platform optionality at zero until explicit curated inputs are added. It uses
net cash plus pipeline rNPV, then divides by diluted shares after the supplied
`expected_dilution_pct`.

## Asset rNPV

A first-pass asset rNPV can be approximated with:

```text
asset rNPV =
  peak sales
* probability of success
* economics share
* operating margin
* present value factor
```

The first implementation should keep the formula transparent and deterministic.
Later versions can add launch curves, patent cliffs, geography splits, and
line-of-therapy segmentation.

## Catalyst Event Impact

Catalyst events usually change one or more assumptions:

- Probability of success
- Launch timing
- Peak sales
- Market share
- Competitive intensity
- Economics share or royalty rate
- Dilution risk
- Discount rate

Event examples:

- Positive clinical readout: increase probability of success and possibly peak
  sales.
- Negative clinical readout: reduce probability of success or set asset value
  to zero.
- Delayed readout: move launch timing later and increase uncertainty.
- Regulatory approval: move probability of success toward commercial-stage
  assumptions.
- Regulatory rejection: reduce probability of success and delay timing.
- Business development deal: update economics share, cash, and validation
  signal.
- Financing: update cash, share count, and dilution assumptions.
- Competitor positive data: lower market share or peak sales assumptions.

## Current Input Contract

The first curated input file is
`data/input/<company>_target_price_assumptions.json`.

Suggested shape:

```json
{
  "as_of_date": "2026-04-21",
  "currency": "HKD",
  "share_price": 12.4,
  "shares_outstanding": 1000000000,
  "cash_and_equivalents": 1200000000,
  "total_debt": 300000000,
  "expected_dilution_pct": 0.0,
  "assets": [
    {
      "name": "Example Drug",
      "indication": "NSCLC",
      "phase": "Phase 2",
      "peak_sales": 3000000000,
      "probability_of_success": 0.35,
      "economics_share": 1.0,
      "operating_margin": 0.35,
      "launch_year": 2030,
      "discount_rate": 0.12,
      "source": "company-model.xlsx",
      "source_date": "2026-04-21"
    }
  ],
  "event_impacts": [
    {
      "event_type": "positive_readout",
      "asset_name": "Example Drug",
      "probability_of_success_delta": 0.15,
      "peak_sales_delta_pct": 0.1,
      "launch_year_delta": 0
    }
  ]
}
```

## Current CLI

The implemented template, validation, and event-impact commands are:

```bash
PYTHONPATH=src python3 -m biotech_alpha.cli target-price-template \
  --company "Akeso" \
  --ticker "9926.HK" \
  --output data/input/akeso_target_price_assumptions.json

PYTHONPATH=src python3 -m biotech_alpha.cli target-price-validate \
  data/input/akeso_target_price_assumptions.json

PYTHONPATH=src python3 -m biotech_alpha.cli event-impact \
  --company "Akeso" \
  --assumptions data/input/akeso_target_price_assumptions.json
```

The full research command can also include the same assumption file:

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

The standalone command writes:

- `event_impact.json`
- `target_price_scenarios.json`
- `target_price_summary.csv`

## Implementation Plan

1. Add curated target-price assumptions template and validator. Implemented.
2. Add transparent asset rNPV calculation. Implemented.
3. Add event-impact assumption deltas for catalyst types. Implemented.
4. Add target-price scenario output with bear, base, and bull cases.
   Implemented.
5. Add sensitivity points for probability of success, peak sales, and discount
   rate. Implemented as first-pass text.
6. Add memo section: `Catalyst-Adjusted Valuation`. Implemented.
7. Add tests for missing assumptions, negative values, and scenario math.
   Implemented.
8. Add backtest hooks later to compare historical catalyst events against
   price reactions without look-ahead bias.
