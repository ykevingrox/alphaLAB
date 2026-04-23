"""Target-price assumptions for catalyst-adjusted rNPV scenarios."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any

from biotech_alpha.models import AgentFinding


@dataclass(frozen=True)
class TargetPriceAssetAssumption:
    """Asset-level inputs for a first-pass rNPV model."""

    name: str
    indication: str | None
    phase: str | None
    peak_sales: float
    probability_of_success: float
    economics_share: float
    operating_margin: float
    launch_year: int
    discount_rate: float
    source: str | None = None
    source_date: str | None = None


@dataclass(frozen=True)
class EventImpactAssumption:
    """Assumption deltas associated with a catalyst event type."""

    event_type: str
    asset_name: str
    probability_of_success_delta: float = 0.0
    peak_sales_delta_pct: float = 0.0
    launch_year_delta: int = 0
    discount_rate_delta: float = 0.0
    rationale: str | None = None


@dataclass(frozen=True)
class TargetPriceAssumptions:
    """Company-level inputs for future target-price scenario calculations."""

    as_of_date: str
    currency: str
    share_price: float
    shares_outstanding: float
    cash_and_equivalents: float
    total_debt: float
    expected_dilution_pct: float
    assets: tuple[TargetPriceAssetAssumption, ...]
    event_impacts: tuple[EventImpactAssumption, ...] = ()


@dataclass(frozen=True)
class TargetPriceValidationReport:
    """Validation result for target-price assumptions."""

    has_assumptions: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    asset_count: int = 0
    event_impact_count: int = 0
    current_equity_value: float | None = None


@dataclass(frozen=True)
class AssetRnpv:
    """One asset rNPV calculation within a target-price scenario."""

    asset_name: str
    scenario: str
    peak_sales: float
    probability_of_success: float
    economics_share: float
    operating_margin: float
    launch_year: int
    discount_rate: float
    years_to_launch: int
    present_value_factor: float
    rnpv: float


@dataclass(frozen=True)
class TargetPriceScenario:
    """One target-price scenario."""

    name: str
    currency: str
    pipeline_rnpv: float
    net_cash: float
    equity_value: float
    target_price: float
    asset_rnpv: tuple[AssetRnpv, ...]


@dataclass(frozen=True)
class TargetPriceAnalysis:
    """Catalyst-adjusted target-price range analysis."""

    as_of_date: str
    currency: str
    current_share_price: float
    shares_outstanding: float
    diluted_shares: float
    current_equity_value: float
    pre_event_equity_value: float
    event_value_delta: float
    asset_value_delta: float
    bear: TargetPriceScenario
    base: TargetPriceScenario
    bull: TargetPriceScenario
    probability_weighted_target_price: float
    implied_upside_downside_pct: float
    key_drivers: tuple[str, ...]
    sensitivity_points: tuple[str, ...]
    missing_assumptions: tuple[str, ...]
    needs_human_review: bool


TARGET_PRICE_SUMMARY_CSV_FIELDS = (
    "scenario",
    "currency",
    "pipeline_rnpv",
    "net_cash",
    "equity_value",
    "target_price",
    "probability_weighted_target_price",
    "implied_upside_downside_pct",
)

_PHASE_POS_DEFAULTS: tuple[tuple[tuple[str, ...], float], ...] = (
    (("bla under review", "bla accepted"), 0.85),
    (("bla planned",), 0.7),
    (("phase 3", "phase iii"), 0.55),
    (("phase 2", "phase ii"), 0.3),
    (("phase 1", "phase i"), 0.12),
    (("ind approved", "ind accepted"), 0.08),
    (("ind-enabling",), 0.04),
    (("pcc nomination",), 0.02),
    (("preclinical",), 0.01),
)

_INDICATION_PEAK_SALES_DEFAULTS: tuple[tuple[tuple[str, ...], float], ...] = (
    (("nsclc", "non-small cell lung"), 8_000_000_000.0),
    (("sclc",), 2_500_000_000.0),
    (("ep-nec", "neuroendocrine"), 1_200_000_000.0),
    (("multiple myeloma", "mm"), 4_000_000_000.0),
    (("systemic lupus erythematosus", "sle"), 3_000_000_000.0),
    (("atopic dermatitis",), 3_500_000_000.0),
    (("asthma",), 2_500_000_000.0),
    (("solid tumor",), 3_000_000_000.0),
    (("breast cancer",), 4_000_000_000.0),
)

_PHASE_LAUNCH_YEAR_BUFFER: tuple[tuple[tuple[str, ...], int], ...] = (
    (("bla under review", "bla accepted"), 1),
    (("bla planned",), 2),
    (("phase 3", "phase iii"), 3),
    (("phase 2", "phase ii"), 5),
    (("phase 1", "phase i"), 7),
    (("ind approved", "ind accepted"), 8),
    (("ind-enabling",), 9),
    (("pcc nomination",), 10),
    (("preclinical",), 11),
)


def target_price_assumptions_template(
    company: str,
    ticker: str | None = None,
) -> dict[str, Any]:
    """Return a starter template for catalyst-adjusted target-price inputs."""

    company = company.strip()
    if not company:
        raise ValueError("company must not be empty")
    return {
        "company": company,
        "ticker": ticker,
        "as_of_date": "YYYY-MM-DD",
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
                "source_date": "YYYY-MM-DD",
            }
        ],
        "event_impacts": [
            {
                "event_type": "positive_readout",
                "asset_name": "Example Drug",
                "probability_of_success_delta": 0.15,
                "peak_sales_delta_pct": 0.1,
                "launch_year_delta": 0,
                "discount_rate_delta": 0.0,
                "rationale": "Update after source-backed catalyst review.",
            }
        ],
    }


def draft_target_price_assumptions(
    *,
    company: str,
    ticker: str | None,
    pipeline_assets_payload: dict[str, Any],
    financial_snapshot_payload: dict[str, Any] | None = None,
    valuation_snapshot_payload: dict[str, Any] | None = None,
    source: str | None = None,
    source_date: str | None = None,
) -> dict[str, Any]:
    """Draft first-pass target-price assumptions from generated inputs."""

    valuation_payload = (
        valuation_snapshot_payload if isinstance(valuation_snapshot_payload, dict) else {}
    )
    financial_payload = (
        financial_snapshot_payload if isinstance(financial_snapshot_payload, dict) else {}
    )
    as_of_date = _first_non_empty_str(
        valuation_payload.get("as_of_date"),
        financial_payload.get("as_of_date"),
        source_date,
    ) or date.today().isoformat()
    currency = _first_non_empty_str(
        valuation_payload.get("currency"),
        financial_payload.get("currency"),
    ) or "HKD"
    share_price = _positive_number_or_none(valuation_payload.get("share_price"))
    shares_outstanding = _positive_number_or_none(
        valuation_payload.get("shares_outstanding")
    )
    market_cap = _positive_number_or_none(valuation_payload.get("market_cap"))
    if share_price is None and shares_outstanding is not None and market_cap is not None:
        share_price = market_cap / shares_outstanding
    if shares_outstanding is None and share_price is not None and market_cap is not None:
        shares_outstanding = market_cap / share_price
    if share_price is None:
        share_price = 1.0
    if shares_outstanding is None:
        shares_outstanding = 1.0

    cash = _non_negative_number_or_default(
        valuation_payload.get("cash_and_equivalents"),
        _non_negative_number_or_default(
            financial_payload.get("cash_and_equivalents"),
            0.0,
        ),
    )
    debt = _non_negative_number_or_default(
        valuation_payload.get("total_debt"),
        _non_negative_number_or_default(
            financial_payload.get("short_term_debt"),
            0.0,
        ),
    )
    as_of_year = _current_year(as_of_date)
    assets_payload = pipeline_assets_payload.get("assets")
    rows = assets_payload if isinstance(assets_payload, list) else []
    drafted_assets = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        phase = _optional_str(row.get("phase"))
        indication = _optional_str(row.get("indication"))
        evidence_source = source
        evidence_date = source_date
        evidence = row.get("evidence")
        if isinstance(evidence, list) and evidence:
            first = evidence[0]
            if isinstance(first, dict):
                evidence_source = _first_non_empty_str(first.get("source"), evidence_source)
                evidence_date = _first_non_empty_str(
                    first.get("source_date"),
                    evidence_date,
                )
        drafted_assets.append(
            {
                "name": name,
                "indication": indication,
                "phase": phase,
                "peak_sales": _peak_sales_from_indication(indication),
                "probability_of_success": _pos_from_phase(phase),
                "economics_share": _economics_share_from_row(row),
                "operating_margin": 0.35,
                "launch_year": _launch_year_from_phase(phase, as_of_year=as_of_year),
                "discount_rate": 0.12,
                "source": evidence_source or source or "generated_pipeline_assets",
                "source_date": evidence_date or source_date or as_of_date,
            }
        )
    if not drafted_assets:
        drafted_assets = [
            {
                "name": "Example Drug",
                "indication": "solid tumors",
                "phase": "preclinical",
                "peak_sales": 1_500_000_000.0,
                "probability_of_success": 0.01,
                "economics_share": 1.0,
                "operating_margin": 0.35,
                "launch_year": as_of_year + 10,
                "discount_rate": 0.12,
                "source": source or "generated_pipeline_assets",
                "source_date": source_date or as_of_date,
            }
        ]

    return {
        "company": company,
        "ticker": ticker,
        "as_of_date": as_of_date,
        "currency": currency,
        "share_price": round(share_price, 6),
        "shares_outstanding": round(shares_outstanding, 4),
        "cash_and_equivalents": round(cash, 2),
        "total_debt": round(debt, 2),
        "expected_dilution_pct": 0.0,
        "assets": drafted_assets,
        "event_impacts": [],
        "generated_by": "auto_inputs.default_rnpv",
        "inferred_by": "default_rnpv_v1",
        "needs_human_review": True,
    }


def write_target_price_assumptions_template(
    *,
    path: str | Path,
    company: str,
    ticker: str | None = None,
    overwrite: bool = False,
) -> Path:
    """Write a target-price assumptions template to disk."""

    output_path = Path(path)
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite existing file: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            target_price_assumptions_template(company=company, ticker=ticker),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path


def load_target_price_assumptions(path: str | Path) -> TargetPriceAssumptions:
    """Load target-price assumptions from JSON."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("target-price assumptions must be a JSON object")
    return target_price_assumptions_from_dict(payload)


def validate_target_price_assumptions_file(
    path: str | Path,
) -> TargetPriceValidationReport:
    """Validate target-price assumptions."""

    try:
        assumptions = load_target_price_assumptions(path)
    except Exception as exc:  # noqa: BLE001 - return validation errors.
        return TargetPriceValidationReport(
            has_assumptions=False,
            errors=(str(exc),),
        )

    warnings = [
        *_placeholder_warnings(assumptions),
        *_coverage_warnings(assumptions),
    ]
    current_equity_value = (
        assumptions.share_price
        * assumptions.shares_outstanding
        * (1 + assumptions.expected_dilution_pct)
    )
    return TargetPriceValidationReport(
        has_assumptions=True,
        warnings=tuple(warnings),
        asset_count=len(assumptions.assets),
        event_impact_count=len(assumptions.event_impacts),
        current_equity_value=current_equity_value,
    )


def build_target_price_analysis(
    assumptions: TargetPriceAssumptions,
) -> TargetPriceAnalysis:
    """Build transparent catalyst-adjusted target-price scenarios."""

    current_year = _current_year(assumptions.as_of_date)
    baseline_assets = assumptions.assets
    adjusted_assets = tuple(
        _apply_event_impacts(asset, assumptions.event_impacts)
        for asset in assumptions.assets
    )
    net_cash = assumptions.cash_and_equivalents - assumptions.total_debt
    diluted_shares = assumptions.shares_outstanding * (
        1 + assumptions.expected_dilution_pct
    )
    current_equity_value = assumptions.share_price * diluted_shares
    pre_event_scenario = _build_scenario(
        name="pre_event_base",
        currency=assumptions.currency,
        assets=baseline_assets,
        net_cash=net_cash,
        diluted_shares=diluted_shares,
        current_year=current_year,
    )
    bear = _build_scenario(
        name="bear",
        currency=assumptions.currency,
        assets=tuple(_scenario_asset(asset, "bear") for asset in adjusted_assets),
        net_cash=net_cash,
        diluted_shares=diluted_shares,
        current_year=current_year,
    )
    base = _build_scenario(
        name="base",
        currency=assumptions.currency,
        assets=adjusted_assets,
        net_cash=net_cash,
        diluted_shares=diluted_shares,
        current_year=current_year,
    )
    bull = _build_scenario(
        name="bull",
        currency=assumptions.currency,
        assets=tuple(_scenario_asset(asset, "bull") for asset in adjusted_assets),
        net_cash=net_cash,
        diluted_shares=diluted_shares,
        current_year=current_year,
    )
    probability_weighted_target_price = round(
        bear.target_price * 0.25 + base.target_price * 0.5 + bull.target_price * 0.25,
        4,
    )
    implied_upside_downside_pct = round(
        (probability_weighted_target_price / assumptions.share_price - 1) * 100,
        2,
    )
    event_value_delta = base.equity_value - pre_event_scenario.equity_value
    asset_value_delta = base.pipeline_rnpv - pre_event_scenario.pipeline_rnpv
    missing_assumptions = _missing_assumptions(assumptions)
    return TargetPriceAnalysis(
        as_of_date=assumptions.as_of_date,
        currency=assumptions.currency,
        current_share_price=assumptions.share_price,
        shares_outstanding=assumptions.shares_outstanding,
        diluted_shares=diluted_shares,
        current_equity_value=current_equity_value,
        pre_event_equity_value=pre_event_scenario.equity_value,
        event_value_delta=event_value_delta,
        asset_value_delta=asset_value_delta,
        bear=bear,
        base=base,
        bull=bull,
        probability_weighted_target_price=probability_weighted_target_price,
        implied_upside_downside_pct=implied_upside_downside_pct,
        key_drivers=_key_drivers(assumptions),
        sensitivity_points=_sensitivity_points(base),
        missing_assumptions=missing_assumptions,
        needs_human_review=bool(
            missing_assumptions
            or validate_target_price_assumptions(assumptions).warnings
        ),
    )


def validate_target_price_assumptions(
    assumptions: TargetPriceAssumptions,
) -> TargetPriceValidationReport:
    """Validate already-loaded target-price assumptions."""

    warnings = [
        *_placeholder_warnings(assumptions),
        *_coverage_warnings(assumptions),
    ]
    current_equity_value = (
        assumptions.share_price
        * assumptions.shares_outstanding
        * (1 + assumptions.expected_dilution_pct)
    )
    return TargetPriceValidationReport(
        has_assumptions=True,
        warnings=tuple(warnings),
        asset_count=len(assumptions.assets),
        event_impact_count=len(assumptions.event_impacts),
        current_equity_value=current_equity_value,
    )


def target_price_payload(
    assumptions: TargetPriceAssumptions,
    analysis: TargetPriceAnalysis,
) -> dict[str, Any]:
    """Return a JSON-serializable target-price scenario payload."""

    return {
        "assumptions": asdict(assumptions),
        "analysis": asdict(analysis),
    }


def event_impact_payload(
    assumptions: TargetPriceAssumptions,
    analysis: TargetPriceAnalysis,
) -> dict[str, Any]:
    """Return the event-impact delta summary."""

    return {
        "as_of_date": analysis.as_of_date,
        "currency": analysis.currency,
        "event_impacts": [asdict(impact) for impact in assumptions.event_impacts],
        "pre_event_equity_value": analysis.pre_event_equity_value,
        "post_event_base_equity_value": analysis.base.equity_value,
        "event_value_delta": analysis.event_value_delta,
        "asset_value_delta": analysis.asset_value_delta,
        "key_drivers": analysis.key_drivers,
        "needs_human_review": analysis.needs_human_review,
    }


def target_price_summary(
    analysis: TargetPriceAnalysis,
) -> dict[str, Any]:
    """Return a compact JSON-serializable target-price summary."""

    return {
        "as_of_date": analysis.as_of_date,
        "currency": analysis.currency,
        "current_share_price": analysis.current_share_price,
        "bear_target_price": analysis.bear.target_price,
        "base_target_price": analysis.base.target_price,
        "bull_target_price": analysis.bull.target_price,
        "probability_weighted_target_price": (
            analysis.probability_weighted_target_price
        ),
        "implied_upside_downside_pct": analysis.implied_upside_downside_pct,
        "event_value_delta": analysis.event_value_delta,
        "asset_value_delta": analysis.asset_value_delta,
        "needs_human_review": analysis.needs_human_review,
    }


def target_price_summary_rows(
    analysis: TargetPriceAnalysis,
) -> list[dict[str, Any]]:
    """Return rows for target-price scenario CSV output."""

    rows = []
    for scenario in (analysis.bear, analysis.base, analysis.bull):
        rows.append(
            {
                "scenario": scenario.name,
                "currency": scenario.currency,
                "pipeline_rnpv": scenario.pipeline_rnpv,
                "net_cash": scenario.net_cash,
                "equity_value": scenario.equity_value,
                "target_price": scenario.target_price,
                "probability_weighted_target_price": (
                    analysis.probability_weighted_target_price
                ),
                "implied_upside_downside_pct": (
                    analysis.implied_upside_downside_pct
                ),
            }
        )
    return rows


def write_target_price_summary_csv(
    path: str | Path,
    analysis: TargetPriceAnalysis,
) -> Path:
    """Write target-price scenario summary rows to CSV."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as file:
        _write_target_price_summary_csv(file, analysis)
    return output_path


def target_price_summary_csv_text(analysis: TargetPriceAnalysis) -> str:
    """Return target-price scenario summary rows as CSV text."""

    output = StringIO()
    _write_target_price_summary_csv(output, analysis)
    return output.getvalue()


def write_target_price_artifacts(
    *,
    output_dir: str | Path,
    company: str,
    assumptions: TargetPriceAssumptions,
    analysis: TargetPriceAnalysis,
) -> dict[str, Path]:
    """Write event-impact and target-price scenario artifacts."""

    output_path = Path(output_dir) / _slugify(company)
    output_path.mkdir(parents=True, exist_ok=True)
    event_impact_path = output_path / "event_impact.json"
    scenarios_path = output_path / "target_price_scenarios.json"
    summary_csv_path = output_path / "target_price_summary.csv"
    _write_json(event_impact_path, event_impact_payload(assumptions, analysis))
    _write_json(scenarios_path, target_price_payload(assumptions, analysis))
    write_target_price_summary_csv(summary_csv_path, analysis)
    return {
        "event_impact": event_impact_path,
        "target_price_scenarios": scenarios_path,
        "target_price_summary_csv": summary_csv_path,
    }


def target_price_finding(
    *,
    company: str,
    analysis: TargetPriceAnalysis,
) -> AgentFinding:
    """Convert target-price scenarios into a memo finding."""

    risks = tuple(analysis.missing_assumptions)
    return AgentFinding(
        agent_name="target_price_scenario_agent",
        summary=(
            f"{company} probability-weighted target price is "
            f"{analysis.probability_weighted_target_price:.2f} "
            f"{analysis.currency}, with bear/base/bull range "
            f"{analysis.bear.target_price:.2f}/"
            f"{analysis.base.target_price:.2f}/"
            f"{analysis.bull.target_price:.2f}."
        ),
        score=analysis.probability_weighted_target_price,
        risks=risks,
        confidence=0.35,
        needs_human_review=analysis.needs_human_review,
    )


def target_price_assumptions_from_dict(
    payload: dict[str, Any],
) -> TargetPriceAssumptions:
    """Build target-price assumptions from a dictionary."""

    assets_payload = payload.get("assets")
    if not isinstance(assets_payload, list) or not assets_payload:
        raise ValueError("target-price assumptions require a non-empty assets list")

    impacts_payload = payload.get("event_impacts", [])
    if impacts_payload is None:
        impacts_payload = []
    if not isinstance(impacts_payload, list):
        raise ValueError("event_impacts must be a list")

    assumptions = TargetPriceAssumptions(
        as_of_date=_required_str(payload, "as_of_date"),
        currency=_required_str(payload, "currency"),
        share_price=_required_positive_number(payload, "share_price"),
        shares_outstanding=_required_positive_number(
            payload,
            "shares_outstanding",
        ),
        cash_and_equivalents=_required_non_negative_number(
            payload,
            "cash_and_equivalents",
        ),
        total_debt=_required_non_negative_number(payload, "total_debt"),
        expected_dilution_pct=_ratio_value(payload.get("expected_dilution_pct", 0.0)),
        assets=tuple(
            _asset_assumption_from_dict(asset)
            for asset in assets_payload
            if isinstance(asset, dict)
        ),
        event_impacts=tuple(
            _event_impact_from_dict(impact)
            for impact in impacts_payload
            if isinstance(impact, dict)
        ),
    )
    if len(assumptions.assets) != len(assets_payload):
        raise ValueError("each asset assumption must be a JSON object")
    if len(assumptions.event_impacts) != len(impacts_payload):
        raise ValueError("each event impact must be a JSON object")
    return assumptions


def target_price_validation_report_as_dict(
    report: TargetPriceValidationReport,
) -> dict[str, Any]:
    """Convert target-price validation reports into JSON dictionaries."""

    return asdict(report)


def _write_target_price_summary_csv(
    file: Any,
    analysis: TargetPriceAnalysis,
) -> None:
    writer = csv.DictWriter(file, fieldnames=TARGET_PRICE_SUMMARY_CSV_FIELDS)
    writer.writeheader()
    for row in target_price_summary_rows(analysis):
        writer.writerow(row)


def _asset_assumption_from_dict(
    payload: dict[str, Any],
) -> TargetPriceAssetAssumption:
    return TargetPriceAssetAssumption(
        name=_required_str(payload, "name"),
        indication=_optional_str(payload.get("indication")),
        phase=_optional_str(payload.get("phase")),
        peak_sales=_required_positive_number(payload, "peak_sales"),
        probability_of_success=_ratio_value(
            payload.get("probability_of_success"),
        ),
        economics_share=_ratio_value(payload.get("economics_share")),
        operating_margin=_ratio_value(payload.get("operating_margin")),
        launch_year=_required_int(payload, "launch_year"),
        discount_rate=_ratio_value(payload.get("discount_rate")),
        source=_optional_str(payload.get("source")),
        source_date=_optional_str(payload.get("source_date")),
    )


def _event_impact_from_dict(payload: dict[str, Any]) -> EventImpactAssumption:
    return EventImpactAssumption(
        event_type=_required_str(payload, "event_type"),
        asset_name=_required_str(payload, "asset_name"),
        probability_of_success_delta=_delta_ratio_value(
            payload.get("probability_of_success_delta", 0.0),
        ),
        peak_sales_delta_pct=_delta_ratio_value(
            payload.get("peak_sales_delta_pct", 0.0),
        ),
        launch_year_delta=_optional_int(payload.get("launch_year_delta", 0)),
        discount_rate_delta=_delta_ratio_value(
            payload.get("discount_rate_delta", 0.0),
        ),
        rationale=_optional_str(payload.get("rationale")),
    )


def _coverage_warnings(
    assumptions: TargetPriceAssumptions,
) -> tuple[str, ...]:
    warnings: list[str] = []
    asset_names = {asset.name.casefold() for asset in assumptions.assets}
    for impact in assumptions.event_impacts:
        if impact.asset_name.casefold() not in asset_names:
            warnings.append(
                f"event impact references unknown asset: {impact.asset_name}"
            )
    for asset in assumptions.assets:
        if not asset.source:
            warnings.append(f"asset {asset.name} is missing source")
        if not asset.source_date:
            warnings.append(f"asset {asset.name} is missing source_date")
    return tuple(warnings)


def _build_scenario(
    *,
    name: str,
    currency: str,
    assets: tuple[TargetPriceAssetAssumption, ...],
    net_cash: float,
    diluted_shares: float,
    current_year: int,
) -> TargetPriceScenario:
    asset_rnpv = tuple(
        _asset_rnpv(
            asset=asset,
            scenario=name,
            current_year=current_year,
        )
        for asset in assets
    )
    pipeline_rnpv = sum(asset.rnpv for asset in asset_rnpv)
    equity_value = pipeline_rnpv + net_cash
    target_price = equity_value / diluted_shares
    return TargetPriceScenario(
        name=name,
        currency=currency,
        pipeline_rnpv=pipeline_rnpv,
        net_cash=net_cash,
        equity_value=equity_value,
        target_price=round(target_price, 4),
        asset_rnpv=asset_rnpv,
    )


def _asset_rnpv(
    *,
    asset: TargetPriceAssetAssumption,
    scenario: str,
    current_year: int,
) -> AssetRnpv:
    years_to_launch = max(asset.launch_year - current_year, 0)
    present_value_factor = 1 / ((1 + asset.discount_rate) ** years_to_launch)
    rnpv = (
        asset.peak_sales
        * asset.probability_of_success
        * asset.economics_share
        * asset.operating_margin
        * present_value_factor
    )
    return AssetRnpv(
        asset_name=asset.name,
        scenario=scenario,
        peak_sales=asset.peak_sales,
        probability_of_success=asset.probability_of_success,
        economics_share=asset.economics_share,
        operating_margin=asset.operating_margin,
        launch_year=asset.launch_year,
        discount_rate=asset.discount_rate,
        years_to_launch=years_to_launch,
        present_value_factor=present_value_factor,
        rnpv=rnpv,
    )


def _apply_event_impacts(
    asset: TargetPriceAssetAssumption,
    impacts: tuple[EventImpactAssumption, ...],
) -> TargetPriceAssetAssumption:
    updated = asset
    for impact in impacts:
        if impact.asset_name.casefold() != updated.name.casefold():
            continue
        updated = TargetPriceAssetAssumption(
            name=updated.name,
            indication=updated.indication,
            phase=updated.phase,
            peak_sales=max(updated.peak_sales * (1 + impact.peak_sales_delta_pct), 0),
            probability_of_success=_clamp_ratio(
                updated.probability_of_success
                + impact.probability_of_success_delta
            ),
            economics_share=updated.economics_share,
            operating_margin=updated.operating_margin,
            launch_year=max(updated.launch_year + impact.launch_year_delta, 1900),
            discount_rate=_clamp_ratio(
                updated.discount_rate + impact.discount_rate_delta
            ),
            source=updated.source,
            source_date=updated.source_date,
        )
    return updated


def _scenario_asset(
    asset: TargetPriceAssetAssumption,
    scenario: str,
) -> TargetPriceAssetAssumption:
    if scenario == "bear":
        return TargetPriceAssetAssumption(
            name=asset.name,
            indication=asset.indication,
            phase=asset.phase,
            peak_sales=asset.peak_sales * 0.75,
            probability_of_success=_clamp_ratio(asset.probability_of_success - 0.1),
            economics_share=asset.economics_share,
            operating_margin=_clamp_ratio(asset.operating_margin - 0.05),
            launch_year=asset.launch_year + 1,
            discount_rate=_clamp_ratio(asset.discount_rate + 0.02),
            source=asset.source,
            source_date=asset.source_date,
        )
    if scenario == "bull":
        return TargetPriceAssetAssumption(
            name=asset.name,
            indication=asset.indication,
            phase=asset.phase,
            peak_sales=asset.peak_sales * 1.25,
            probability_of_success=_clamp_ratio(asset.probability_of_success + 0.1),
            economics_share=asset.economics_share,
            operating_margin=_clamp_ratio(asset.operating_margin + 0.05),
            launch_year=max(asset.launch_year - 1, 1900),
            discount_rate=_clamp_ratio(asset.discount_rate - 0.02),
            source=asset.source,
            source_date=asset.source_date,
        )
    return asset


def _key_drivers(assumptions: TargetPriceAssumptions) -> tuple[str, ...]:
    if not assumptions.event_impacts:
        return ("No event impact assumptions supplied.",)
    drivers = []
    for impact in assumptions.event_impacts:
        drivers.append(
            f"{impact.asset_name} {impact.event_type}: "
            f"PoS {impact.probability_of_success_delta:+.2f}, "
            f"peak sales {impact.peak_sales_delta_pct:+.1%}, "
            f"launch year {impact.launch_year_delta:+d}, "
            f"discount rate {impact.discount_rate_delta:+.2f}"
        )
    return tuple(drivers)


def _sensitivity_points(
    base: TargetPriceScenario,
) -> tuple[str, ...]:
    if not base.asset_rnpv:
        return ()
    largest_asset = max(base.asset_rnpv, key=lambda item: item.rnpv)
    return (
        (
            f"Largest asset sensitivity: {largest_asset.asset_name} contributes "
            f"{largest_asset.rnpv:.0f} {base.currency} base rNPV."
        ),
        "Review probability of success, peak sales, and discount rate first.",
    )


def _missing_assumptions(
    assumptions: TargetPriceAssumptions,
) -> tuple[str, ...]:
    missing: list[str] = []
    if not assumptions.event_impacts:
        missing.append("no event impact assumptions supplied")
    for asset in assumptions.assets:
        if not asset.source:
            missing.append(f"{asset.name} missing source")
        if not asset.source_date:
            missing.append(f"{asset.name} missing source_date")
    return tuple(missing)


def _current_year(as_of_date: str) -> int:
    try:
        return date.fromisoformat(as_of_date).year
    except ValueError:
        return date.today().year


def _clamp_ratio(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def _slugify(value: str) -> str:
    slug = "".join(
        character.lower() if character.isalnum() else "-"
        for character in value.strip()
    )
    return "-".join(part for part in slug.split("-") if part) or "company"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _placeholder_warnings(
    assumptions: TargetPriceAssumptions,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if assumptions.as_of_date == "YYYY-MM-DD":
        warnings.append("replace placeholder as_of_date")
    for asset in assumptions.assets:
        if asset.name.startswith("Example"):
            warnings.append(f"replace placeholder asset name: {asset.name}")
        if asset.source == "company-model.xlsx":
            warnings.append(f"replace placeholder source for asset: {asset.name}")
        if asset.source_date == "YYYY-MM-DD":
            warnings.append(f"replace placeholder source_date for asset: {asset.name}")
    return tuple(warnings)


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"target-price field {key!r} must be a non-empty string")
    return value.strip()


def _first_non_empty_str(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _positive_number_or_none(value: Any) -> float | None:
    number = _number_value(value)
    if number is None or number <= 0:
        return None
    return number


def _non_negative_number_or_default(value: Any, default: float) -> float:
    number = _number_value(value)
    if number is None or number < 0:
        return default
    return number


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in terms)


def _pos_from_phase(phase: str | None) -> float:
    text = (phase or "").casefold()
    for terms, value in _PHASE_POS_DEFAULTS:
        if _contains_any(text, terms):
            return value
    return 0.03


def _peak_sales_from_indication(indication: str | None) -> float:
    text = (indication or "").casefold()
    for terms, value in _INDICATION_PEAK_SALES_DEFAULTS:
        if _contains_any(text, terms):
            return value
    return 2_000_000_000.0


def _launch_year_from_phase(phase: str | None, *, as_of_year: int) -> int:
    text = (phase or "").casefold()
    for terms, buffer_years in _PHASE_LAUNCH_YEAR_BUFFER:
        if _contains_any(text, terms):
            return as_of_year + buffer_years
    return as_of_year + 9


def _economics_share_from_row(row: dict[str, Any]) -> float:
    partner = str(row.get("partner") or "").casefold()
    rights = str(row.get("rights") or "").casefold()
    evidence_text = ""
    evidence = row.get("evidence")
    if isinstance(evidence, list) and evidence:
        first = evidence[0]
        if isinstance(first, dict):
            evidence_text = str(first.get("claim") or "").casefold()
    licensing_markers = (
        "licensed",
        "out-licensed",
        "license agreement",
        "exclusive agreement",
        "rights",
        "collaboration",
    )
    if (
        _contains_any(partner, licensing_markers)
        or _contains_any(rights, licensing_markers)
        or _contains_any(evidence_text, licensing_markers)
    ):
        return 0.2
    return 1.0


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional target-price text fields must be strings")
    value = value.strip()
    return value or None


def _required_positive_number(payload: dict[str, Any], key: str) -> float:
    value = _number_value(payload.get(key))
    if value is None or value <= 0:
        raise ValueError(f"target-price field {key!r} must be positive")
    return value


def _required_non_negative_number(payload: dict[str, Any], key: str) -> float:
    value = _number_value(payload.get(key))
    if value is None or value < 0:
        raise ValueError(f"target-price field {key!r} must be non-negative")
    return value


def _number_value(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("target-price numeric fields must be numbers")
    return float(value)


def _ratio_value(value: Any) -> float:
    number = _number_value(value)
    if number is None or number < 0 or number > 1:
        raise ValueError("target-price ratio fields must be between 0 and 1")
    return number


def _delta_ratio_value(value: Any) -> float:
    number = _number_value(value)
    if number is None or number < -1 or number > 1:
        raise ValueError("target-price ratio deltas must be between -1 and 1")
    return number


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"target-price field {key!r} must be an integer")
    return value


def _optional_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("target-price integer fields must be integers")
    return value
