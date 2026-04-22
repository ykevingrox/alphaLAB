from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from biotech_alpha.auto_inputs import (
    SourceDocument,
    _resolve_hkex_stock_id,
    draft_conference_catalysts,
    draft_financial_snapshot,
    draft_pipeline_assets,
    generate_auto_inputs,
)
from biotech_alpha.company_report import CompanyIdentity


SAMPLE_TEXT = """
FINANCIAL HIGHLIGHTS
For the year ended December 31, 2025
RMB'000
Revenue 1,851,735 1,941,257
Adjusted loss for the year (388,769) (177,018)
As at December 31, 2025
Cash and Bank Balances 2 3,324,529 1,435,827
Bank borrowings 141,056 -

BUSINESS HIGHLIGHTS
First-Wave Assets: Pivotal Clinical and Regulatory Progress
Trastuzumab pamirtecan (DB-1303/BNT323) Met Primary Endpoint in Phase 3 Trial.
This trial evaluates DB-1303/BNT323 versus T-DM1 in China in patients with
HER2+ unresectable and/or metastatic breast cancer.
DB-1311/BNT324 (B7-H3 ADC) Clinical Readouts in mCRPC and Beyond.
The first global Phase 3 trial evaluating DB-1311/BNT324 compared with
docetaxel in patients with taxane-naive mCRPC is planned to start in 2026.
DB-1310 (HER3 ADC) Clinical Readouts in NSCLC and breast cancer.
The company plans to present updated data at ASCO 2026.
DB-2304 (BDCA2 ADC): A global Phase 1/2a clinical trial in SLE patients.
DB-1317 (ADAM9 ADC): A global Phase 1a/1b clinical trial in solid tumors.
DB-1324 (CDH17 ADC): A global Phase 1/2 trial in gastrointestinal tumors.
DB-2304 payload P2025 exposures increased dose-proportionally.
Proprietary payloads P1003 and P1021 improved systemic stability.
DB-1311/BNT324 is being evaluated in combination with BNT116.
B7-H4 DB-1312/BG-C9074 Global mono solid tumors.
HER3 xE GFRDB-1418 table artifact.
"""


class AutoInputsTest(unittest.TestCase):
    def test_drafts_pipeline_assets_from_source_text(self) -> None:
        payload = draft_pipeline_assets(
            identity=CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            text=SAMPLE_TEXT,
            source=_source(),
        )

        names = [asset["name"] for asset in payload["assets"]]

        self.assertIn("DB-1303", names)
        self.assertIn("DB-1311", names)
        self.assertIn("DB-1310", names)
        self.assertIn("DB-2304", names)
        self.assertIn("DB-1317", names)
        self.assertIn("DB-1324", names)
        self.assertNotIn("P2025", names)
        self.assertNotIn("P1003", names)
        self.assertNotIn("P1021", names)
        self.assertNotIn("BNT116", names)
        self.assertNotIn("C9074", names)
        self.assertNotIn("GFRDB-1418", names)
        first = payload["assets"][0]
        self.assertEqual(first["aliases"], ["BNT323"])
        self.assertEqual(first["target"], "HER2")
        self.assertEqual(first["phase"], "Phase 3")
        self.assertIn("breast cancer", first["indication"])
        self.assertTrue(first["evidence"][0]["is_inferred"])
        db2304 = _asset_by_name(payload, "DB-2304")
        self.assertEqual(db2304["target"], "BDCA2")
        self.assertEqual(db2304["phase"], "Phase 1/2a")
        self.assertIn("systemic lupus erythematosus", db2304["indication"])
        self.assertEqual(_asset_by_name(payload, "DB-1317")["target"], "ADAM9")
        self.assertEqual(_asset_by_name(payload, "DB-1324")["target"], "CDH17")
        self.assertIn("solid tumors", _asset_by_name(payload, "DB-1312")["indication"])

    def test_drafts_pipeline_assets_enriches_repeated_asset_mentions(self) -> None:
        text = """
        DB-9999 (HER2 ADC) Clinical readout in breast cancer.
        DB-8888 (TROP2 ADC) Clinical readout in solid tumors.
        A global Phase 2 clinical trial evaluates DB-9999 in breast cancer.
        """
        payload = draft_pipeline_assets(
            identity=CompanyIdentity(company="Example Bio", ticker="9999.HK"),
            text=text,
            source=_source(),
        )

        names = [asset["name"] for asset in payload["assets"]]
        self.assertEqual(names.count("DB-9999"), 1)
        self.assertEqual(_asset_by_name(payload, "DB-9999")["phase"], "Phase 2")

    def test_drafts_financial_snapshot_from_source_text(self) -> None:
        payload = draft_financial_snapshot(
            identity=CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            text=SAMPLE_TEXT,
            source=_source(),
        )

        self.assertEqual(payload["as_of_date"], "2025-12-31")
        self.assertEqual(payload["currency"], "RMB")
        self.assertEqual(payload["cash_and_equivalents"], 3324529000)
        self.assertEqual(payload["short_term_debt"], 141056000)
        self.assertEqual(payload["quarterly_cash_burn"], 97192250)
        self.assertTrue(payload["needs_human_review"])

    def test_drafts_conference_catalysts_from_source_text(self) -> None:
        payload = draft_conference_catalysts(
            identity=CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            text=SAMPLE_TEXT,
            source=_source(),
        )
        self.assertTrue(payload["needs_human_review"])
        self.assertEqual(len(payload["catalysts"]), 1)
        self.assertEqual(payload["catalysts"][0]["category"], "conference")
        self.assertIn("ASCO", payload["catalysts"][0]["title"])

    def test_generate_auto_inputs_with_fixture_source_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_dir = root / "raw_fixture"
            raw_dir.mkdir()
            source = _source(
                file_path=raw_dir / "results.pdf",
                text_path=raw_dir / "results.txt",
            )
            source.file_path.write_bytes(b"%PDF fixture")
            source.text_path.write_text(SAMPLE_TEXT, encoding="utf-8")

            with patch(
                "biotech_alpha.auto_inputs._resolve_hkex_stock_id",
                return_value="12345",
            ) as resolve:
                with patch(
                    "biotech_alpha.auto_inputs._latest_hkex_annual_result",
                    return_value={"NEWS_ID": "fixture"},
                ) as latest:
                    with patch(
                        "biotech_alpha.auto_inputs._download_and_extract_document",
                        return_value=source,
                    ) as download:
                        artifacts = generate_auto_inputs(
                            identity=CompanyIdentity(
                                company="DualityBio",
                                ticker="09606.HK",
                            ),
                            input_dir=root / "generated",
                            output_dir=root / "out",
                        )

            resolve.assert_called_once()
            latest.assert_called_once()
            download.assert_called_once()
            self.assertEqual(artifacts.warnings, ())
            self.assertIsNotNone(artifacts.pipeline_assets)
            self.assertIsNotNone(artifacts.financials)
            self.assertIsNotNone(artifacts.conference_catalysts)
            self.assertIsNotNone(artifacts.source_manifest)

            pipeline = _read_json(artifacts.pipeline_assets)
            financials = _read_json(artifacts.financials)
            conference = _read_json(artifacts.conference_catalysts)
            manifest = _read_json(artifacts.source_manifest)

            self.assertEqual(pipeline["assets"][0]["name"], "DB-1303")
            self.assertEqual(financials["cash_and_equivalents"], 3324529000)
            self.assertEqual(conference["catalysts"][0]["category"], "conference")
            self.assertIn("pipeline_assets", manifest["generated_inputs"])

    def test_generate_auto_inputs_skips_non_hk_identity_without_network(self) -> None:
        with patch("requests.Session") as session:
            artifacts = generate_auto_inputs(
                identity=CompanyIdentity(
                    company="Example Bio",
                    ticker="EXM",
                    market="US",
                ),
            )

        session.assert_not_called()
        self.assertTrue(artifacts.warnings)

    def test_hkex_stock_resolution_retries_transient_request_errors(self) -> None:
        session = _RetrySession(
            responses=[
                requests.Timeout("temporary timeout"),
                _JsonResponse([{"c": "9606", "i": "12345"}]),
            ]
        )

        with patch("biotech_alpha.auto_inputs.time.sleep") as sleep:
            stock_id = _resolve_hkex_stock_id(
                session,
                "09606",
                timeout=5,
            )

        self.assertEqual(stock_id, "12345")
        self.assertEqual(session.call_count, 2)
        sleep.assert_called_once()


def _source(
    *,
    file_path: Path = Path("results.pdf"),
    text_path: Path = Path("results.txt"),
) -> SourceDocument:
    return SourceDocument(
        source_type="hkex_annual_results",
        title="Annual Results",
        url="https://example.com/results.pdf",
        publication_date="2026-03-23",
        file_path=file_path,
        text_path=text_path,
        stock_code="09606",
        stock_name="DUALITYBIO-B",
    )


def _read_json(path: Path | None) -> dict:
    if path is None:
        raise AssertionError("expected a generated path")
    return json.loads(path.read_text(encoding="utf-8"))


def _asset_by_name(payload: dict, name: str) -> dict:
    for asset in payload["assets"]:
        if asset["name"] == name:
            return asset
    raise AssertionError(f"missing asset {name}")


class _JsonResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class _RetrySession:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.call_count = 0

    def get(self, *_args: object, **_kwargs: object) -> object:
        self.call_count += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


if __name__ == "__main__":
    unittest.main()
