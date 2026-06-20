"""Worker service for integrations reporting."""


import logging

from src.core.config import get_settings
from src.services.reporting.providers import ProviderError, UnknownProviderError, get_provider
from src.services.reporting.report_client import ReportClient

settings = get_settings()
logger = logging.getLogger("arq.worker.jira_reporting")

_report_client = ReportClient()


async def cron_poll_scenario_reports(ctx: dict) -> None:
    """Enqueue a small batch of generic ARQ jobs that each claim one report."""
    redis = ctx["redis"]
    queued = 0
    for _ in range(settings.jira_report_poll_batch_size):
        job = await redis.enqueue_job("task_report_scenario_to_provider")
        if job is None:
            logger.warning("[ScenarioReport] ARQ did not enqueue a report task")
            continue
        queued += 1

    if queued:
        logger.info(f"[ScenarioReport] Enqueued {queued} scenario report task(s)")


async def task_report_scenario_to_provider(
    ctx: dict,
    report_id: str | None = None,
    provider: str = "jira",
) -> dict:
    """Claim and process one scenario integration report."""
    claim = await _report_client.claim_report(report_id=report_id, provider=provider)
    if claim is None:
        return {"status": "empty"}

    report = claim["report"]
    claimed_report_id = report["id"]
    logger.info(f"[ScenarioReport:{claimed_report_id}] Claimed report for provider '{provider}'")

    try:
        issue_provider = get_provider(provider)
    except UnknownProviderError as exc:
        logger.error(f"[ScenarioReport:{claimed_report_id}] {exc}")
        await _report_client.patch_report(claimed_report_id, {"status": "failed", "lastError": str(exc)})
        return {"status": "failed", "report_id": claimed_report_id, "reason": "unknown_provider"}

    try:
        context = await _report_client.get_context(claimed_report_id)
        report = context["report"]
        if report.get("status") == "created":
            return {"status": "already_created", "report_id": claimed_report_id}

        issue_key = report.get("externalIssueKey")
        issue_url = report.get("externalIssueUrl")
        attached_ids = set(report.get("attachedArtifactIds") or [])

        if not issue_key:
            issue = await issue_provider.create_issue(context)
            issue_key = issue.key
            issue_url = issue.url
            await _report_client.patch_report(
                claimed_report_id,
                {
                    "status": "attaching",
                    "externalIssueKey": issue_key,
                    "externalIssueUrl": issue_url,
                    "providerData": {f"{provider}IssueId": issue.id},
                },
            )
            logger.info(f"[ScenarioReport:{claimed_report_id}] Created {provider} issue {issue_key}")
        else:
            await _report_client.patch_report(
                claimed_report_id,
                {
                    "status": "attaching",
                    "externalIssueKey": issue_key,
                    "externalIssueUrl": issue_url,
                },
            )

        for artifact in context.get("artifacts", []):
            artifact_id = artifact["id"]
            if artifact_id in attached_ids:
                continue
            content, content_type = await _report_client.download_artifact(claimed_report_id, artifact_id)
            await issue_provider.upload_attachment(
                context,
                issue_key,
                artifact["name"],
                content,
                content_type or artifact.get("contentType"),
            )
            attached_ids.add(artifact_id)
            await _report_client.patch_report(
                claimed_report_id,
                {
                    "status": "attaching",
                    "attachedArtifactIds": sorted(attached_ids),
                    "externalIssueKey": issue_key,
                    "externalIssueUrl": issue_url,
                },
            )

        await _report_client.patch_report(
            claimed_report_id,
            {
                "status": "created",
                "attachedArtifactIds": sorted(attached_ids),
                "externalIssueKey": issue_key,
                "externalIssueUrl": issue_url,
                "lastError": None,
            },
        )
        return {
            "status": "created",
            "report_id": claimed_report_id,
            "issue_key": issue_key,
        }
    except ProviderError as exc:
        logger.error(f"[ScenarioReport:{claimed_report_id}] {exc}")
        await _report_client.patch_report(claimed_report_id, {"status": "failed", "lastError": str(exc)})
        raise
    except Exception as exc:
        logger.exception(f"[ScenarioReport:{claimed_report_id}] Processing failed")
        await _report_client.patch_report(claimed_report_id, {"status": "failed", "lastError": str(exc)})
        raise
