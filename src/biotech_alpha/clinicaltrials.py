"""Minimal ClinicalTrials.gov API client.

The module intentionally keeps dependencies to the Python standard library so
the repository can run before a full application stack is chosen.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from biotech_alpha.models import TrialSummary


class ClinicalTrialsError(RuntimeError):
    """Raised when the ClinicalTrials.gov API request fails."""


class ClinicalTrialsClient:
    """Small client for the ClinicalTrials.gov v2 API."""

    def __init__(
        self,
        base_url: str = "https://clinicaltrials.gov/api/v2",
        timeout: float = 20,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def version(self) -> dict[str, Any]:
        """Return API version metadata, including the data timestamp."""

        return self._get_json("/version")

    def search_studies(
        self,
        term: str,
        *,
        page_size: int = 10,
        page_token: str | None = None,
    ) -> dict[str, Any]:
        """Search full study records by a free-text query term."""

        if not term.strip():
            raise ValueError("term must not be empty")
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")

        params: dict[str, str | int] = {
            "query.term": term,
            "pageSize": page_size,
            "format": "json",
        }
        if page_token:
            params["pageToken"] = page_token

        return self._get_json(f"/studies?{urlencode(params)}")

    def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "biotech-alpha-lab/0.1",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - keep stdlib client compact.
            message = f"ClinicalTrials.gov request failed: {url}"
            raise ClinicalTrialsError(message) from exc


def extract_trial_summaries(response: dict[str, Any]) -> list[TrialSummary]:
    """Extract normalized trial summaries from a v2 studies response."""

    return [
        _extract_trial_summary(study)
        for study in response.get("studies", [])
        if isinstance(study, dict)
    ]


def summaries_as_dicts(summaries: list[TrialSummary]) -> list[dict[str, Any]]:
    """Convert summaries into JSON-serializable dictionaries."""

    return [asdict(summary) for summary in summaries]


def _extract_trial_summary(study: dict[str, Any]) -> TrialSummary:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    sponsors = protocol.get("sponsorCollaboratorsModule", {})
    design = protocol.get("designModule", {})
    conditions = protocol.get("conditionsModule", {})
    arms = protocol.get("armsInterventionsModule", {})

    phases = design.get("phases") or []
    enrollment_info = design.get("enrollmentInfo") or {}
    interventions = arms.get("interventions") or []

    return TrialSummary(
        registry="ClinicalTrials.gov",
        registry_id=identification.get("nctId", ""),
        title=identification.get("officialTitle")
        or identification.get("briefTitle")
        or "",
        sponsor=(sponsors.get("leadSponsor") or {}).get("name"),
        status=status.get("overallStatus"),
        phase=", ".join(phases) if phases else None,
        conditions=tuple(conditions.get("conditions") or ()),
        interventions=tuple(
            item.get("name", "")
            for item in interventions
            if isinstance(item, dict) and item.get("name")
        ),
        enrollment=enrollment_info.get("count"),
        start_date=_date_value(status.get("startDateStruct")),
        primary_completion_date=_date_value(status.get("primaryCompletionDateStruct")),
        completion_date=_date_value(status.get("completionDateStruct")),
        last_update_posted=_date_value(status.get("lastUpdatePostDateStruct")),
    )


def _date_value(value: dict[str, Any] | None) -> str | None:
    if not isinstance(value, dict):
        return None
    return value.get("date")
