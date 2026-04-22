from __future__ import annotations

import unittest
from pathlib import Path

from biotech_alpha.auto_inputs import (
    SourceDocument,
    draft_conference_catalysts,
    draft_financial_snapshot,
    draft_pipeline_assets,
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
        first = payload["assets"][0]
        self.assertEqual(first["aliases"], ["BNT323"])
        self.assertEqual(first["target"], "HER2")
        self.assertEqual(first["phase"], "Phase 3")
        self.assertIn("breast cancer", first["indication"])
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


def _source() -> SourceDocument:
    return SourceDocument(
        source_type="hkex_annual_results",
        title="Annual Results",
        url="https://example.com/results.pdf",
        publication_date="2026-03-23",
        file_path=Path("results.pdf"),
        text_path=Path("results.txt"),
        stock_code="09606",
        stock_name="DUALITYBIO-B",
    )


if __name__ == "__main__":
    unittest.main()
