"""Automatic source discovery and draft input generation."""

from __future__ import annotations

import io
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

from biotech_alpha.clinicaltrials import extract_trial_summaries
from biotech_alpha.company_report import CompanyIdentity
from biotech_alpha.competition import (
    competition_validation_report_as_dict,
    validate_competitor_file,
)
from biotech_alpha.conference import (
    conference_validation_report_as_dict,
    validate_conference_catalyst_file,
)
from biotech_alpha.financials import (
    financial_validation_report_as_dict,
    validate_financial_snapshot_file,
)
from biotech_alpha.market_data import (
    normalize_hk_market_data,
    valuation_snapshot_payload_from_market_data,
)
from biotech_alpha.pipeline import (
    validate_pipeline_asset_file,
    validation_report_as_dict,
)
from biotech_alpha.valuation import (
    valuation_validation_report_as_dict,
    validate_valuation_snapshot_file,
)
from biotech_alpha.target_price import (
    draft_target_price_assumptions,
    target_price_validation_report_as_dict,
    validate_target_price_assumptions_file,
)


MarketDataProvider = Callable[[CompanyIdentity], dict[str, Any] | None]


class ClinicalTrialsSearchClient(Protocol):
    def search_studies(
        self,
        term: str,
        *,
        page_size: int = 10,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """Search ClinicalTrials.gov-style records."""
        ...


HKEX_BASE_URL = "https://www1.hkexnews.hk"
HKEX_ACTIVE_STOCKS_URL = (
    f"{HKEX_BASE_URL}/ncms/script/eds/activestock_sehk_e.json"
)
HKEX_TITLE_SEARCH_URL = f"{HKEX_BASE_URL}/search/titleSearchServlet.do"
PIPELINE_EXTRACTOR_VERSION = 9
COMPETITOR_EXTRACTOR_VERSION = 5
TARGET_PRICE_EXTRACTOR_VERSION = 1


@dataclass(frozen=True)
class SourceDocument:
    """One discovered and downloaded source document."""

    source_type: str
    title: str
    url: str
    publication_date: str | None
    file_path: Path
    text_path: Path
    stock_code: str | None = None
    stock_name: str | None = None


@dataclass(frozen=True)
class AutoInputArtifacts:
    """Artifacts produced by automatic input generation."""

    source_manifest: Path | None = None
    pipeline_assets: Path | None = None
    competitors: Path | None = None
    financials: Path | None = None
    conference_catalysts: Path | None = None
    valuation: Path | None = None
    target_price_assumptions: Path | None = None
    validation: dict[str, Any] | None = None
    source_documents: tuple[SourceDocument, ...] = ()
    warnings: tuple[str, ...] = ()


def generate_auto_inputs(
    *,
    identity: CompanyIdentity,
    input_dir: str | Path = "data/input/generated",
    output_dir: str | Path = "data",
    overwrite: bool = False,
    timeout: int = 30,
    market_data_provider: MarketDataProvider | None = None,
    competitor_discovery_client: ClinicalTrialsSearchClient | None = None,
    competitor_discovery_page_size: int = 5,
    competitor_discovery_max_requests: int = 3,
) -> AutoInputArtifacts:
    """Generate draft curated inputs for the current HK biotech MVP.

    When ``market_data_provider`` is supplied and returns a non-empty payload,
    a source-backed valuation snapshot draft is written alongside the other
    generated inputs. Provider failures or empty payloads degrade gracefully
    into warnings so the one-command report keeps working.
    """

    if identity.market != "HK" or not identity.ticker:
        return AutoInputArtifacts(
            warnings=(
                "auto input generation currently requires a Hong Kong ticker",
            )
        )

    ticker_code = _ticker_code(identity.ticker)
    if not ticker_code:
        return AutoInputArtifacts(warnings=("unable to parse Hong Kong ticker",))

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 biotech-alpha-lab/0.1"})
    stock_id = _resolve_hkex_stock_id(session, ticker_code, timeout=timeout)
    if stock_id is None:
        return AutoInputArtifacts(
            warnings=(f"unable to resolve HKEX stock id for {ticker_code}",)
        )

    announcement = _latest_hkex_annual_result(
        session=session,
        stock_id=stock_id,
        timeout=timeout,
    )
    if announcement is None:
        return AutoInputArtifacts(
            warnings=(f"unable to find annual results for {ticker_code}",)
        )

    slug = _slug(identity.ticker)
    raw_dir = Path(output_dir) / "raw" / "hkex" / slug
    processed_dir = Path(output_dir) / "processed" / "source_manifest" / slug
    generated_input_dir = Path(input_dir)
    for directory in (raw_dir, processed_dir, generated_input_dir):
        directory.mkdir(parents=True, exist_ok=True)

    document = _download_and_extract_document(
        session=session,
        announcement=announcement,
        raw_dir=raw_dir,
        timeout=timeout,
    )
    text = document.text_path.read_text(encoding="utf-8")
    pipeline_path = generated_input_dir / f"{slug}_pipeline_assets.json"
    competitors_path = generated_input_dir / f"{slug}_competitors.json"
    discovery_candidates_path = (
        generated_input_dir / f"{slug}_competitor_discovery_candidates.json"
    )
    financials_path = generated_input_dir / f"{slug}_financials.json"
    conference_path = generated_input_dir / f"{slug}_conference_catalysts.json"
    valuation_path = generated_input_dir / f"{slug}_valuation.json"
    target_price_assumptions_path = (
        generated_input_dir / f"{slug}_target_price_assumptions.json"
    )
    generation_warnings: list[str] = []

    if (
        overwrite
        or not pipeline_path.exists()
        or _pipeline_draft_needs_refresh(pipeline_path)
    ):
        pipeline_payload = draft_pipeline_assets(
            identity=identity,
            text=text,
            source=document,
        )
        _write_json(pipeline_path, pipeline_payload)
    else:
        pipeline_payload = _read_json(pipeline_path)
    discovery_candidates, candidate_warning = _read_competitor_discovery_file(
        discovery_candidates_path
    )
    if candidate_warning:
        generation_warnings.append(candidate_warning)
    candidates_newer = (
        discovery_candidates_path.exists()
        and (
            not competitors_path.exists()
            or discovery_candidates_path.stat().st_mtime
            >= competitors_path.stat().st_mtime
        )
    )
    if (
        overwrite
        or not competitors_path.exists()
        or _competitor_draft_needs_refresh(competitors_path)
        or candidates_newer
    ):
        _write_json(
            competitors_path,
            draft_competitor_assets(
                identity=identity,
                pipeline_assets_payload=pipeline_payload,
                source=document,
                discovery_candidates=discovery_candidates,
            ),
        )
    if competitor_discovery_client is not None:
        competitor_payload = _read_json(competitors_path)
        if (
            overwrite
            or not discovery_candidates_path.exists()
            or _competitor_discovery_needs_refresh(
                discovery_candidates_path,
                competitor_payload=competitor_payload,
                max_requests=competitor_discovery_max_requests,
            )
        ):
            discovery_payload = (
                draft_competitor_discovery_candidates_from_clinical_trials(
                    identity=identity,
                    competitor_draft_payload=competitor_payload,
                    client=competitor_discovery_client,
                    page_size=competitor_discovery_page_size,
                    max_requests=competitor_discovery_max_requests,
                )
            )
            _write_json(discovery_candidates_path, discovery_payload)
            generation_warnings.extend(discovery_payload.get("warnings", []))
            discovery_candidates, candidate_warning = (
                _read_competitor_discovery_file(discovery_candidates_path)
            )
            if candidate_warning:
                generation_warnings.append(candidate_warning)
            _write_json(
                competitors_path,
                draft_competitor_assets(
                    identity=identity,
                    pipeline_assets_payload=pipeline_payload,
                    source=document,
                    discovery_candidates=discovery_candidates,
                ),
            )
    if overwrite or not financials_path.exists():
        _write_json(
            financials_path,
            draft_financial_snapshot(
                identity=identity,
                text=text,
                source=document,
            ),
        )
    if overwrite or not conference_path.exists():
        _write_json(
            conference_path,
            draft_conference_catalysts(
                identity=identity,
                text=text,
                source=document,
            ),
        )

    valuation_written_path: Path | None = None
    if market_data_provider is not None and (
        overwrite or not valuation_path.exists()
    ):
        payload, provider_warnings = _safe_market_data_payload(
            provider=market_data_provider,
            identity=identity,
        )
        generation_warnings.extend(provider_warnings)
        if payload is not None:
            draft = draft_valuation_snapshot(
                identity=identity,
                market_data=payload,
            )
            generation_warnings.extend(draft["warnings"])
            if draft.get("writeable"):
                _write_json(valuation_path, draft["payload"])
                valuation_written_path = valuation_path

    if valuation_written_path is None and valuation_path.exists():
        valuation_written_path = valuation_path

    valuation_payload_for_target_price: dict[str, Any] | None = None
    if valuation_written_path is not None and valuation_written_path.exists():
        valuation_payload_for_target_price = _read_json(valuation_written_path)
    financial_payload = _read_json(financials_path) if financials_path.exists() else None
    if (
        overwrite
        or not target_price_assumptions_path.exists()
        or _target_price_draft_needs_refresh(target_price_assumptions_path)
    ):
        target_price_payload = draft_target_price_assumptions(
            company=identity.company,
            ticker=identity.ticker,
            pipeline_assets_payload=pipeline_payload,
            financial_snapshot_payload=financial_payload,
            valuation_snapshot_payload=valuation_payload_for_target_price,
            source=document.url,
            source_date=document.publication_date,
        )
        target_price_payload["generated_extractor_version"] = (
            TARGET_PRICE_EXTRACTOR_VERSION
        )
        _write_json(target_price_assumptions_path, target_price_payload)

    validation = {
        "pipeline_assets": validation_report_as_dict(
            validate_pipeline_asset_file(pipeline_path)
        ),
        "competitors": competition_validation_report_as_dict(
            validate_competitor_file(competitors_path)
        ),
        "financials": financial_validation_report_as_dict(
            validate_financial_snapshot_file(financials_path)
        ),
        "conference_catalysts": conference_validation_report_as_dict(
            validate_conference_catalyst_file(conference_path)
        ),
    }
    if valuation_written_path is not None:
        validation["valuation"] = valuation_validation_report_as_dict(
            validate_valuation_snapshot_file(valuation_written_path)
        )
    validation["target_price_assumptions"] = target_price_validation_report_as_dict(
        validate_target_price_assumptions_file(target_price_assumptions_path)
    )

    generated_inputs: dict[str, Path] = {
        "pipeline_assets": pipeline_path,
        "competitors": competitors_path,
        "financials": financials_path,
        "conference_catalysts": conference_path,
    }
    if valuation_written_path is not None:
        generated_inputs["valuation"] = valuation_written_path
    generated_inputs["target_price_assumptions"] = target_price_assumptions_path
    if discovery_candidates_path.exists():
        generated_inputs["competitor_discovery_candidates"] = (
            discovery_candidates_path
        )

    manifest_path = processed_dir / f"{date.today().isoformat()}_source_manifest.json"
    _write_json(
        manifest_path,
        {
            "identity": asdict(identity),
            "source_documents": [asdict(document)],
            "generated_inputs": generated_inputs,
            "validation": validation,
            "warnings": list(generation_warnings),
        },
    )
    return AutoInputArtifacts(
        source_manifest=manifest_path,
        pipeline_assets=pipeline_path,
        competitors=competitors_path,
        financials=financials_path,
        conference_catalysts=conference_path,
        valuation=valuation_written_path,
        target_price_assumptions=target_price_assumptions_path,
        validation=validation,
        source_documents=(document,),
        warnings=tuple(generation_warnings),
    )


def draft_pipeline_assets(
    *,
    identity: CompanyIdentity,
    text: str,
    source: SourceDocument,
) -> dict[str, Any]:
    """Extract a conservative draft pipeline asset file from source text."""

    assets = []
    seen_assets: dict[str, dict[str, Any]] = {}
    seen_codes: dict[str, str] = {}
    for match in _asset_mentions(text):
        context = match["context"]
        primary, aliases = _split_asset_codes(
            _canonical_asset_name_from_context(
                name=match["name"],
                context=context,
            )
        )
        key = primary.casefold()
        existing_key = seen_codes.get(key)
        candidate = _draft_asset_from_context(
            primary=primary,
            aliases=aliases,
            context=context,
            source=source,
        )
        candidate_aliases = [
            str(alias)
            for alias in candidate.get("aliases", [])
            if str(alias).strip()
        ]
        if existing_key:
            _merge_asset_fields(seen_assets[existing_key], candidate)
            _merge_asset_aliases(seen_assets[existing_key], candidate_aliases)
            for alias in candidate_aliases:
                seen_codes[alias.casefold()] = existing_key
            continue
        if len(assets) >= 12:
            continue
        assets.append(candidate)
        seen_assets[key] = candidate
        seen_codes[key] = key
        for alias in candidate_aliases:
            seen_codes[alias.casefold()] = key

    return {
        "company": identity.company,
        "ticker": identity.ticker,
        "generated_by": "auto_inputs.hkex_annual_results",
        "generated_extractor_version": PIPELINE_EXTRACTOR_VERSION,
        "needs_human_review": True,
        "assets": assets,
    }


_COMPETITOR_SEEDS_BY_TARGET: dict[str, list[dict[str, str]]] = {
    "HER2": [
        {"company": "AstraZeneca", "asset_name": "Trastuzumab deruxtecan"},
        {"company": "RemeGen", "asset_name": "Disitamab vedotin"},
    ],
    "B7-H3": [
        {"company": "Merck", "asset_name": "Ifinatamab deruxtecan"},
        {"company": "MediLink", "asset_name": "YL201"},
    ],
    "HER3": [
        {"company": "Daiichi Sankyo", "asset_name": "Patritumab deruxtecan"},
    ],
    "ADAM9": [
        {"company": "Amgen", "asset_name": "AMG 193 program"},
    ],
    "CDH17": [
        {"company": "Minghui Pharma", "asset_name": "CDH17 ADC program"},
    ],
    "B7-H4": [
        {"company": "Nuvation Bio", "asset_name": "B7-H4 ADC program"},
    ],
    "BCMA/CD3": [
        {"company": "Johnson & Johnson", "asset_name": "TECVAYLI"},
        {"company": "Pfizer", "asset_name": "ELREXFIO"},
    ],
    "CTLA-4": [
        {"company": "Bristol Myers Squibb", "asset_name": "YERVOY"},
    ],
    "FcRn": [
        {"company": "argenx", "asset_name": "VYVGART"},
        {"company": "UCB", "asset_name": "RYSTIGGO"},
    ],
    "TSLP": [
        {"company": "AstraZeneca/Amgen", "asset_name": "TEZSPIRE"},
    ],
}


def draft_competitor_assets(
    *,
    identity: CompanyIdentity,
    pipeline_assets_payload: dict[str, Any],
    source: SourceDocument,
    discovery_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Draft a conservative competitor seed set from extracted targets.

    This is intentionally heuristic and human-review-first. The goal is
    to reduce zero-competitor runs by pre-populating plausible same-target
    peers for major disclosed targets, while keeping every row clearly
    source-tagged as inferred. Optional ``discovery_candidates`` are
    source-backed records from a future LLM/web discovery layer; they are
    still gated deterministically before entering the competitor draft.
    """

    competitors: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    accepted_candidates = 0
    rejected_candidates = 0
    discovery_requests: list[dict[str, Any]] = []
    rows = pipeline_assets_payload.get("assets", [])
    if not isinstance(rows, list):
        rows = []
    pipeline_rows = [
        row
        for row in rows
        if isinstance(row, dict) and str(row.get("target") or "").strip()
    ]
    for row in pipeline_rows:
        target = str(row.get("target") or "").strip()
        pipeline_indication = str(row.get("indication") or "").strip()
        discovery_requests.append(_competitor_discovery_request(row, target))
        for seed in _competitor_seeds_for_target(target):
            key = (seed["company"], seed["asset_name"])
            if key in seen:
                continue
            seen.add(key)
            claim = (
                "Auto-generated competitor seed from target-overlap "
                f"heuristic for {target}; competitor indication and "
                "phase require manual verification."
            )
            if pipeline_indication:
                claim = (
                    f"{claim} Pipeline asset indication context: "
                    f"{pipeline_indication}."
                )
            competitors.append(
                {
                    "company": seed["company"],
                    "asset_name": seed["asset_name"],
                    "aliases": [],
                    "target": target,
                    "mechanism": None,
                    "indication": "to_verify",
                    "phase": "to_verify",
                    "geography": "global",
                    "differentiation": (
                        "Generated target-overlap seed; verify indication, "
                        "phase, and modality before using as a comparator."
                    ),
                    "evidence": [
                        {
                            "claim": claim,
                            "source": source.url,
                            "source_date": source.publication_date,
                            "confidence": 0.3,
                            "is_inferred": True,
                        }
                    ],
                }
            )
        if len(competitors) >= 16:
            break
    for candidate in discovery_candidates or []:
        drafted = _draft_competitor_from_discovery_candidate(
            candidate=candidate,
            identity=identity,
            pipeline_rows=pipeline_rows,
            source=source,
        )
        if drafted is None:
            rejected_candidates += 1
            continue
        key = (drafted["company"], drafted["asset_name"])
        if key in seen:
            continue
        seen.add(key)
        competitors.append(drafted)
        accepted_candidates += 1
        if len(competitors) >= 16:
            break

    return {
        "company": identity.company,
        "ticker": identity.ticker,
        "generated_by": "auto_inputs.target_overlap_seed",
        "generated_extractor_version": COMPETITOR_EXTRACTOR_VERSION,
        "needs_human_review": True,
        "generation_strategy": [
            "deterministic_target_overlap_seed",
            "review_gated_global_discovery_candidates",
        ],
        "discovery_requests": discovery_requests,
        "candidate_ingest": {
            "accepted": accepted_candidates,
            "rejected": rejected_candidates,
            "notes": (
                "Discovery candidates must include source URL/date, evidence "
                "text, and a target family matching the pipeline asset."
            ),
        },
        "competitors": competitors,
    }


def draft_competitor_discovery_candidates_from_clinical_trials(
    *,
    identity: CompanyIdentity,
    competitor_draft_payload: dict[str, Any],
    client: ClinicalTrialsSearchClient,
    page_size: int = 5,
    max_requests: int = 8,
) -> dict[str, Any]:
    """Create source-backed competitor candidates from ClinicalTrials.gov.

    This runner is intentionally bounded and conservative: a returned trial is
    only converted into a candidate when the trial text itself mentions every
    target token from the pipeline discovery request.
    """

    requests_payload = competitor_draft_payload.get("discovery_requests")
    if not isinstance(requests_payload, list):
        requests_payload = []
    candidates: list[dict[str, Any]] = []
    searched: list[dict[str, Any]] = []
    warnings: list[str] = []
    rejections: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    request_count = 0
    for request in requests_payload:
        if request_count >= max_requests:
            break
        if not isinstance(request, dict):
            continue
        target = _candidate_text(request, "target")
        if not target:
            continue
        query = _clinical_trials_query_for_competitor_request(request)
        if not query:
            continue
        request_count += 1
        searched.append(
            {
                "pipeline_asset": _candidate_text(request, "pipeline_asset"),
                "target": target,
                "query": query,
            }
        )
        try:
            response = client.search_studies(query, page_size=page_size)
        except Exception as exc:  # noqa: BLE001 - discovery should degrade.
            warnings.append(
                f"ClinicalTrials.gov competitor discovery failed for "
                f"{target}: {exc}"
            )
            continue
        for trial in extract_trial_summaries(response):
            candidate, rejection = _clinical_trial_competitor_candidate(
                identity=identity,
                request=request,
                target=target,
                query=query,
                trial=trial,
            )
            if candidate is None:
                if rejection is not None and len(rejections) < 30:
                    rejections.append(rejection)
                continue
            key = (
                _compact_target_key(candidate["company"]),
                _compact_target_key(candidate["asset_name"]),
                str(candidate.get("source_url") or ""),
            )
            if key in seen:
                if len(rejections) < 30:
                    rejections.append(
                        _trial_rejection(
                            trial=trial,
                            target=target,
                            reason="duplicate_candidate",
                        )
                    )
                continue
            seen.add(key)
            candidates.append(candidate)
    return {
        "company": identity.company,
        "ticker": identity.ticker,
        "generated_by": "auto_inputs.clinicaltrials_competitor_discovery",
        "generated_extractor_version": COMPETITOR_EXTRACTOR_VERSION,
        "source": "ClinicalTrials.gov",
        "max_requests": max_requests,
        "requests_searched": searched,
        "warnings": warnings,
        "rejections": rejections,
        "rejection_summary": _rejection_summary(rejections),
        "candidates": candidates,
        "needs_human_review": True,
    }


def _clinical_trials_query_for_competitor_request(
    request: dict[str, Any],
) -> str | None:
    target = _candidate_text(request, "target")
    if not target:
        return None
    modality = _candidate_text(request, "modality") or ""
    target_query = target.replace("/", " ").replace("×", " ")
    return " ".join(part for part in (target_query, modality) if part).strip()


def _clinical_trial_competitor_candidate(
    *,
    identity: CompanyIdentity,
    request: dict[str, Any],
    target: str,
    query: str,
    trial: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not _trial_mentions_target(trial, target):
        return None, _trial_rejection(
            trial=trial,
            target=target,
            reason="target_family_not_mentioned",
        )
    sponsor = str(getattr(trial, "sponsor", "") or "").strip()
    if not sponsor or _same_compact_text(sponsor, identity.company):
        reason = "missing_sponsor" if not sponsor else "self_company"
        return None, _trial_rejection(trial=trial, target=target, reason=reason)
    source_date = str(getattr(trial, "last_update_posted", "") or "").strip()
    if not source_date:
        return None, _trial_rejection(
            trial=trial,
            target=target,
            reason="missing_source_date",
        )
    asset_name, asset_rejection = _trial_candidate_asset_name(trial, target)
    if not asset_name:
        return None, _trial_rejection(
            trial=trial,
            target=target,
            reason=asset_rejection or "missing_asset_name",
        )
    registry_id = str(getattr(trial, "registry_id", "") or "").strip()
    source_url = _clinicaltrials_study_url(registry_id)
    if not source_url:
        return None, _trial_rejection(
            trial=trial,
            target=target,
            reason="missing_registry_id",
        )
    pipeline_asset = _candidate_text(request, "pipeline_asset") or target
    snippet = _clinical_trial_evidence_snippet(trial)
    return {
        "company": sponsor,
        "asset_name": asset_name,
        "aliases": [registry_id] if registry_id else [],
        "target": target,
        "modality": _candidate_text(request, "modality"),
        "indication": _trial_conditions_text(trial) or "to_verify",
        "phase": str(getattr(trial, "phase", "") or "").strip() or "to_verify",
        "geography": "global",
        "source_url": source_url,
        "source_date": source_date,
        "evidence_snippet": snippet,
        "why_comparable": (
            f"ClinicalTrials.gov record mentions the {target} target family "
            f"and was discovered from the request for {pipeline_asset}."
        ),
        "source_query": query,
        "confidence": 0.55,
        "generated_by_llm": False,
    }, None


def _trial_rejection(
    *,
    trial: Any,
    target: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "reason": reason,
        "target": target,
        "registry_id": str(getattr(trial, "registry_id", "") or "").strip()
        or None,
        "title": str(getattr(trial, "title", "") or "").strip()[:120] or None,
        "sponsor": str(getattr(trial, "sponsor", "") or "").strip() or None,
    }


def _rejection_summary(rejections: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for rejection in rejections:
        reason = str(rejection.get("reason") or "unknown")
        summary[reason] = summary.get(reason, 0) + 1
    return summary


def _trial_mentions_target(trial: Any, target: str) -> bool:
    haystack = _compact_target_key(
        " ".join(
            [
                str(getattr(trial, "title", "") or ""),
                " ".join(getattr(trial, "conditions", ()) or ()),
                " ".join(getattr(trial, "interventions", ()) or ()),
            ]
        )
    )
    tokens = _target_tokens(target)
    return bool(tokens) and all(token in haystack for token in tokens)


def _trial_candidate_asset_name(
    trial: Any,
    target: str,
) -> tuple[str | None, str | None]:
    interventions = [
        str(intervention or "").strip()
        for intervention in getattr(trial, "interventions", ()) or ()
        if str(intervention or "").strip()
    ]
    target_interventions = [
        intervention
        for intervention in interventions
        if _text_mentions_target(intervention, target)
    ]
    if target_interventions:
        for intervention in target_interventions:
            if not _generic_target_intervention(intervention, target):
                return intervention, None
        return None, "generic_target_intervention"
    for intervention in interventions:
        if not _background_intervention(intervention):
            return intervention, None
    title = str(getattr(trial, "title", "") or "").strip()
    return (title[:80], None) if title else (None, "missing_asset_name")


def _text_mentions_target(text: str, target: str) -> bool:
    haystack = _compact_target_key(text)
    tokens = _target_tokens(target)
    return bool(tokens) and all(token in haystack for token in tokens)


def _generic_target_intervention(intervention: str, target: str) -> bool:
    compact = _compact_target_key(intervention)
    target_compact = _compact_target_key(target)
    generic_terms = (
        "bites",
        "bite",
        "bispecific",
        "antibody",
        "antibodies",
        "tcellengager",
        "tce",
    )
    if target_compact not in compact:
        return False
    remainder = compact.replace(target_compact, "")
    for term in generic_terms:
        remainder = remainder.replace(term, "")
    return len(remainder) < 4


def _background_intervention(intervention: str) -> bool:
    compact = _compact_target_key(intervention)
    background_terms = (
        "hematopoieticstemcelltransplantation",
        "stemcelltransplantation",
        "autologous",
        "placebo",
        "standardofcare",
    )
    return any(term in compact for term in background_terms)


def _clinical_trial_evidence_snippet(trial: Any) -> str:
    parts = [
        str(getattr(trial, "title", "") or "").strip(),
        "Interventions: "
        + "; ".join(getattr(trial, "interventions", ()) or ()),
        "Conditions: " + "; ".join(getattr(trial, "conditions", ()) or ()),
        "Phase: " + str(getattr(trial, "phase", "") or "").strip(),
        "Status: " + str(getattr(trial, "status", "") or "").strip(),
    ]
    return " | ".join(part for part in parts if part and not part.endswith(": "))


def _trial_conditions_text(trial: Any) -> str | None:
    conditions = [
        str(condition).strip()
        for condition in getattr(trial, "conditions", ()) or ()
        if str(condition).strip()
    ]
    return "; ".join(conditions) if conditions else None


def _clinicaltrials_study_url(registry_id: str) -> str | None:
    if not registry_id:
        return None
    return f"https://clinicaltrials.gov/study/{registry_id}"


def _competitor_seeds_for_target(target: str) -> tuple[dict[str, str], ...]:
    seeds: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for key in _target_seed_keys(target):
        for seed in _COMPETITOR_SEEDS_BY_TARGET.get(key, []):
            seed_key = (seed["company"], seed["asset_name"])
            if seed_key in seen:
                continue
            seen.add(seed_key)
            seeds.append(seed)
    return tuple(seeds)


def _competitor_discovery_request(
    row: dict[str, Any],
    target: str,
) -> dict[str, Any]:
    asset_name = str(row.get("name") or "").strip()
    modality = str(row.get("modality") or "").strip()
    target_query = target.replace("/", " ")
    terms = [
        f'"{target}" competitor clinical trial',
        f'"{target}" {modality} pipeline'.strip(),
        f'"{target_query}" biotech asset phase',
    ]
    return {
        "pipeline_asset": asset_name,
        "target": target,
        "modality": modality or None,
        "queries": list(dict.fromkeys(terms)),
        "candidate_schema": {
            "required": [
                "company",
                "asset_name",
                "target",
                "source_url",
                "source_date",
                "evidence_snippet",
                "why_comparable",
            ]
        },
    }


def _draft_competitor_from_discovery_candidate(
    *,
    candidate: dict[str, Any],
    identity: CompanyIdentity,
    pipeline_rows: list[dict[str, Any]],
    source: SourceDocument,
) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    company = _candidate_text(candidate, "company")
    asset_name = _candidate_text(candidate, "asset_name")
    candidate_target = _candidate_text(candidate, "target")
    source_url = _candidate_text(candidate, "source_url") or _candidate_text(
        candidate, "evidence_url"
    )
    source_date = _candidate_text(candidate, "source_date")
    evidence_snippet = _candidate_text(candidate, "evidence_snippet")
    why_comparable = _candidate_text(candidate, "why_comparable")
    if not (
        company
        and asset_name
        and candidate_target
        and source_url
        and source_date
        and evidence_snippet
        and why_comparable
    ):
        return None
    if _same_compact_text(company, identity.company):
        return None
    pipeline_row = _matching_pipeline_row(candidate_target, pipeline_rows)
    if pipeline_row is None:
        return None
    pipeline_target = str(pipeline_row.get("target") or "").strip()
    confidence = _candidate_confidence(candidate.get("confidence"), default=0.45)
    pipeline_asset = str(pipeline_row.get("name") or "").strip()
    claim = (
        f"Global discovery candidate for {pipeline_asset or pipeline_target}: "
        f"{why_comparable} Evidence snippet: {evidence_snippet}"
    )
    return {
        "company": company,
        "asset_name": asset_name,
        "aliases": _candidate_aliases(candidate.get("aliases")),
        "target": pipeline_target,
        "mechanism": _candidate_text(candidate, "mechanism"),
        "indication": _candidate_text(candidate, "indication") or "to_verify",
        "phase": _candidate_text(candidate, "phase") or "to_verify",
        "geography": _candidate_text(candidate, "geography") or "global",
        "differentiation": (
            "Review-gated global discovery candidate; verify ownership, "
            "phase, indication, and true competitive proximity before use."
        ),
        "generated_by_llm": bool(candidate.get("generated_by_llm", True)),
        "source_query": _candidate_text(candidate, "source_query"),
        "matched_pipeline_asset": pipeline_asset or None,
        "evidence": [
            {
                "claim": claim,
                "source": source_url,
                "source_date": source_date,
                "retrieved_at": _candidate_text(candidate, "retrieved_at"),
                "confidence": min(confidence, 0.65),
                "is_inferred": True,
            },
            {
                "claim": (
                    "Candidate accepted by deterministic target-family gate "
                    f"against {pipeline_target} from {source.title}."
                ),
                "source": source.url,
                "source_date": source.publication_date,
                "confidence": 0.35,
                "is_inferred": True,
            },
        ],
    }


def _matching_pipeline_row(
    candidate_target: str,
    pipeline_rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for row in pipeline_rows:
        pipeline_target = str(row.get("target") or "").strip()
        if _target_family_matches(candidate_target, pipeline_target):
            return row
    return None


def _candidate_text(candidate: dict[str, Any], key: str) -> str | None:
    value = candidate.get(key)
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _candidate_aliases(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _candidate_confidence(value: Any, *, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return default
    if confidence < 0:
        return default
    if confidence > 1:
        return 1.0
    return confidence


def _target_family_matches(candidate_target: str, pipeline_target: str) -> bool:
    candidate_compact = _compact_target_key(candidate_target)
    pipeline_compact = _compact_target_key(pipeline_target)
    if candidate_compact and candidate_compact == pipeline_compact:
        return True
    candidate_tokens = _target_tokens(candidate_target)
    pipeline_tokens = _target_tokens(pipeline_target)
    return bool(candidate_tokens) and candidate_tokens == pipeline_tokens


def _target_tokens(value: str) -> tuple[str, ...]:
    normalized = re.sub(r"\s+(?:x|X)\s+", "/", value)
    normalized = normalized.replace("×", "/")
    parts = re.split(r"/+", normalized)
    tokens = [
        _compact_target_key(part)
        for part in parts
        if _compact_target_key(part)
    ]
    return tuple(sorted(dict.fromkeys(tokens)))


def _same_compact_text(left: str, right: str | None) -> bool:
    if not left or not right:
        return False
    return _compact_target_key(left) == _compact_target_key(right)


def _target_seed_keys(target: str) -> tuple[str, ...]:
    normalized = target.strip()
    if not normalized:
        return ()
    compact = _compact_target_key(normalized)
    keys = [normalized]
    for known in _COMPETITOR_SEEDS_BY_TARGET:
        if _compact_target_key(known) == compact:
            keys.append(known)
    for part in re.split(r"[/×x]", normalized):
        item = part.strip()
        if not item:
            continue
        keys.append(item)
        compact_item = _compact_target_key(item)
        for known in _COMPETITOR_SEEDS_BY_TARGET:
            if _compact_target_key(known) == compact_item:
                keys.append(known)
    return tuple(dict.fromkeys(keys))


def _compact_target_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _draft_asset_from_context(
    *,
    primary: str,
    aliases: list[str],
    context: str,
    source: SourceDocument,
) -> dict[str, Any]:
    local_context = _local_asset_context(context=context, asset_name=primary)
    partner_context = _asset_context_with_left(
        context=context,
        asset_name=primary,
    )
    packed_context = _packed_left_context(context=context, asset_name=primary)
    target = _target_from_context(local_context)
    modality = _modality_from_context(local_context)
    mechanism = _mechanism_from_context(local_context, target=target)
    indication = _indication_from_context(local_context)
    if packed_context:
        target = _target_from_context(packed_context)
        modality = _modality_from_context(packed_context)
        mechanism = (
            _mechanism_from_context(packed_context, target=target)
            or mechanism
        )
        indication = _indication_from_context(packed_context) or indication
    if target:
        mechanism = None
    source_year = _year_from_source_date(source.publication_date)
    aliases = list(
        dict.fromkeys([*aliases, *_aliases_from_context(local_context, primary)])
    )
    return {
        "name": primary,
        "aliases": aliases,
        "target": target,
        "modality": modality,
        "mechanism": mechanism,
        "indication": indication,
        "phase": _phase_from_asset_context(
            context=context,
            asset_name=primary,
        ),
        "geography": _geography_from_context(context),
        "rights": None,
        "partner": _partner_from_context(partner_context),
        "next_milestone": _milestone_from_context(
            local_context,
            as_of_year=source_year,
        ),
        "evidence": [
            {
                "claim": _clean_claim(context),
                "source": source.url,
                "source_date": source.publication_date,
                "confidence": 0.45,
                "is_inferred": True,
            }
        ],
    }


def _local_asset_context(
    *,
    context: str,
    asset_name: str,
    size: int = 700,
) -> str:
    match = _asset_code_match(context=context, asset_name=asset_name)
    if not match:
        return context
    local = _truncate_at_next_numbered_section(
        context[match.start(): match.start() + size]
    )
    local = _truncate_at_next_asset_mention(local, asset_name=asset_name)
    return _truncate_at_listing_warning(local)


def _asset_context_with_left(
    *,
    context: str,
    asset_name: str,
    size: int = 700,
    left_size: int = 180,
) -> str:
    match = _asset_code_match(context=context, asset_name=asset_name)
    if not match:
        return context
    left = context[max(0, match.start() - left_size): match.start()]
    left = re.split(r"(?:\n|\s{2,}|\.\s+)\d+\.\s+[A-Z]", left)[-1]
    right = _truncate_at_next_numbered_section(
        context[match.start(): match.start() + size]
    )
    return left + right


def _truncate_at_next_numbered_section(context: str) -> str:
    match = re.search(r"(?:\n|\s{2,}|\.\s+)\d+\.\s+[A-Z]", context)
    if not match:
        return context
    return context[:match.start()]


def _truncate_at_next_asset_mention(context: str, *, asset_name: str) -> str:
    pattern = re.compile(
        r"(?<![A-Za-z-])([A-Z]{1,6}\s*-\s*\d{3,5}|[A-Z]{1,6}-?\d{3,5})\b"
    )
    current, _ = _split_asset_codes(re.sub(r"\s+", "", asset_name))
    for match in pattern.finditer(context):
        prefix = context[:match.start()].rstrip()
        if prefix.endswith("/"):
            continue
        if re.search(r"\bknown\s+as\s*$", prefix, flags=re.IGNORECASE):
            continue
        candidate, _ = _split_asset_codes(re.sub(r"\s+", "", match.group(1)))
        if candidate == current:
            continue
        return context[:match.start()]
    return context


def _truncate_at_listing_warning(context: str) -> str:
    match = re.search(
        r"\bWarning under Rule 18A\b|\bThere is no assurance that\b",
        context,
        flags=re.IGNORECASE,
    )
    if not match:
        return context
    return context[:match.start()]


def _packed_left_context(
    *,
    context: str,
    asset_name: str,
    size: int = 180,
) -> str | None:
    match = _asset_code_match(context=context, asset_name=asset_name)
    if not match:
        return None
    if match.start() == 0 or context[match.start() - 1].isspace():
        return None
    if context[match.start() - 1] in "(/":
        return None
    left = context[max(0, match.start() - size): match.start()]
    stripped = re.sub(
        r".*[A-Z]{1,6}-?\d{3,5}\d?(?:/\s*[A-Z]{1,6}-?\d{3,5}\d?)?",
        "",
        left,
        flags=re.DOTALL,
    )
    if not re.search(
        r"Global|Greater|Diseases?|Tumou?rs?|IBD|IgAN|\(mAb\)|\(BsAb\)",
        stripped,
        flags=re.IGNORECASE,
    ):
        return None
    return stripped


def _asset_code_match(*, context: str, asset_name: str) -> re.Match[str] | None:
    escaped = re.escape(asset_name).replace(r"\-", r"\s*-\s*")
    pattern = rf"(?<![A-Za-z-]){escaped}\b"
    return re.search(pattern, context)


def _aliases_from_context(context: str, asset_name: str) -> list[str]:
    aliases: list[str] = []
    pattern = (
        rf"\b{re.escape(asset_name)}\b.{{0,80}}"
        r"\(known as\s+([A-Z]{1,6}-?\d{3,5})\s+outside of China\)"
    )
    match = re.search(pattern, context, flags=re.IGNORECASE | re.DOTALL)
    if match:
        aliases.append(match.group(1))
    return aliases


def _merge_asset_fields(
    existing: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    for key in (
        "target",
        "modality",
        "indication",
        "phase",
        "geography",
        "partner",
        "next_milestone",
    ):
        existing_value = existing.get(key)
        candidate_value = candidate.get(key)
        if not existing_value and candidate_value:
            existing[key] = candidate[key]
        elif key == "phase" and _phase_rank(candidate_value) > _phase_rank(
            existing_value
        ):
            existing[key] = candidate_value
        elif key == "target" and _field_specificity_score(
            candidate_value
        ) > _field_specificity_score(existing_value):
            existing[key] = candidate_value
        elif key == "modality" and _modality_rank(
            candidate_value
        ) > _modality_rank(existing_value):
            existing[key] = candidate_value
        elif key == "indication" and _field_specificity_score(
            candidate_value
        ) > _field_specificity_score(existing_value):
            existing[key] = candidate_value


def _merge_asset_aliases(existing: dict[str, Any], aliases: list[str]) -> None:
    existing_aliases = existing.get("aliases")
    if not isinstance(existing_aliases, list):
        existing["aliases"] = []
        existing_aliases = existing["aliases"]
    for alias in aliases:
        if alias != existing.get("name") and alias not in existing_aliases:
            existing_aliases.append(alias)


def _phase_rank(value: Any) -> float:
    text = str(value or "").casefold()
    if not text:
        return 0
    if "bla under review" in text or "bla accepted" in text:
        return 7
    if "bla" in text:
        return 6
    if "phase 3" in text or "phase iii" in text:
        return 5
    if "phase 2" in text or "phase ii" in text:
        return 4
    if "phase 1" in text or "phase i" in text:
        return 3
    if "ind approved" in text or "ind accepted" in text:
        return 2.5
    if "clinical-stage" in text:
        return 2.25
    if "ind-enabling" in text:
        return 2
    if "pcc nomination" in text:
        return 1.5
    if "preclinical" in text or "pre-clinical" in text:
        return 1
    return 1


def _modality_rank(value: Any) -> int:
    text = str(value or "").casefold()
    if not text:
        return 0
    if "tce-adc" in text:
        return 6
    if "bispecific adc" in text:
        return 5
    if "trispecific" in text:
        return 4
    if "bispecific fusion" in text:
        return 4
    if "fusion protein" in text:
        return 3
    if "bispecific" in text:
        return 3
    if "adc" in text:
        return 2
    if "antibody" in text:
        return 1
    return 1


def _field_specificity_score(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    parts = [part for part in re.split(r"[/;]", text) if part.strip()]
    return len(parts) * 10 + len(text)


def draft_financial_snapshot(
    *,
    identity: CompanyIdentity,
    text: str,
    source: SourceDocument,
) -> dict[str, Any]:
    """Extract a draft financial snapshot from source text."""

    multiplier = _financial_multiplier(text)
    cash = _first_amount(
        text,
        (
            r"Cash and Bank Balances\s+\d*\s*([\d,]+)",
            r"Cash and cash equivalents at end of the year\s+([\d,]+)",
            r"Cash and cash equivalents\s+([\d,]+)",
        ),
        multiplier=multiplier,
    )
    debt = _first_amount(
        text,
        (
            r"Bank borrowings[^\n\d]{0,80}([\d,]+)",
            r"Bank borrowings\s+([\d,]+)",
            r"Borrowings\s+([\d,]+)",
            r"Interest-bearing bank borrowings\s+([\d,]+)",
        ),
        multiplier=multiplier,
    )
    adjusted_loss = _first_amount(
        text,
        (
            r"Adjusted loss for the year(?:\s+\d+)?\s+\(?([\d,]+)\)?",
            r"Adjusted net loss\s+\(?([\d,]+)\)?",
            r"Loss for the year(?:\s+\d+)?\s+\(?([\d,]+)\)?",
        ),
        multiplier=multiplier,
    )
    operating_cash_flow = _signed_amount_after_label(
        text,
        "Net cash inflow from operating activities",
        multiplier=multiplier,
    )
    if operating_cash_flow is None:
        operating_cash_flow = _signed_amount_after_label(
            text,
            "Net cash outflow from operating activities",
            multiplier=multiplier,
        )
        if operating_cash_flow is not None:
            operating_cash_flow = -abs(operating_cash_flow)

    return {
        "company": identity.company,
        "ticker": identity.ticker,
        "as_of_date": _financial_as_of_date(text) or source.publication_date,
        "currency": _financial_currency(text),
        "cash_and_equivalents": cash or 0,
        "short_term_debt": debt or 0,
        "quarterly_cash_burn": (
            abs(adjusted_loss) / 4
            if adjusted_loss and adjusted_loss > 0
            else None
        ),
        "operating_cash_flow_ttm": operating_cash_flow,
        "source": source.url,
        "source_date": source.publication_date,
        "generated_by": "auto_inputs.hkex_annual_results",
        "needs_human_review": True,
    }


def draft_valuation_snapshot(
    *,
    identity: CompanyIdentity,
    market_data: dict[str, Any],
) -> dict[str, Any]:
    """Build a draft valuation snapshot payload from a market-data provider.

    Returns a dict with keys ``payload`` (JSON-serializable valuation snapshot)
    and ``warnings`` (list of normalization warnings for auditability).
    """

    normalized = normalize_hk_market_data(market_data)
    financials = market_data.get("financials") if isinstance(
        market_data.get("financials"), dict
    ) else {}
    cash = _optional_float(financials.get("cash_and_equivalents")) or 0.0
    debt = _optional_float(financials.get("total_debt")) or 0.0
    revenue = _optional_float(financials.get("revenue_ttm"))

    payload = valuation_snapshot_payload_from_market_data(
        company=identity.company,
        ticker=identity.ticker,
        normalized=normalized,
        cash_and_equivalents=cash,
        total_debt=debt,
        revenue_ttm=revenue,
    )
    payload["generated_by"] = "auto_inputs.market_data_provider"
    payload["needs_human_review"] = True

    writeable = normalized.market_cap is not None or (
        normalized.share_price is not None
        and normalized.shares_outstanding is not None
    )

    return {
        "payload": payload,
        "writeable": writeable,
        "warnings": [
            f"valuation draft: {warning}" for warning in normalized.warnings
        ],
    }


def _safe_market_data_payload(
    *,
    provider: MarketDataProvider,
    identity: CompanyIdentity,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Invoke a market-data provider without breaking the report flow."""

    try:
        payload = provider(identity)
    except Exception as exc:  # noqa: BLE001 - keep one-command flow resilient.
        return None, [f"market data provider failed: {exc}"]
    if payload is None:
        return None, ["market data provider returned no payload"]
    if not isinstance(payload, dict):
        return None, ["market data provider returned non-dict payload"]
    return payload, []


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        compact = value.replace(",", "").strip()
        if not compact:
            return None
        try:
            return float(compact)
        except ValueError:
            return None
    return None


def draft_conference_catalysts(
    *,
    identity: CompanyIdentity,
    text: str,
    source: SourceDocument,
) -> dict[str, Any]:
    """Extract a conservative draft conference catalyst input file."""

    conferences = ("ASCO", "ESMO", "AACR", "WCLC", "ASH", "SABCS")
    catalysts: list[dict[str, Any]] = []
    for conference in conferences:
        if not re.search(rf"\b{re.escape(conference)}\b", text, flags=re.IGNORECASE):
            continue
        catalysts.append(
            {
                "title": f"{conference} data update expected",
                "category": "conference",
                "expected_window": conference,
                "related_asset": None,
                "confidence": 0.35,
                "source_type": "company_disclosure",
                "evidence": [
                    {
                        "claim": (
                            f"{conference} appears in source text; confirm event scope "
                            "and timing manually."
                        ),
                        "source": source.url,
                        "source_date": source.publication_date,
                        "confidence": 0.45,
                        "is_inferred": True,
                    }
                ],
            }
        )

    return {
        "company": identity.company,
        "ticker": identity.ticker,
        "generated_by": "auto_inputs.hkex_annual_results",
        "needs_human_review": True,
        "catalysts": catalysts,
    }


def _resolve_hkex_stock_id(
    session: requests.Session,
    ticker_code: str,
    *,
    timeout: int,
) -> str | None:
    response = _get_with_retries(
        session,
        HKEX_ACTIVE_STOCKS_URL,
        timeout=timeout,
    )
    for row in response.json():
        if str(row.get("c", "")).zfill(5) == ticker_code:
            return str(row.get("i"))
    return None


def _latest_hkex_annual_result(
    *,
    session: requests.Session,
    stock_id: str,
    timeout: int,
) -> dict[str, Any] | None:
    today = date.today()
    from_date = (today - timedelta(days=900)).strftime("%Y%m%d")
    to_date = today.strftime("%Y%m%d")
    for title in ("annual results", "annual report", "final results"):
        params = {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": stock_id,
            "documentType": "",
            "fromDate": from_date,
            "toDate": to_date,
            "title": title,
            "searchType": "0",
            "t1code": "",
            "t2Gcode": "",
            "t2code": "",
            "rowRange": "20",
            "lang": "en",
        }
        response = _get_with_retries(
            session,
            HKEX_TITLE_SEARCH_URL,
            params=params,
            timeout=timeout,
        )
        rows = json.loads(response.json().get("result", "[]"))
        pdf_rows = [row for row in rows if row.get("FILE_LINK")]
        if pdf_rows:
            return pdf_rows[0]
    return None


def _download_and_extract_document(
    *,
    session: requests.Session,
    announcement: dict[str, Any],
    raw_dir: Path,
    timeout: int,
) -> SourceDocument:
    file_url = urljoin(HKEX_BASE_URL, announcement["FILE_LINK"])
    news_id = str(announcement.get("NEWS_ID") or _safe_filename(file_url))
    pdf_path = raw_dir / f"{news_id}.pdf"
    text_path = raw_dir / f"{news_id}.txt"
    if not pdf_path.exists():
        response = _get_with_retries(session, file_url, timeout=timeout)
        pdf_path.write_bytes(response.content)
    if not text_path.exists():
        reader = PdfReader(io.BytesIO(pdf_path.read_bytes()))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        text_path.write_text(text, encoding="utf-8")

    return SourceDocument(
        source_type="hkex_annual_results",
        title=str(announcement.get("TITLE") or ""),
        url=file_url,
        publication_date=_announcement_date(announcement.get("DATE_TIME")),
        file_path=pdf_path,
        text_path=text_path,
        stock_code=announcement.get("STOCK_CODE"),
        stock_name=announcement.get("STOCK_NAME"),
    )


def _get_with_retries(
    session: requests.Session,
    url: str,
    *,
    timeout: int,
    attempts: int = 3,
    **kwargs: Any,
) -> requests.Response:
    last_error: requests.RequestException | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            time.sleep(min(0.5 * attempt, 2.0))
    if last_error:
        raise last_error
    raise RuntimeError("request retry loop exhausted without an exception")


def _asset_mentions(text: str) -> list[dict[str, str]]:
    pattern = re.compile(
        r"(?<![A-Za-z-])(?!(?:NCT|RMB|HKD)\b)"
        r"([A-Z]{1,6}-?\d{3,5}(?:/\s*[A-Z]{1,6}-?\d{3,5})?)\b"
    )
    mentions = []
    matches = list(pattern.finditer(text))
    for index, match in enumerate(matches):
        name = match.group(1)
        if _looks_like_non_asset_code(name):
            continue
        if _looks_like_merged_target_code(name):
            continue
        if _looks_like_merged_modality_code(name):
            continue
        previous_match = _adjacent_different_asset_match(
            matches=matches,
            index=index,
            current=name,
            direction=-1,
        )
        next_match = _next_different_asset_match(
            matches=matches,
            index=index,
            current=name,
        )
        if _payload_only_context(
            name=name,
            context=_nearby_text(text, match.start(), match.end()),
        ):
            continue
        if _listing_warning_context(
            context=text[max(0, match.start() - 180): match.end() + 20],
        ):
            continue
        if _combination_partner_context(
            name=name,
            context=_nearby_text(text, match.start(), match.end()),
        ):
            continue
        left_boundary = previous_match.end() if previous_match else None
        if previous_match and re.search(
            r"\bknown\s+as\s*$",
            text[previous_match.end(): match.start()],
            flags=re.IGNORECASE | re.DOTALL,
        ):
            left_boundary = previous_match.start()
        context = _context_window(
            text,
            match.start(),
            match.end(),
            left_boundary=left_boundary,
            right_boundary=next_match.start() if next_match else None,
        )
        if not _biotech_context(context):
            continue
        mentions.append({"name": name, "context": context})
    return mentions


def _next_different_asset_match(
    *,
    matches: list[re.Match[str]],
    index: int,
    current: str,
) -> re.Match[str] | None:
    return _adjacent_different_asset_match(
        matches=matches,
        index=index,
        current=current,
        direction=1,
    )


def _adjacent_different_asset_match(
    *,
    matches: list[re.Match[str]],
    index: int,
    current: str,
    direction: int,
) -> re.Match[str] | None:
    current_primary, _ = _split_asset_codes(current)
    cursor = index + direction
    while 0 <= cursor < len(matches):
        candidate = matches[cursor]
        candidate_primary, _ = _split_asset_codes(candidate.group(1))
        if candidate_primary != current_primary:
            return candidate
        cursor += direction
    return None


def _split_asset_codes(value: str) -> tuple[str, list[str]]:
    codes = [code.strip() for code in value.split("/") if code.strip()]
    return codes[0], codes[1:]


def _canonical_asset_name_from_context(*, name: str, context: str) -> str:
    pattern = (
        r"\b([A-Z]{1,6}\s*-\s*\d{3,5}|[A-Z]{1,6}\d{3,5})"
        rf"\b\s*\(known as\s+{re.escape(name)}\s+outside of China\)"
    )
    match = re.search(pattern, context, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return name
    primary = re.sub(r"\s+", "", match.group(1))
    return f"{primary}/{name}"


def _target_from_context(context: str) -> str | None:
    context = re.sub(r"I\s+L23p19", "IL23p19", context)
    context = re.sub(r"4-1\s+BB", "4-1BB", context, flags=re.IGNORECASE)
    targets = (
        "HER2",
        "B7-H3",
        "B7-H4",
        "B7H4",
        "B7H7",
        "HER3",
        "EGFR",
        "HHLA2",
        "CLDN18.2",
        "TROP2",
        "BCMA",
        "CD3",
        "CD19",
        "PD-1",
        "PD-L1",
        "4-1BB",
        "LAG-3",
        "CD40",
        "VEGF",
        "CTLA-4",
        "FcRn",
        "TSLP",
        "BAFF",
        "TL1A",
        "IL23p19",
        "APRIL",
        "CRH",
        "MSLN",
        "BDCA2",
        "TACI",
        "ADAM9",
        "CDH17",
        "CD38",
        "GPRC5D",
        "DLL3",
    )
    parenthetical = re.search(r"\(([^)]{1,80})\)", context)
    if parenthetical:
        found_local = _targets_in_context_order(parenthetical.group(1), targets)
        if found_local:
            return "/".join(dict.fromkeys(found_local))
    lowered = re.sub(r"\s+", " ", context).lower()
    anti_match = re.search(r"\banti-([a-z0-9-]{2,20})", lowered)
    if anti_match:
        anti_target = anti_match.group(1).replace("-", "")
        for target in targets:
            if anti_target == target.lower().replace("-", ""):
                return target
    found = _targets_in_context_order(lowered, targets)
    if "PD-L1" in found and "4-1BB" in found and "PD-1" in found:
        found = [target for target in found if target != "PD-1"]
    return "/".join(dict.fromkeys(found)) if found else None


def _targets_in_context_order(
    context: str,
    targets: tuple[str, ...],
) -> list[str]:
    lowered = context.casefold()
    found: list[tuple[int, str]] = []
    for target in targets:
        index = lowered.find(target.casefold())
        if index != -1:
            found.append((index, target))
    return [target for _, target in sorted(found)]


def _mechanism_from_context(
    context: str, *, target: str | None = None
) -> str | None:
    lowered = re.sub(r"\s+", " ", context).lower()
    if not target and "undisclosed" in lowered:
        return "undisclosed target"
    return None


def _modality_from_context(context: str) -> str | None:
    lowered = context.lower()
    if "tce-adc" in lowered or "tce adc" in lowered:
        return "TCE-ADC"
    if "bsadc" in lowered:
        return "bispecific ADC"
    if "triab" in lowered or "trispecific" in lowered:
        return "trispecific antibody"
    if "fusion protein" in lowered:
        if "bispecific" in lowered:
            return "bispecific fusion protein"
        return "fusion protein"
    if "adc" in lowered:
        return "ADC"
    if "vaccine" in lowered:
        return "vaccine"
    if "bsab" in lowered:
        return "bispecific antibody"
    if "bispecific" in lowered:
        return "bispecific antibody"
    if "mab" in lowered:
        return "antibody"
    if "antibody" in lowered:
        return "antibody"
    return None


def _phase_from_context(context: str) -> str | None:
    normalized = re.sub(r"\s+", " ", context)
    normalized = re.sub(
        r"Discovery\s*/\s*Preclinical\s+IND-Enabling\s+Phase\s+I\s+"
        r"Phase\s+II\s+Registrational\s*/\s+Phase\s+III\s+"
        r"Current Status/Upcoming Milestone",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    if re.search(r"\b(BLA|Biologics License Application)\b", normalized):
        lowered = normalized.lower()
        if "under review" in lowered:
            return "BLA under review"
        if "accepted" in lowered:
            return "BLA accepted"
        if "submission" in lowered or "submit" in lowered:
            return "BLA planned"
    phase_matches = re.findall(
        r"Phase\s+([123I/abAB]+)(?!\.\d)",
        normalized,
        flags=re.IGNORECASE,
    )
    if phase_matches:
        phases = [f"Phase {match}" for match in phase_matches]
        return max(phases, key=_phase_rank)
    if re.search(
        r"\bIND\b.{0,120}\bapproved\b|\bapproved\b.{0,120}\bIND\b",
        context,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        return "IND approved"
    if re.search(
        r"\bIND\b.{0,120}\baccepted\b|\baccepted\b.{0,120}\bIND\b",
        context,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        return "IND accepted"
    if "clinical-stage" in context.lower():
        return "clinical-stage"
    lowered = context.lower()
    if "ind-enabling" in lowered or "ind enabling" in lowered:
        return "IND-enabling"
    if "pcc nomination" in lowered:
        return "PCC nomination"
    if "preclinical" in lowered or "pre-clinical" in lowered:
        return "preclinical"
    return None


def _phase_from_asset_context(*, context: str, asset_name: str) -> str | None:
    local_context = _local_asset_context(context=context, asset_name=asset_name)
    phase = _phase_from_context(local_context)
    if phase:
        return phase
    match = re.search(rf"\b{re.escape(asset_name)}\b", context)
    if not match:
        return None
    left = context[max(0, match.start() - 160): match.start()]
    same_sentence_left = re.split(r"[\n.;]", left)[-1]
    return _phase_from_context(same_sentence_left + context[match.start(): match.end()])


def _indication_from_context(context: str) -> str | None:
    context = re.split(r"\bAbbreviations:", context, flags=re.IGNORECASE)[0]
    terms = (
        "breast cancer",
        "EP-NEC",
        "SCLC",
        "NSCLC",
        "NPC",
        "HNSCC",
        "mCRPC",
        "cervical cancer",
        "ovarian cancer",
        "gastrointestinal tumors",
        "gastrointestinal cancers",
        "gastric cancer",
        "colorectal cancer",
        "pancreatic cancer",
        "neuroendocrine carcinoma",
        "systemic lupus erythematosus",
        "multiple myeloma",
        "solid tumors",
        "autoimmune diseases",
        "atopic dermatitis",
        "myasthenia gravis",
        "asthma",
        "COPD",
        "gMG",
        "IBD",
        "IgAN",
        "MM",
        "mCRC",
        "HCC",
        "CRC",
        "NEN",
        "melanoma",
        "CNS diseases",
        "obesity",
    )
    found = [
        term
        for term in terms
        if _term_in_context(term=term, context=context)
    ]
    if "breast cancer" not in found and re.search(r"\bBC\b", context):
        found.append("breast cancer")
    if (
        "solid tumors" not in found
        and re.search(r"\bMono\s*Solid\s*Tumors\b", context, flags=re.IGNORECASE)
    ):
        found.append("solid tumors")
    if (
        "systemic lupus erythematosus" not in found
        and re.search(r"\bSLE\b", context)
    ):
        found.append("systemic lupus erythematosus")
    if "IBD" not in found and re.search(
        r"\b(?:Global|China|US|Greater\s+China)\s*IBD\b",
        context,
        flags=re.IGNORECASE,
    ):
        found.append("IBD")
    if "autoimmune diseases" not in found and re.search(
        r"\b(?:Global|China|US|Greater\s+China)\s*Autoimmune\s+Diseases\b",
        context,
        flags=re.IGNORECASE,
    ):
        found.append("autoimmune diseases")
    return "; ".join(dict.fromkeys(found)) if found else None


def _term_in_context(*, term: str, context: str) -> bool:
    pattern = r"\b" + re.escape(term).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(pattern, context, flags=re.IGNORECASE))


def _geography_from_context(context: str) -> str | None:
    found = []
    for term in ("China", "U.S.", "EU", "Australia", "global"):
        if term.lower() in context.lower():
            found.append(term)
    return "; ".join(dict.fromkeys(found)) if found else None


def _partner_from_context(context: str) -> str | None:
    partners = (
        "BioNTech",
        "BNT",
        "3SBIO",
        "Kelun",
        "Windward",
        "Solstice",
        "Otsuka",
        "Spruce",
        "Dianthus",
    )
    found = [partner for partner in partners if partner.lower() in context.lower()]
    return "; ".join(dict.fromkeys(found)) if found else None


def _milestone_from_context(
    context: str, *, as_of_year: int | None = None
) -> str | None:
    normalized = re.sub(r"\s+", " ", context).lower()
    quarter_names = {
        "first": "Q1",
        "second": "Q2",
        "third": "Q3",
        "fourth": "Q4",
    }
    bla_quarter = re.search(
        r"\bbla submission\b.{0,100}\b(first|second|third|fourth) "
        r"quarter of (20\d{2})",
        normalized,
    )
    if bla_quarter:
        quarter = quarter_names[bla_quarter.group(1)]
        year = int(bla_quarter.group(2))
        return f"BLA submission in {quarter} {year}"
    pcc_half = re.search(
        r"\bpcc nomination\b.{0,120}\b(first half|h1) (?:of )?(20\d{2})",
        normalized,
    )
    if pcc_half:
        year = int(pcc_half.group(2))
        return f"PCC nomination in H1 {year}"
    planned_start = re.search(r"\bplanned to start in (20\d{2})\b", normalized)
    if planned_start:
        year = int(planned_start.group(1))
        if as_of_year is not None and year < as_of_year - 1:
            return None
        return f"planned to start in {year}"
    if not any(
        token in normalized
        for token in (
            "planned",
            "start",
            "initiat",
            "present",
            "readout",
            "submit",
            "approval",
            "expected",
            "milestone",
            "data",
        )
    ):
        return None
    match = re.search(r"\b(in|during)\s+(20\d{2})\b", normalized)
    if match:
        preposition = match.group(1)
        year = int(match.group(2))
        # Reject obviously stale legacy years that leak from historical
        # narrative sections (e.g. "in 2017") into current asset rows.
        if as_of_year is not None and year < as_of_year - 1:
            return None
        return f"{preposition} {year}"
    return None


def _year_from_source_date(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value)
    match = re.match(r"^(\d{4})", text)
    if not match:
        return None
    return int(match.group(1))


def _clean_claim(context: str) -> str:
    return re.sub(r"\s+", " ", context).strip()[:700]


def _context_window(
    text: str,
    start: int,
    end: int,
    size: int = 700,
    left_size: int = 180,
    left_boundary: int | None = None,
    right_boundary: int | None = None,
) -> str:
    left = max(0, start - left_size)
    if left_boundary is not None:
        left = max(left, left_boundary)
    right = min(len(text), end + size)
    if right_boundary is not None:
        right = min(right, right_boundary)
    return text[left:right]


def _biotech_context(context: str) -> bool:
    keywords = (
        "trial",
        "clinical",
        "phase",
        "adc",
        "antibody",
        "tumor",
        "cancer",
        "patients",
        "pipeline",
        "fda",
        "ind",
        "bla",
        "bsab",
        "mab",
    )
    lowered = context.lower()
    return any(keyword in lowered for keyword in keywords)


def _payload_only_context(*, name: str, context: str) -> bool:
    if re.search(
        rf"\bpayloads?\b.{{0,80}}\b{re.escape(name)}\b"
        rf"|\b{name}\s+exposures\b",
        context,
        flags=re.IGNORECASE,
    ):
        return True
    return False


def _listing_warning_context(*, context: str) -> bool:
    lowered = context.lower()
    return "warning under rule 18a" in lowered or "no assurance that" in lowered


def _combination_partner_context(*, name: str, context: str) -> bool:
    if not re.match(r"^[A-Z]{2,6}\d{3,5}$", name):
        return False
    return bool(
        re.search(
            rf"\bin combination with\s+{re.escape(name)}\b",
            context,
            flags=re.IGNORECASE,
        )
    )


def _nearby_text(text: str, start: int, end: int, size: int = 120) -> str:
    return text[max(0, start - size): min(len(text), end + size)]


def _looks_like_non_asset_code(value: str) -> bool:
    compact = value.replace("-", "")
    prefixes = ("NCT", "RMB", "HKD", "USD")
    return compact.isdigit() or any(compact.startswith(prefix) for prefix in prefixes)


def _looks_like_merged_target_code(value: str) -> bool:
    prefix = value.split("-", 1)[0]
    if not prefix.endswith("DB"):
        return False
    target_fragment = prefix[:-2]
    return target_fragment in {"GFR", "EGFR", "HER", "VEGF"}


def _looks_like_merged_modality_code(value: str) -> bool:
    for prefix in ("ADC", "BSAB", "MAB"):
        if value.startswith(prefix):
            suffix = value[len(prefix):]
            if re.match(r"^[A-Z]{2,6}-?\d{3,5}$", suffix):
                return True
    return False


def _financial_multiplier(text: str) -> int:
    thousand_markers = (
        "RMB’000",
        "RMB'000",
        "USD’000",
        "USD'000",
        "US$’000",
        "US$'000",
        "HK$’000",
        "HK$'000",
        "HKD’000",
        "HKD'000",
    )
    return 1000 if any(marker in text for marker in thousand_markers) else 1


def _financial_currency(text: str) -> str:
    head = text[:5000]
    if "USD" in head or "US$" in head:
        return "USD"
    if "RMB" in head:
        return "RMB"
    if "HK$" in head or "HKD" in head:
        return "HKD"
    return "HKD"


def _financial_as_of_date(text: str) -> str | None:
    date_pattern = (
        r"(?:[A-Z][a-z]+\s+\d{1,2},\s+20\d{2}"
        r"|\d{1,2}\s+[A-Z][a-z]+\s+20\d{2})"
    )
    match = re.search(rf"As at\s+({date_pattern})", text)
    if not match:
        match = re.search(rf"year ended\s+({date_pattern})", text)
    if not match:
        return None
    return _parse_english_date(match.group(1))


def _first_amount(
    text: str,
    patterns: tuple[str, ...],
    *,
    multiplier: int,
) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _amount(match.group(1)) * multiplier
    return None


def _signed_amount_after_label(
    text: str,
    label: str,
    *,
    multiplier: int,
) -> float | None:
    match = re.search(
        re.escape(label) + r"\s+\(?([\d,]+)\)?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    amount = _amount(match.group(1)) * multiplier
    return -amount if "outflow" in label.lower() else amount


def _amount(value: str) -> float:
    return float(value.replace(",", ""))


def _announcement_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value)
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def _parse_english_date(value: str) -> str | None:
    months = {
        "january": "01",
        "february": "02",
        "march": "03",
        "april": "04",
        "may": "05",
        "june": "06",
        "july": "07",
        "august": "08",
        "september": "09",
        "october": "10",
        "november": "11",
        "december": "12",
    }
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2}),\s+(20\d{2})", value)
    if match:
        month, day, year = match.groups()
    else:
        match = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(20\d{2})", value)
        if not match:
            return None
        day, month, year = match.groups()
    month_number = months.get(month.lower())
    if not month_number:
        return None
    return f"{year}-{month_number}-{int(day):02d}"


def _ticker_code(ticker: str) -> str:
    match = re.search(r"(\d+)", ticker)
    return match.group(1).zfill(5) if match else ""


def _slug(value: str | None) -> str:
    if not value:
        return "company"
    return re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")


def _safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_")[:80]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(_jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_competitor_discovery_file(
    path: Path,
) -> tuple[list[dict[str, Any]], str | None]:
    if not path.exists():
        return [], None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - degrade candidate ingestion.
        return [], f"competitor discovery candidate file unreadable: {exc}"
    rows = payload.get("candidates") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return [], "competitor discovery candidate file must contain candidates list"
    candidates = [row for row in rows if isinstance(row, dict)]
    skipped = len(rows) - len(candidates)
    if skipped:
        return candidates, f"ignored {skipped} non-object discovery candidates"
    return candidates, None


def _competitor_discovery_needs_refresh(
    path: Path,
    *,
    competitor_payload: dict[str, Any],
    max_requests: int,
) -> bool:
    try:
        payload = _read_json(path)
    except Exception:  # noqa: BLE001 - invalid generated draft can be refreshed.
        return True
    if (
        payload.get("generated_by")
        != "auto_inputs.clinicaltrials_competitor_discovery"
    ):
        return True
    if payload.get("generated_extractor_version") != COMPETITOR_EXTRACTOR_VERSION:
        return True
    if payload.get("max_requests") != max_requests:
        return True
    expected_targets = _request_targets(
        competitor_payload.get("discovery_requests")
    )[:max_requests]
    actual_targets = _request_targets(payload.get("requests_searched"))
    return expected_targets != actual_targets


def _request_targets(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    targets = [
        str(item.get("target") or "").strip()
        for item in value
        if isinstance(item, dict) and str(item.get("target") or "").strip()
    ]
    return tuple(dict.fromkeys(targets))


def _pipeline_draft_needs_refresh(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = _read_json(path)
    except Exception:  # noqa: BLE001 - invalid generated draft can be refreshed.
        return True
    if payload.get("generated_by") == "auto_inputs.hkex_annual_results":
        if payload.get("generated_extractor_version") != PIPELINE_EXTRACTOR_VERSION:
            return True
    try:
        report = validate_pipeline_asset_file(path)
    except Exception:  # noqa: BLE001 - invalid generated draft can be refreshed.
        return True
    refresh_markers = (
        "next_milestone contains newline/control characters",
        "next_milestone year looks stale",
    )
    return any(
        any(marker in warning for marker in refresh_markers)
        for warning in report.warnings
    )


def _competitor_draft_needs_refresh(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = _read_json(path)
    except Exception:  # noqa: BLE001 - invalid generated draft can be refreshed.
        return True
    if payload.get("generated_by") == "auto_inputs.target_overlap_seed":
        return (
            payload.get("generated_extractor_version")
            != COMPETITOR_EXTRACTOR_VERSION
        )
    return False


def _target_price_draft_needs_refresh(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = _read_json(path)
    except Exception:  # noqa: BLE001 - invalid generated draft can be refreshed.
        return True
    if payload.get("generated_by") == "auto_inputs.default_rnpv":
        return (
            payload.get("generated_extractor_version")
            != TARGET_PRICE_EXTRACTOR_VERSION
        )
    return False


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
