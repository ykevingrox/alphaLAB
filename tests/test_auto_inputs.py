from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from biotech_alpha.auto_inputs import (
    COMPETITOR_EXTRACTOR_VERSION,
    PIPELINE_EXTRACTOR_VERSION,
    SourceDocument,
    _resolve_hkex_stock_id,
    draft_competitor_assets,
    draft_competitor_discovery_candidates_from_clinical_trials,
    draft_conference_catalysts,
    draft_financial_snapshot,
    draft_pipeline_assets,
    draft_valuation_snapshot,
    generate_auto_inputs,
)
from biotech_alpha.company_report import CompanyIdentity


class FakeClinicalTrialsClient:
    def __init__(self, responses: dict[str, dict] | None = None) -> None:
        self.responses = responses or {}
        self.queries: list[str] = []

    def search_studies(
        self,
        term: str,
        *,
        page_size: int = 10,
        page_token: str | None = None,
    ) -> dict:
        self.queries.append(term)
        return self.responses.get(term, {"studies": []})


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

LEADS_SAMPLE_TEXT = """
BUSINESS HIGHLIGHTS
During fiscal year 2025, we advanced clinical and preclinical milestones:
LBL-024 completed patient enrollment for its registrational trial and remains
on track for BLA submission in the third quarter of 2026 for 3L+ EP-NEC.
For LBL-034, we orally presented Phase I data and are now advancing its
Phase II trial. Our first clinical-stage autoimmune asset, LBL-047
(known as DNTH212 outside of China), entered a Phase I clinical trial.

Clinical Stage Products
Opamtistomig (LBL-024, PD-L1/4-1BB BsAb), our pivotal-stage asset, is
designed to block PD-1/L1 suppression and activate 4-1BB.
LBL-034 (GPRC5D/CD3 BsAb) is being advanced for multiple myeloma.
LBL-047 (anti-BDCA2/TACI bispecific fusion protein) is being evaluated
in patients with systemic lupus erythematosus (SLE).

Pre-clinical Stage Products
LBL-054 (CDH17/CD3 TCE-ADC) entered the IND-enabling stage in Q3 2025.
LBL-058 (DLL3/CD3 TCE-ADC) targets SCLC and other solid tumors, with
PCC nomination targeted in the first half of 2026.
LBL-081 (PD-L1-based Bispecific ADC) is being developed for multiple
solid tumors with PCC nomination targeted in the first half of 2026.
Abbreviations: IgAN = IgA nephropathy; MM = Multiple myeloma.
Warning under Rule 18A.08: there is no assurance that LBL-081 will be
marketed. We plan to submit the first BLA for LBL-024 in China.
"""


def _ctgov_response(
    *,
    nct_id: str = "NCT00000001",
    title: str = "Study of a GPRC5D/CD3 Bispecific Antibody",
    sponsor: str = "Regeneron",
    phase: str = "PHASE3",
    conditions: list[str] | None = None,
    interventions: list[str] | None = None,
    last_update: str = "2026-01-15",
) -> dict:
    return {
        "studies": [
            _ctgov_study(
                nct_id=nct_id,
                title=title,
                sponsor=sponsor,
                phase=phase,
                conditions=conditions,
                interventions=interventions,
                last_update=last_update,
            )
        ]
    }


def _ctgov_study(
    *,
    nct_id: str,
    title: str,
    sponsor: str,
    phase: str = "PHASE3",
    conditions: list[str] | None = None,
    interventions: list[str] | None = None,
    last_update: str = "2026-01-15",
) -> dict:
    return {
        "protocolSection": {
            "identificationModule": {
                "nctId": nct_id,
                "briefTitle": title,
            },
            "statusModule": {
                "overallStatus": "RECRUITING",
                "lastUpdatePostDateStruct": {"date": last_update},
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": sponsor},
            },
            "designModule": {
                "phases": [phase],
            },
            "conditionsModule": {
                "conditions": conditions or ["Multiple Myeloma"],
            },
            "armsInterventionsModule": {
                "interventions": [
                    {"name": item}
                    for item in (
                        interventions
                        or ["Linvoseltamab GPRC5D/CD3 bispecific"]
                    )
                ],
            },
        }
    }


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

    def test_drafts_pipeline_asset_prefers_nearby_anti_target(self) -> None:
        text = """
        Spruce obtained rights to develop and commercialize HAT001/HBM9013,
        a potent and selective anti-CRH-neutralizing antibody.
        In June 2025, Harbour BioMed entered a collaboration to advance
        HBM7020, BCMAxCD3 bispecific T-cell engager, for autoimmune diseases.
        """
        payload = draft_pipeline_assets(
            identity=CompanyIdentity(company="Harbour BioMed", ticker="02142.HK"),
            text=text,
            source=_hbm_source(),
        )

        hat001 = _asset_by_name(payload, "HAT001")
        self.assertEqual(hat001["target"], "CRH")
        self.assertNotIn("BCMA", hat001["target"])

    def test_drafts_pipeline_asset_ignores_strategy_era_phase(self) -> None:
        text = """
        3. HBM7020 China rights was out-licensed to Hualan biologics in 2020
        and Ex-China rights was out-licensed to Otsuka in 2025.
        In 2025, we fully transitioned into Phase 3.0 strategic era.
        HBM7020 is a BCMAxCD3 bispecific antibody generated with our
        proprietary fully human HBICE platform.
        In August 2023, HBM7020 obtained the IND clearance to commence
        Phase I trial for cancer in China from NMPA.
        """
        payload = draft_pipeline_assets(
            identity=CompanyIdentity(company="Harbour BioMed", ticker="02142.HK"),
            text=text,
            source=_hbm_source(),
        )

        hbm7020 = _asset_by_name(payload, "HBM7020")
        self.assertEqual(hbm7020["phase"], "Phase I")
        self.assertEqual(hbm7020["partner"], "Otsuka")

    def test_drafts_pipeline_asset_truncates_inline_numbered_sections(self) -> None:
        text = """
        1. We entered an exclusive agreement with Windward Bio for HBM9378,
        an anti-TSLP fully human monoclonal antibody. 2. In February 2025,
        Spruce obtained rights to HAT001/HBM9013, an anti-CRH antibody.
        """
        payload = draft_pipeline_assets(
            identity=CompanyIdentity(company="Harbour BioMed", ticker="02142.HK"),
            text=text,
            source=_hbm_source(),
        )

        hbm9378 = _asset_by_name(payload, "HBM9378")
        self.assertEqual(hbm9378["partner"], "Windward")
        self.assertNotIn("Spruce", hbm9378["partner"] or "")

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
        self.assertEqual(
            payload["generated_extractor_version"],
            COMPETITOR_EXTRACTOR_VERSION,
        )
        self.assertTrue(payload["needs_human_review"])
        self.assertGreaterEqual(len(payload["competitors"]), 1)
        first = payload["competitors"][0]
        self.assertIn("company", first)
        self.assertIn("asset_name", first)
        self.assertIn("target", first)
        self.assertEqual(first["indication"], "to_verify")
        self.assertIn(
            "Pipeline asset indication context",
            first["evidence"][0]["claim"],
        )
        self.assertTrue(first["evidence"][0]["is_inferred"])

    def test_drafts_competitor_assets_for_hbm_targets(self) -> None:
        identity = CompanyIdentity(company="Harbour BioMed", ticker="02142.HK")
        source = _hbm_source()
        pipeline_payload = draft_pipeline_assets(
            identity=identity,
            text=HBM_SAMPLE_TEXT,
            source=source,
        )
        payload = draft_competitor_assets(
            identity=identity,
            pipeline_assets_payload=pipeline_payload,
            source=source,
        )

        pairs = {
            (row["company"], row["asset_name"], row["target"])
            for row in payload["competitors"]
        }
        self.assertIn(("argenx", "VYVGART", "FcRn"), pairs)
        self.assertIn(("UCB", "RYSTIGGO", "FcRn"), pairs)
        self.assertIn(("AstraZeneca/Amgen", "TEZSPIRE", "TSLP"), pairs)
        self.assertIn(("Nuvation Bio", "B7-H4 ADC program", "B7H4/CD3"), pairs)
        for row in payload["competitors"]:
            self.assertEqual(row["indication"], "to_verify")

    def test_drafts_competitor_assets_for_exact_composite_targets(self) -> None:
        identity = CompanyIdentity(company="Example Bio", ticker="9999.HK")
        source = _source()
        pipeline_payload = {
            "assets": [
                {"name": "BCMA Asset", "target": "BCMA/CD3"},
                {"name": "CTLA Asset", "target": "CTLA-4"},
            ]
        }

        payload = draft_competitor_assets(
            identity=identity,
            pipeline_assets_payload=pipeline_payload,
            source=source,
        )

        pairs = {
            (row["company"], row["asset_name"], row["target"])
            for row in payload["competitors"]
        }
        self.assertIn(("Johnson & Johnson", "TECVAYLI", "BCMA/CD3"), pairs)
        self.assertIn(("Pfizer", "ELREXFIO", "BCMA/CD3"), pairs)
        self.assertIn(("Bristol Myers Squibb", "YERVOY", "CTLA-4"), pairs)
        for row in payload["competitors"]:
            self.assertEqual(row["indication"], "to_verify")

    def test_drafts_competitor_assets_ingests_discovery_candidates(self) -> None:
        identity = CompanyIdentity(company="Leads Biolabs", ticker="09887.HK")
        source = _leads_source()
        pipeline_payload = draft_pipeline_assets(
            identity=identity,
            text=LEADS_SAMPLE_TEXT,
            source=source,
        )
        candidates = [
            {
                "company": "Regeneron",
                "asset_name": "Linvoseltamab",
                "target": "GPRC5D x CD3",
                "modality": "bispecific antibody",
                "indication": "multiple myeloma",
                "phase": "Phase 3",
                "geography": "global",
                "source_url": "https://clinicaltrials.gov/study/NCT00000001",
                "source_date": "2026-01-15",
                "evidence_snippet": "A GPRC5D x CD3 bispecific antibody.",
                "why_comparable": "Same GPRC5D/CD3 target family as LBL-034.",
                "source_query": "GPRC5D CD3 clinical trial",
                "confidence": 0.72,
            },
            {
                "company": "Leads Biolabs",
                "asset_name": "LBL-034",
                "target": "GPRC5D/CD3",
                "source_url": "https://example.com/self",
                "source_date": "2026-01-15",
                "evidence_snippet": "Self asset.",
                "why_comparable": "Same company should be rejected.",
            },
            {
                "company": "Loose PD-1 Co",
                "asset_name": "PD-1 asset",
                "target": "PD-1",
                "source_url": "https://example.com/pd1",
                "source_date": "2026-01-15",
                "evidence_snippet": "PD-1 monotherapy.",
                "why_comparable": "Loose single-target match should reject.",
            },
            {
                "company": "No Source Bio",
                "asset_name": "Mystery asset",
                "target": "DLL3/CD3",
                "source_date": "2026-01-15",
                "evidence_snippet": "Missing source URL.",
                "why_comparable": "Insufficient evidence.",
            },
        ]

        payload = draft_competitor_assets(
            identity=identity,
            pipeline_assets_payload=pipeline_payload,
            source=source,
            discovery_candidates=candidates,
        )

        pairs = {
            (row["company"], row["asset_name"], row["target"])
            for row in payload["competitors"]
        }
        self.assertIn(("Regeneron", "Linvoseltamab", "GPRC5D/CD3"), pairs)
        self.assertNotIn(("Leads Biolabs", "LBL-034", "GPRC5D/CD3"), pairs)
        self.assertEqual(payload["candidate_ingest"]["accepted"], 1)
        self.assertEqual(payload["candidate_ingest"]["rejected"], 3)
        requests = {
            request["target"]: request
            for request in payload["discovery_requests"]
        }
        self.assertIn("GPRC5D/CD3", requests)
        self.assertIn("candidate_schema", requests["GPRC5D/CD3"])
        linvo = next(
            row
            for row in payload["competitors"]
            if row["asset_name"] == "Linvoseltamab"
        )
        self.assertTrue(linvo["generated_by_llm"])
        self.assertEqual(linvo["indication"], "multiple myeloma")
        self.assertEqual(linvo["evidence"][0]["source_date"], "2026-01-15")
        self.assertTrue(linvo["evidence"][0]["is_inferred"])

    def test_drafts_ctgov_competitor_discovery_candidates(self) -> None:
        client = FakeClinicalTrialsClient(
            {
                "GPRC5D CD3 bispecific antibody": {
                    "studies": [
                        _ctgov_study(
                            nct_id="NCT00000001",
                            title="Study of a GPRC5D/CD3 Bispecific Antibody",
                            sponsor="Regeneron",
                        ),
                        _ctgov_study(
                            nct_id="NCT00000002",
                            title="Study of a GPRC5D Antibody",
                            sponsor="Loose Target Bio",
                            interventions=["GPRC5D antibody"],
                        ),
                        _ctgov_study(
                            nct_id="NCT00000003",
                            title="Study of LBL-034 GPRC5D/CD3",
                            sponsor="Leads Biolabs",
                            interventions=["LBL-034 GPRC5D/CD3"],
                        ),
                        _ctgov_study(
                            nct_id="NCT00000004",
                            title="GPRC5D/CD3 Maintenance After Transplant",
                            sponsor="Generic Maintenance Study Group",
                            interventions=[
                                "Autologous Hematopoietic Stem Cell Transplantation",
                                "GPRC5D/CD3 BiTEs",
                            ],
                        ),
                    ]
                },
            }
        )
        competitor_payload = {
            "discovery_requests": [
                {
                    "pipeline_asset": "LBL-034",
                    "target": "GPRC5D/CD3",
                    "modality": "bispecific antibody",
                }
            ]
        }

        payload = draft_competitor_discovery_candidates_from_clinical_trials(
            identity=CompanyIdentity(company="Leads Biolabs", ticker="09887.HK"),
            competitor_draft_payload=competitor_payload,
            client=client,
        )

        self.assertEqual(payload["generated_by"], (
            "auto_inputs.clinicaltrials_competitor_discovery"
        ))
        self.assertEqual(client.queries, ["GPRC5D CD3 bispecific antibody"])
        self.assertEqual(len(payload["candidates"]), 1)
        self.assertEqual(
            payload["rejection_summary"],
            {
                "target_family_not_mentioned": 1,
                "self_company": 1,
                "generic_target_intervention": 1,
            },
        )
        candidate = payload["candidates"][0]
        self.assertEqual(candidate["company"], "Regeneron")
        self.assertEqual(
            candidate["asset_name"],
            "Linvoseltamab GPRC5D/CD3 bispecific",
        )
        self.assertEqual(candidate["target"], "GPRC5D/CD3")
        self.assertEqual(
            candidate["source_url"],
            "https://clinicaltrials.gov/study/NCT00000001",
        )
        self.assertFalse(candidate["generated_by_llm"])

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

    def test_leads_fixture_drafts_pipeline_without_status_leakage(self) -> None:
        payload = draft_pipeline_assets(
            identity=CompanyIdentity(company="Leads Biolabs", ticker="09887.HK"),
            text=LEADS_SAMPLE_TEXT,
            source=_leads_source(),
        )

        names = [asset["name"] for asset in payload["assets"]]
        self.assertIn("LBL-024", names)
        self.assertIn("LBL-047", names)
        self.assertIn("LBL-058", names)
        self.assertNotIn("DNTH212", names)
        lbl024 = _asset_by_name(payload, "LBL-024")
        self.assertEqual(lbl024["target"], "PD-L1/4-1BB")
        self.assertEqual(lbl024["phase"], "BLA planned")
        self.assertEqual(lbl024["next_milestone"], "BLA submission in Q3 2026")
        self.assertNotEqual(lbl024["phase"], "preclinical")
        lbl047 = _asset_by_name(payload, "LBL-047")
        self.assertIn("DNTH212", lbl047["aliases"])
        self.assertEqual(lbl047["target"], "BDCA2/TACI")
        self.assertEqual(lbl047["modality"], "bispecific fusion protein")
        self.assertIn("systemic lupus erythematosus", lbl047["indication"])
        lbl058 = _asset_by_name(payload, "LBL-058")
        self.assertEqual(lbl058["target"], "DLL3/CD3")
        self.assertEqual(lbl058["modality"], "TCE-ADC")
        self.assertIn("SCLC", lbl058["indication"])
        self.assertNotIn("IgAN", lbl058["indication"] or "")
        lbl081 = _asset_by_name(payload, "LBL-081")
        self.assertEqual(lbl081["phase"], "PCC nomination")
        self.assertEqual(lbl081["next_milestone"], "PCC nomination in H1 2026")

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
            generated_dir = root / "generated"
            generated_dir.mkdir()
            discovery_path = (
                generated_dir / "09606_hk_competitor_discovery_candidates.json"
            )
            discovery_path.write_text(
                json.dumps(
                    {
                        "generated_by": "llm.global_competitor_discovery",
                        "candidates": [
                            {
                                "company": "Example Global Bio",
                                "asset_name": "HER2 candidate",
                                "target": "HER2",
                                "source_url": "https://example.com/her2",
                                "source_date": "2026-01-15",
                                "evidence_snippet": "HER2-directed asset.",
                                "why_comparable": "Same target as DB-1303.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
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
                            input_dir=generated_dir,
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
            self.assertEqual(competitors["candidate_ingest"]["accepted"], 1)
            self.assertEqual(financials["cash_and_equivalents"], 3324529000)
            self.assertEqual(conference["catalysts"][0]["category"], "conference")
            self.assertIn("pipeline_assets", manifest["generated_inputs"])
            self.assertIn("competitors", manifest["generated_inputs"])
            self.assertIn(
                "competitor_discovery_candidates",
                manifest["generated_inputs"],
            )
            self.assertIn("competitors", manifest["validation"])

    def test_generate_auto_inputs_runs_ctgov_competitor_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_dir = root / "raw_fixture"
            raw_dir.mkdir()
            generated_dir = root / "generated"
            source = _source(
                file_path=raw_dir / "results.pdf",
                text_path=raw_dir / "results.txt",
            )
            source.file_path.write_bytes(b"%PDF fixture")
            source.text_path.write_text(SAMPLE_TEXT, encoding="utf-8")
            client = FakeClinicalTrialsClient(
                {
                    "HER2": _ctgov_response(
                        title="Study of a HER2 ADC",
                        sponsor="Example Global Bio",
                        phase="PHASE2",
                        conditions=["HER2-positive breast cancer"],
                        interventions=["Example HER2 ADC"],
                    )
                }
            )

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
                    competitor_discovery_client=client,
                )

            discovery_path = (
                generated_dir / "09606_hk_competitor_discovery_candidates.json"
            )
            self.assertTrue(discovery_path.exists())
            self.assertIn("HER2", client.queries)
            competitors = _read_json(artifacts.competitors)
            discovery = _read_json(discovery_path)
            self.assertEqual(len(discovery["candidates"]), 1)
            self.assertEqual(competitors["candidate_ingest"]["accepted"], 1)
            pairs = {
                (row["company"], row["asset_name"])
                for row in competitors["competitors"]
            }
            self.assertIn(("Example Global Bio", "Example HER2 ADC"), pairs)

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
                        "generated_by": "auto_inputs.hkex_annual_results",
                        "generated_extractor_version": PIPELINE_EXTRACTOR_VERSION,
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
            competitors_path = generated_dir / "09606_hk_competitors.json"
            competitors_path.write_text(
                json.dumps(
                    {
                        "company": "DualityBio",
                        "ticker": "09606.HK",
                        "generated_by": "auto_inputs.target_overlap_seed",
                        "competitors": [],
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
            self.assertEqual(
                competitors["generated_extractor_version"],
                COMPETITOR_EXTRACTOR_VERSION,
            )
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
        hbm9161 = _asset_by_name(payload, "HBM9161")
        self.assertEqual(hbm9161["target"], "FcRn")
        self.assertIn("gMG", hbm9161["indication"])
        self.assertEqual(hbm9161["phase"], "BLA accepted")
        self.assertEqual(_asset_by_name(payload, "HBM7004")["phase"], "IND-enabling")
        hbm7575 = _asset_by_name(payload, "HBM7575")
        self.assertIn("atopic dermatitis", hbm7575["indication"])
        self.assertEqual(hbm7575["phase"], "IND approved")
        hbm7022 = _asset_by_name(payload, "HBM7022")
        self.assertIn("AZD5863", hbm7022["aliases"])
        hbm7004 = _asset_by_name(payload, "HBM7004")
        self.assertNotIn("obesity", hbm7004["indication"] or "")
        hbm2001 = _asset_by_name(payload, "HBM2001")
        self.assertEqual(hbm2001["target"], "TL1A/IL23p19")
        self.assertIsNone(hbm2001["mechanism"])
        self.assertEqual(hbm2001["indication"], "IBD")
        j9003 = _asset_by_name(payload, "J9003")
        self.assertIsNone(j9003["target"])
        self.assertEqual(j9003["mechanism"], "undisclosed target")
        self.assertEqual(j9003["modality"], "antibody")
        self.assertEqual(j9003["indication"], "IBD")
        r2006 = _asset_by_name(payload, "R2006")
        self.assertEqual(r2006["target"], "CD3/CD19")
        self.assertIsNone(r2006["mechanism"])
        self.assertEqual(r2006["indication"], "autoimmune diseases")
        r7027 = _asset_by_name(payload, "R7027")
        self.assertIsNone(r7027["target"])
        self.assertEqual(r7027["mechanism"], "undisclosed target")
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


def _leads_source(
    *,
    file_path: Path = Path("leads_results.pdf"),
    text_path: Path = Path("leads_results.txt"),
) -> SourceDocument:
    return SourceDocument(
        source_type="hkex_annual_results",
        title="Annual Results",
        url=(
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/"
            "0327/2026032700954.pdf"
        ),
        publication_date="2026-03-27",
        file_path=file_path,
        text_path=text_path,
        stock_code="09887",
        stock_name="LEADS BIOLABS-B",
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
