from __future__ import annotations

import unittest

from biotech_alpha.clinicaltrials import extract_trial_summaries


class ClinicalTrialsExtractionTest(unittest.TestCase):
    def test_extract_trial_summary_from_v2_response(self) -> None:
        response = {
            "studies": [
                {
                    "protocolSection": {
                        "identificationModule": {
                            "nctId": "NCT00000001",
                            "officialTitle": "A Phase III Study of Example Drug",
                        },
                        "statusModule": {
                            "overallStatus": "RECRUITING",
                            "startDateStruct": {"date": "2026-01-01"},
                            "primaryCompletionDateStruct": {"date": "2027-01-01"},
                            "completionDateStruct": {"date": "2027-06-01"},
                            "lastUpdatePostDateStruct": {"date": "2026-04-01"},
                        },
                        "sponsorCollaboratorsModule": {
                            "leadSponsor": {"name": "Example Biotech"}
                        },
                        "designModule": {
                            "phases": ["PHASE3"],
                            "enrollmentInfo": {"count": 300},
                        },
                        "conditionsModule": {
                            "conditions": ["Non-Small Cell Lung Cancer"]
                        },
                        "armsInterventionsModule": {
                            "interventions": [{"name": "Example Drug"}]
                        },
                    }
                }
            ]
        }

        summaries = extract_trial_summaries(response)

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].registry_id, "NCT00000001")
        self.assertEqual(summaries[0].phase, "PHASE3")
        self.assertEqual(summaries[0].enrollment, 300)
        self.assertEqual(summaries[0].conditions, ("Non-Small Cell Lung Cancer",))
        self.assertEqual(summaries[0].interventions, ("Example Drug",))


if __name__ == "__main__":
    unittest.main()
