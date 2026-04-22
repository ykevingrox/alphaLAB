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
    draft_competitor_assets,
    draft_conference_catalysts,
    draft_financial_snapshot,
    draft_pipeline_assets,
    draft_valuation_snapshot,
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
docetaxel in patients with taxane-naive mCRPC is planned to start in
2026.
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

HBM_SAMPLE_TEXT = """
FINANCIAL HIGHLIGHTS
For the year ended 31 December 2025
USD'000
Profit for the year 92,221 2,742
Cash and cash equivalents 403,056 166,821
Bank borrowings - unsecured 56,005 17,480 73,485

ROBUST PORTFOLIO AND DIFFERENTIATED PIPELINE
BATOCLIMAB (HBM9161) (FcRn mAb)
The BLA for generalized myasthenia gravis (gMG) was accepted.
The gMG Phase III pivotal clinical trial results were presented.
HBM9378 (TSLP mAb)
Windward Bio launched Phase II POLARIS assessing HBM9378/WIN378 for asthma.
The IND for COPD was approved by NMPA.
HBM7004 (B7H4/CD3 BsAb)
In 2025, we continued pre-clinical development and advanced to IND-enabling.
HBM7575 (TSLP undisclosed target BsAb)
The China IND application for atopic dermatitis was accepted and approved.
Global (Out-licensed) Solid Tumors MSLN ADC HBM9033 / SGN-MesoC2.
Global (Out-licensed) Solid Tumors MSLN ADCHBM9033 table artifact.
GlobalIBD*TL1A xI L23p19HBM2001
GlobalIBD*Undisclosed (mAb)J9003
GlobalAutoimmune DiseasesCD3xCD19R2006
GlobalAutoimmune Diseases Undisclosed (BsAb)R7027
Oncology/Immuno-Oncology Greater China NSCLC, HCC, NEN, CRC* CTLA-4 HBM4003.
GlobalSolid TumorsB7H7/HHLA2HBM1020
Global solid tumors CLDN18.2xCD3HBM7022/ AZD5863.
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
        self.assertEqual(
            _asset_by_name(payload, "DB-1311")["next_milestone"],
            "planned to start in 2026",
        )
        # Guard against stale legacy-year leakage from broad context windows.
        self.assertIsNone(_asset_by_name(payload, "DB-1312")["next_milestone"])

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

    def test_drafts_competitor_assets_from_pipeline_targets(self) -> None:
        identity = CompanyIdentity(company="DualityBio", ticker="09606.HK")
        source = _source()
        pipeline_payload = draft_pipeline_assets(
            identity=identity,
            text=SAMPLE_TEXT,
            source=source,
        )
        payload = draft_competitor_assets(
            identity=identity,
            pipeline_assets_payload=pipeline_payload,
            source=source,
        )

        self.assertEqual(payload["company"], "DualityBio")
        self.assertEqual(payload["generated_by"], "auto_inputs.target_overlap_seed")
        self.assertTrue(payload["needs_human_review"])
        self.assertGreaterEqual(len(payload["competitors"]), 1)
        first = payload["competitors"][0]
        self.assertIn("company", first)
        self.assertIn("asset_name", first)
        self.assertIn("target", first)
        self.assertTrue(first["evidence"][0]["is_inferred"])

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

    def test_hbm_fixture_drafts_usd_financial_snapshot(self) -> None:
        payload = draft_financial_snapshot(
            identity=CompanyIdentity(company="Harbour BioMed", ticker="02142.HK"),
            text=HBM_SAMPLE_TEXT,
            source=_hbm_source(),
        )

        self.assertEqual(payload["as_of_date"], "2025-12-31")
        self.assertEqual(payload["currency"], "USD")
        self.assertEqual(payload["cash_and_equivalents"], 403056000)
        self.assertEqual(payload["short_term_debt"], 56005000)
        self.assertIsNone(payload["quarterly_cash_burn"])
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
            self.assertIsNotNone(artifacts.competitors)
            self.assertIsNotNone(artifacts.financials)
            self.assertIsNotNone(artifacts.conference_catalysts)
            self.assertIsNotNone(artifacts.source_manifest)

            pipeline = _read_json(artifacts.pipeline_assets)
            competitors = _read_json(artifacts.competitors)
            financials = _read_json(artifacts.financials)
            conference = _read_json(artifacts.conference_catalysts)
            manifest = _read_json(artifacts.source_manifest)

            self.assertEqual(pipeline["assets"][0]["name"], "DB-1303")
            self.assertGreaterEqual(len(competitors["competitors"]), 1)
            self.assertEqual(financials["cash_and_equivalents"], 3324529000)
            self.assertEqual(conference["catalysts"][0]["category"], "conference")
            self.assertIn("pipeline_assets", manifest["generated_inputs"])
            self.assertIn("competitors", manifest["generated_inputs"])
            self.assertIn("competitors", manifest["validation"])

    def test_generate_auto_inputs_reuses_existing_pipeline_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            pipeline_path = generated_dir / "09606_hk_pipeline_assets.json"
            pipeline_path.write_text(
                json.dumps(
                    {
                        "company": "DualityBio",
                        "ticker": "09606.HK",
                        "assets": [
                            {
                                "name": "DB-1303",
                                "aliases": [],
                                "target": "HER2",
                                "modality": "ADC",
                                "indication": "breast cancer",
                                "phase": "Phase 3",
                                "partner": "BioNTech",
                                "next_milestone": None,
                                "evidence": [
                                    {
                                        "claim": "Existing generated draft",
                                        "source": "fixture.pdf",
                                        "confidence": 0.8,
                                        "is_inferred": True,
                                    }
                                ],
                            }
                        ],
                        "needs_human_review": True,
                    }
                ),
                encoding="utf-8",
            )
            source = _source(
                file_path=root / "results.pdf",
                text_path=root / "results.txt",
            )
            source.file_path.write_bytes(b"%PDF fixture")
            source.text_path.write_text(SAMPLE_TEXT, encoding="utf-8")

            with patch(
                "biotech_alpha.auto_inputs._resolve_hkex_stock_id",
                return_value="12345",
            ), patch(
                "biotech_alpha.auto_inputs._latest_hkex_annual_result",
                return_value={"NEWS_ID": "fixture"},
            ), patch(
                "biotech_alpha.auto_inputs._download_and_extract_document",
                return_value=source,
            ):
                artifacts = generate_auto_inputs(
                    identity=CompanyIdentity(
                        company="DualityBio",
                        ticker="09606.HK",
                    ),
                    input_dir=generated_dir,
                    output_dir=root / "out",
                )

            self.assertEqual(artifacts.warnings, ())
            self.assertEqual(artifacts.source_documents, (source,))
            self.assertEqual(artifacts.pipeline_assets, pipeline_path)
            competitors = _read_json(artifacts.competitors)
            self.assertGreaterEqual(len(competitors["competitors"]), 1)

    def test_generate_auto_inputs_refreshes_stale_generated_pipeline(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            generated_dir = root / "generated"
            generated_dir.mkdir()
            pipeline_path = generated_dir / "09606_hk_pipeline_assets.json"
            pipeline_path.write_text(
                json.dumps(
                    {
                        "company": "DualityBio",
                        "ticker": "09606.HK",
                        "generated_by": "auto_inputs.hkex_annual_results",
                        "assets": [
                            {
                                "name": "DB-1312",
                                "aliases": [],
                                "target": "B7-H4",
                                "modality": "ADC",
                                "indication": "solid tumors",
                                "phase": "Phase 1",
                                "next_milestone": "in \n2017",
                                "evidence": [
                                    {
                                        "claim": "Stale generated draft",
                                        "source": "fixture.pdf",
                                        "source_date": "2026-03-23",
                                        "confidence": 0.8,
                                        "is_inferred": True,
                                    }
                                ],
                            }
                        ],
                        "needs_human_review": True,
                    }
                ),
                encoding="utf-8",
            )
            source = _source(
                file_path=root / "results.pdf",
                text_path=root / "results.txt",
            )
            source.file_path.write_bytes(b"%PDF fixture")
            source.text_path.write_text(SAMPLE_TEXT, encoding="utf-8")

            with patch(
                "biotech_alpha.auto_inputs._resolve_hkex_stock_id",
                return_value="12345",
            ), patch(
                "biotech_alpha.auto_inputs._latest_hkex_annual_result",
                return_value={"NEWS_ID": "fixture"},
            ), patch(
                "biotech_alpha.auto_inputs._download_and_extract_document",
                return_value=source,
            ):
                artifacts = generate_auto_inputs(
                    identity=CompanyIdentity(
                        company="DualityBio",
                        ticker="09606.HK",
                    ),
                    input_dir=generated_dir,
                    output_dir=root / "out",
                )

            refreshed = _read_json(artifacts.pipeline_assets)
            self.assertEqual(
                _asset_by_name(refreshed, "DB-1311")["next_milestone"],
                "planned to start in 2026",
            )
            self.assertIsNone(
                _asset_by_name(refreshed, "DB-1312")["next_milestone"]
            )

    def test_draft_valuation_snapshot_from_market_data_payload(self) -> None:
        market_data = {
            "as_of_date": "2026-04-22",
            "currency": "HKD",
            "market_cap": 25_000_000_000,
            "share_price": 35.2,
            "shares_outstanding": 710_000_000,
            "source": "https://example.com/09606-quote",
            "source_date": "2026-04-22",
            "financials": {
                "cash_and_equivalents": 1_200_000_000,
                "total_debt": 300_000_000,
                "revenue_ttm": 1_500_000_000,
            },
        }
        result = draft_valuation_snapshot(
            identity=CompanyIdentity(company="DualityBio", ticker="09606.HK"),
            market_data=market_data,
        )

        payload = result["payload"]
        self.assertEqual(result["warnings"], [])
        self.assertTrue(result["writeable"])
        self.assertEqual(payload["company"], "DualityBio")
        self.assertEqual(payload["market_cap"], 25_000_000_000)
        self.assertEqual(payload["cash_and_equivalents"], 1_200_000_000)
        self.assertEqual(payload["source"], "https://example.com/09606-quote")
        self.assertEqual(
            payload["generated_by"], "auto_inputs.market_data_provider"
        )
        self.assertTrue(payload["needs_human_review"])

    def test_generate_auto_inputs_with_market_data_provider(self) -> None:
        provider_calls: list[CompanyIdentity] = []

        def provider(identity: CompanyIdentity) -> dict[str, object]:
            provider_calls.append(identity)
            return {
                "as_of_date": "2026-04-22",
                "currency": "HKD",
                "market_cap": 25_000_000_000,
                "source": "https://example.com/09606-quote",
                "source_date": "2026-04-22",
                "financials": {
                    "cash_and_equivalents": 1_200_000_000,
                    "total_debt": 300_000_000,
                    "revenue_ttm": 1_500_000_000,
                },
            }

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
            ), patch(
                "biotech_alpha.auto_inputs._latest_hkex_annual_result",
                return_value={"NEWS_ID": "fixture"},
            ), patch(
                "biotech_alpha.auto_inputs._download_and_extract_document",
                return_value=source,
            ):
                artifacts = generate_auto_inputs(
                    identity=CompanyIdentity(
                        company="DualityBio",
                        ticker="09606.HK",
                    ),
                    input_dir=root / "generated",
                    output_dir=root / "out",
                    market_data_provider=provider,
                )

            self.assertEqual(len(provider_calls), 1)
            self.assertIsNotNone(artifacts.valuation)
            self.assertEqual(artifacts.warnings, ())

            valuation_payload = _read_json(artifacts.valuation)
            self.assertEqual(valuation_payload["market_cap"], 25_000_000_000)
            self.assertEqual(valuation_payload["currency"], "HKD")
            self.assertEqual(
                valuation_payload["source"], "https://example.com/09606-quote"
            )
            manifest = _read_json(artifacts.source_manifest)
            self.assertIn("valuation", manifest["generated_inputs"])
            self.assertIn("valuation", manifest["validation"])

    def test_generate_auto_inputs_bubbles_warnings_when_snapshot_unwriteable(
        self,
    ) -> None:
        def provider(_identity: CompanyIdentity) -> dict[str, object]:
            return {
                "as_of_date": "2026-04-22",
                "currency": "HKD",
                "market_cap": None,
                "share_price": 12.5,
                "shares_outstanding": None,
                "source": "https://example.com/halted-quote",
                "source_date": "2026-04-22",
                "warnings": [
                    "halted or stale quote: no market cap or shares outstanding",
                ],
            }

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
            ), patch(
                "biotech_alpha.auto_inputs._latest_hkex_annual_result",
                return_value={"NEWS_ID": "fixture"},
            ), patch(
                "biotech_alpha.auto_inputs._download_and_extract_document",
                return_value=source,
            ):
                artifacts = generate_auto_inputs(
                    identity=CompanyIdentity(
                        company="DualityBio",
                        ticker="09606.HK",
                    ),
                    input_dir=root / "generated",
                    output_dir=root / "out",
                    market_data_provider=provider,
                )

            self.assertIsNone(artifacts.valuation)
            self.assertTrue(
                any(
                    "halted" in warning for warning in artifacts.warnings
                ),
                msg=f"expected halted warning, got {artifacts.warnings}",
            )

    def test_generate_auto_inputs_degrades_when_provider_fails(self) -> None:
        def provider(_identity: CompanyIdentity) -> dict[str, object]:
            raise RuntimeError("provider unreachable")

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
            ), patch(
                "biotech_alpha.auto_inputs._latest_hkex_annual_result",
                return_value={"NEWS_ID": "fixture"},
            ), patch(
                "biotech_alpha.auto_inputs._download_and_extract_document",
                return_value=source,
            ):
                artifacts = generate_auto_inputs(
                    identity=CompanyIdentity(
                        company="DualityBio",
                        ticker="09606.HK",
                    ),
                    input_dir=root / "generated",
                    output_dir=root / "out",
                    market_data_provider=provider,
                )

            self.assertIsNone(artifacts.valuation)
            self.assertIsNotNone(artifacts.pipeline_assets)
            self.assertIsNotNone(artifacts.competitors)
            self.assertIsNotNone(artifacts.financials)
            self.assertTrue(
                any("provider" in warning for warning in artifacts.warnings),
                msg=f"expected provider warning, got {artifacts.warnings}",
            )

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

    def test_hbm_fixture_drafts_pipeline_assets_without_table_noise(self) -> None:
        payload = draft_pipeline_assets(
            identity=CompanyIdentity(company="Harbour BioMed", ticker="02142.HK"),
            text=HBM_SAMPLE_TEXT,
            source=_hbm_source(),
        )

        names = [asset["name"] for asset in payload["assets"]]
        self.assertIn("HBM9161", names)
        self.assertIn("HBM9378", names)
        self.assertIn("HBM7004", names)
        self.assertIn("HBM7575", names)
        self.assertIn("HBM7022", names)
        self.assertNotIn("ADCHBM9033", names)
        self.assertNotIn("AZD5863", names)

        hbm9378 = _asset_by_name(payload, "HBM9378")
        self.assertEqual(hbm9378["target"], "TSLP")
        self.assertEqual(hbm9378["phase"], "Phase II")
        self.assertIn("WIN378", hbm9378["aliases"])
        self.assertIn("asthma", hbm9378["indication"])
        self.assertIn("COPD", hbm9378["indication"])
        self.assertEqual(_asset_by_name(payload, "HBM9161")["target"], "FcRn")
        self.assertIn("gMG", _asset_by_name(payload, "HBM9161")["indication"])
        self.assertEqual(_asset_by_name(payload, "HBM7004")["phase"], "preclinical")
        hbm7575 = _asset_by_name(payload, "HBM7575")
        self.assertIn("atopic dermatitis", hbm7575["indication"])
        hbm7022 = _asset_by_name(payload, "HBM7022")
        self.assertIn("AZD5863", hbm7022["aliases"])
        hbm2001 = _asset_by_name(payload, "HBM2001")
        self.assertEqual(hbm2001["target"], "TL1A/IL23p19")
        self.assertEqual(hbm2001["indication"], "IBD")
        j9003 = _asset_by_name(payload, "J9003")
        self.assertIsNone(j9003["target"])
        self.assertEqual(j9003["modality"], "antibody")
        self.assertEqual(j9003["indication"], "IBD")
        r2006 = _asset_by_name(payload, "R2006")
        self.assertEqual(r2006["target"], "CD3/CD19")
        self.assertEqual(r2006["indication"], "autoimmune diseases")
        r7027 = _asset_by_name(payload, "R7027")
        self.assertIsNone(r7027["target"])
        self.assertEqual(r7027["modality"], "bispecific antibody")
        self.assertEqual(r7027["indication"], "autoimmune diseases")
        hbm1020 = _asset_by_name(payload, "HBM1020")
        self.assertEqual(hbm1020["target"], "B7H7/HHLA2")
        self.assertEqual(hbm1020["indication"], "solid tumors")


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


def _hbm_source(
    *,
    file_path: Path = Path("hbm_results.pdf"),
    text_path: Path = Path("hbm_results.txt"),
) -> SourceDocument:
    return SourceDocument(
        source_type="hkex_annual_results",
        title="Annual Results",
        url=(
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/"
            "0330/2026033002702.pdf"
        ),
        publication_date="2026-03-30",
        file_path=file_path,
        text_path=text_path,
        stock_code="02142",
        stock_name="HBM HOLDINGS-B",
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
