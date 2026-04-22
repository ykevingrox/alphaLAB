"""Automatic source discovery and draft input generation."""

from __future__ import annotations

import io
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

import requests
from pypdf import PdfReader

from biotech_alpha.company_report import CompanyIdentity
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


MarketDataProvider = Callable[[CompanyIdentity], dict[str, Any] | None]


HKEX_BASE_URL = "https://www1.hkexnews.hk"
HKEX_ACTIVE_STOCKS_URL = (
    f"{HKEX_BASE_URL}/ncms/script/eds/activestock_sehk_e.json"
)
HKEX_TITLE_SEARCH_URL = f"{HKEX_BASE_URL}/search/titleSearchServlet.do"


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
    financials: Path | None = None
    conference_catalysts: Path | None = None
    valuation: Path | None = None
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
    financials_path = generated_input_dir / f"{slug}_financials.json"
    conference_path = generated_input_dir / f"{slug}_conference_catalysts.json"
    valuation_path = generated_input_dir / f"{slug}_valuation.json"

    if overwrite or not pipeline_path.exists():
        _write_json(
            pipeline_path,
            draft_pipeline_assets(
                identity=identity,
                text=text,
                source=document,
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

    valuation_warnings: list[str] = []
    valuation_written_path: Path | None = None
    if market_data_provider is not None and (
        overwrite or not valuation_path.exists()
    ):
        payload, provider_warnings = _safe_market_data_payload(
            provider=market_data_provider,
            identity=identity,
        )
        valuation_warnings.extend(provider_warnings)
        if payload is not None:
            draft = draft_valuation_snapshot(
                identity=identity,
                market_data=payload,
            )
            valuation_warnings.extend(draft["warnings"])
            if draft.get("writeable"):
                _write_json(valuation_path, draft["payload"])
                valuation_written_path = valuation_path

    if valuation_written_path is None and valuation_path.exists():
        valuation_written_path = valuation_path

    validation = {
        "pipeline_assets": validation_report_as_dict(
            validate_pipeline_asset_file(pipeline_path)
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

    generated_inputs: dict[str, Path] = {
        "pipeline_assets": pipeline_path,
        "financials": financials_path,
        "conference_catalysts": conference_path,
    }
    if valuation_written_path is not None:
        generated_inputs["valuation"] = valuation_written_path

    manifest_path = processed_dir / f"{date.today().isoformat()}_source_manifest.json"
    _write_json(
        manifest_path,
        {
            "identity": asdict(identity),
            "source_documents": [asdict(document)],
            "generated_inputs": generated_inputs,
            "validation": validation,
            "warnings": list(valuation_warnings),
        },
    )
    return AutoInputArtifacts(
        source_manifest=manifest_path,
        pipeline_assets=pipeline_path,
        financials=financials_path,
        conference_catalysts=conference_path,
        valuation=valuation_written_path,
        validation=validation,
        source_documents=(document,),
        warnings=tuple(valuation_warnings),
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
        primary, aliases = _split_asset_codes(match["name"])
        key = primary.casefold()
        existing_key = seen_codes.get(key)
        context = match["context"]
        candidate = _draft_asset_from_context(
            primary=primary,
            aliases=aliases,
            context=context,
            source=source,
        )
        if existing_key:
            _merge_asset_fields(seen_assets[existing_key], candidate)
            _merge_asset_aliases(seen_assets[existing_key], aliases)
            for alias in aliases:
                seen_codes[alias.casefold()] = existing_key
            continue
        if len(assets) >= 12:
            continue
        assets.append(candidate)
        seen_assets[key] = candidate
        seen_codes[key] = key
        for alias in aliases:
            seen_codes[alias.casefold()] = key

    return {
        "company": identity.company,
        "ticker": identity.ticker,
        "generated_by": "auto_inputs.hkex_annual_results",
        "needs_human_review": True,
        "assets": assets,
    }


def _draft_asset_from_context(
    *,
    primary: str,
    aliases: list[str],
    context: str,
    source: SourceDocument,
) -> dict[str, Any]:
    local_context = _local_asset_context(context=context, asset_name=primary)
    packed_context = _packed_left_context(context=context, asset_name=primary)
    target = _target_from_context(local_context)
    modality = _modality_from_context(local_context)
    indication = _indication_from_context(local_context)
    if packed_context:
        target = _target_from_context(packed_context)
        modality = _modality_from_context(packed_context)
        indication = _indication_from_context(packed_context) or indication
    return {
        "name": primary,
        "aliases": aliases,
        "target": target,
        "modality": modality,
        "mechanism": None,
        "indication": indication,
        "phase": _phase_from_asset_context(
            context=context,
            asset_name=primary,
        ),
        "geography": _geography_from_context(context),
        "rights": None,
        "partner": _partner_from_context(context),
        "next_milestone": _milestone_from_context(context),
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
    return context[match.start(): match.start() + size]


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
    pattern = rf"(?<![A-Za-z-]){re.escape(asset_name)}\b"
    return re.search(pattern, context)


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
        if not existing.get(key) and candidate.get(key):
            existing[key] = candidate[key]


def _merge_asset_aliases(existing: dict[str, Any], aliases: list[str]) -> None:
    existing_aliases = existing.get("aliases")
    if not isinstance(existing_aliases, list):
        existing["aliases"] = []
        existing_aliases = existing["aliases"]
    for alias in aliases:
        if alias != existing.get("name") and alias not in existing_aliases:
            existing_aliases.append(alias)


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
        if _combination_partner_context(
            name=name,
            context=_nearby_text(text, match.start(), match.end()),
        ):
            continue
        context = _context_window(
            text,
            match.start(),
            match.end(),
            left_boundary=previous_match.end() if previous_match else None,
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


def _target_from_context(context: str) -> str | None:
    context = re.sub(r"I\s+L23p19", "IL23p19", context)
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
        "CD40",
        "VEGF",
        "CTLA-4",
        "FcRn",
        "TSLP",
        "TL1A",
        "IL23p19",
        "APRIL",
        "MSLN",
        "BDCA2",
        "ADAM9",
        "CDH17",
    )
    parenthetical = re.search(r"\(([^)]{1,80})\)", context)
    if parenthetical:
        local = parenthetical.group(1).lower()
        found_local = [target for target in targets if target.lower() in local]
        if found_local:
            return "/".join(dict.fromkeys(found_local))
    lowered = re.sub(r"\s+", " ", context).lower()
    found = [target for target in targets if target.lower() in lowered]
    return "/".join(dict.fromkeys(found)) if found else None


def _modality_from_context(context: str) -> str | None:
    lowered = context.lower()
    if "bsadc" in lowered:
        return "bispecific ADC"
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
    match = re.search(r"Phase\s+([123I/abAB]+)", context, flags=re.IGNORECASE)
    if match:
        return f"Phase {match.group(1)}"
    if "clinical-stage" in context.lower():
        return "clinical-stage"
    lowered = context.lower()
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
    terms = (
        "breast cancer",
        "NSCLC",
        "mCRPC",
        "cervical cancer",
        "ovarian cancer",
        "gastrointestinal tumors",
        "gastric cancer",
        "colorectal cancer",
        "pancreatic cancer",
        "systemic lupus erythematosus",
        "solid tumors",
        "autoimmune diseases",
        "atopic dermatitis",
        "myasthenia gravis",
        "asthma",
        "COPD",
        "gMG",
        "IBD",
        "IgAN",
        "mCRC",
        "HCC",
        "CRC",
        "NEN",
        "melanoma",
        "CNS diseases",
        "obesity",
    )
    lowered = re.sub(r"\s+", " ", context).lower()
    found = [term for term in terms if term.lower() in lowered]
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
    return "; ".join(dict.fromkeys(found)) if found else None


def _geography_from_context(context: str) -> str | None:
    found = []
    for term in ("China", "U.S.", "EU", "Australia", "global"):
        if term.lower() in context.lower():
            found.append(term)
    return "; ".join(dict.fromkeys(found)) if found else None


def _partner_from_context(context: str) -> str | None:
    partners = ("BioNTech", "BNT", "3SBIO", "Kelun", "Windward")
    found = [partner for partner in partners if partner.lower() in context.lower()]
    return "; ".join(dict.fromkeys(found)) if found else None


def _milestone_from_context(context: str) -> str | None:
    if "planned to start in 2026" in context:
        return "planned to start in 2026"
    match = re.search(r"(?:in|during)\s+(20\d{2})", context)
    if match:
        return match.group(0)
    return None


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
