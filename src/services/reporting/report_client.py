"""Client for CoverIt's own internal API.

This is the worker's only dependency for talking to CoverIt itself. It knows
nothing about Jira or any other external issue tracker - it just manages the
lifecycle of a scenario report record.
"""

import asyncio
import logging
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.core.config import get_settings
from src.core.http_client import json_request

settings = get_settings()
logger = logging.getLogger("arq.worker.jira_reporting")


class ReportClient:
    """Talks to CoverIt-API."""

    def __init__(self) -> None:
        self._base_url = settings.api_base_url.rstrip("/")
        self._headers = {
            "Accept": "application/json",
            "X-CoverIt-Internal-Token": settings.internal_service_token,
        }

    async def claim_report(self, report_id: str | None, provider: str) -> dict | None:
        payload: dict[str, str] = {"provider": provider}
        if report_id:
            payload["reportId"] = report_id
        status, data = await self._post("/internal/reports/scenario/claim", payload)
        if status == 204:
            return None
        return data

    async def get_context(self, report_id: str) -> dict:
        _, data = await self._get(f"/internal/reports/scenario/{report_id}/context")
        return data

    async def patch_report(self, report_id: str, payload: dict) -> dict:
        _, data = await self._patch(f"/internal/reports/scenario/{report_id}", payload)
        return data

    async def download_artifact(self, report_id: str, artifact_id: str) -> tuple[bytes, str | None]:
        return await asyncio.to_thread(self._download_artifact_sync, report_id, artifact_id)

    async def _get(self, path: str) -> tuple[int, dict]:
        return await json_request("GET", f"{self._base_url}{path}", None, self._headers)

    async def _post(self, path: str, payload: dict) -> tuple[int, dict]:
        return await json_request("POST", f"{self._base_url}{path}", payload, self._headers)

    async def _patch(self, path: str, payload: dict) -> tuple[int, dict]:
        return await json_request("PATCH", f"{self._base_url}{path}", payload, self._headers)

    def _download_artifact_sync(self, report_id: str, artifact_id: str) -> tuple[bytes, str | None]:
        url = f"{self._base_url}/internal/reports/scenario/{report_id}/artifacts/{artifact_id}/download"
        request = Request(url, headers=self._headers, method="GET")
        try:
            with urlopen(request, timeout=120) as response:
                return response.read(), response.headers.get("Content-Type")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"artifact download failed with {exc.code}: {detail}") from exc
