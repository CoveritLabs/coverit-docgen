import logging
import json
from pathlib import Path

from src.core.config import get_settings
from src.core.neo import neo_manager
from src.models.bdd import BddFlowInput
from src.models.manual_bug import ManualBugReportInput
from src.repositories.video_repo import VideoRepository
from src.services.reporting.providers import (
    ProviderError,
    UnknownProviderError,
    get_provider,
)
from src.services.reporting.report_client import ReportClient
from src.services.video.config import get_video_render_config
from src.services.video.generator import VideoGenerator

settings = get_settings()
logger = logging.getLogger("arq.worker.manual_bug")
_report_client = ReportClient()


async def _resolve_flows(request: ManualBugReportInput):
    async with neo_manager.driver.session() as session:
        return await VideoRepository(session).resolve_flows(
            request.session_id,
            [
                BddFlowInput(
                    flow_id=request.flow_id,
                    checkpoint_hash=request.checkpoint_hash,
                    transition_ids=request.transition_ids,
                )
            ],
        )


async def _generate_video(request: ManualBugReportInput, flows):
    return await VideoGenerator(get_video_render_config()).generate(
        request.session_id,
        flows,
        Path(settings.video_output_dir),
    )


async def _get_or_create_issue(request: ManualBugReportInput, issue_provider, context: dict):
    report = context["report"]
    issue_key = report.get("externalIssueKey")
    issue_url = report.get("externalIssueUrl")

    if not issue_key:
        issue = await issue_provider.create_issue(context)
        issue_key = issue.key
        issue_url = issue.url
        await _report_client.patch_report(
            request.report_id,
            {
                "status": "attaching",
                "externalIssueKey": issue_key,
                "externalIssueUrl": issue_url,
                "providerData": {f"{request.provider}IssueId": issue.id},
            },
        )
    else:
        await _report_client.patch_report(
            request.report_id,
            {
                "status": "attaching",
                "externalIssueKey": issue_key,
                "externalIssueUrl": issue_url,
            },
        )
    return issue_key, issue_url


async def _upload_video_attachment(request: ManualBugReportInput, issue_provider, context: dict, issue_key: str, video_result):
    artifact_path = Path(video_result.artifact_path)
    video_bytes = artifact_path.read_bytes()
    attachment_name = f"manual-bug-{request.flow_id}.mp4"
    await issue_provider.upload_attachment(
        context,
        issue_key,
        attachment_name,
        video_bytes,
        "video/mp4",
    )
    return attachment_name


async def _upload_events_attachment_if_any(request: ManualBugReportInput, issue_provider, context: dict, issue_key: str):
    if not request.recorded_events:
        return False

    events_attachment_name = f"manual-bug-{request.flow_id}-recorded-events.json"
    await issue_provider.upload_attachment(
        context,
        issue_key,
        events_attachment_name,
        json.dumps(request.recorded_events, indent=2, ensure_ascii=False).encode("utf-8"),
        "application/json",
    )
    return True


async def _process_report_attachments(request: ManualBugReportInput, issue_provider, context: dict, issue_key: str, video_result):
    report = context["report"]
    attachment_name = await _upload_video_attachment(request, issue_provider, context, issue_key, video_result)
    logger.info(
        f"[ManualBug:{request.session_id}] Attached video to "
        f"{request.provider} issue {issue_key}"
    )

    attached_ids = set(report.get("attachedArtifactIds") or [])
    attached_ids.add(f"manual-bug-video:{request.flow_id}")

    events_uploaded = await _upload_events_attachment_if_any(request, issue_provider, context, issue_key)
    if events_uploaded:
        attached_ids.add(f"manual-bug-recorded-events:{request.flow_id}")
        logger.info(
            f"[ManualBug:{request.session_id}] Attached recorded events to "
            f"{request.provider} issue {issue_key}"
        )

    return attachment_name, attached_ids


async def task_generate_manual_bug_report(ctx: dict, payload: dict) -> dict:
    request = ManualBugReportInput.model_validate(payload)
    logger.info(
        f"[ManualBug:{request.session_id}] Generating provider report "
        f"{request.report_id} for flow {request.flow_id}"
    )

    flows = await _resolve_flows(request)
    logger.info(
        f"[ManualBug:{request.session_id}] Resolved {len(flows)} flow(s) for video generation"
    )
    video_result = await _generate_video(request, flows)
    logger.info(
        f"[ManualBug:{request.session_id}] Generated video at {video_result.artifact_path}"
    )

    try:
        issue_provider = get_provider(request.provider)
    except UnknownProviderError as exc:
        await _report_client.patch_report(
            request.report_id,
            {"status": "failed", "lastError": str(exc)},
        )
        raise

    try:
        context = await _report_client.get_context(request.report_id)
        issue_key, issue_url = await _get_or_create_issue(request, issue_provider, context)

        attachment_name, attached_ids = await _process_report_attachments(
            request, issue_provider, context, issue_key, video_result
        )

        await _report_client.patch_report(
            request.report_id,
            {
                "status": "created",
                "attachedArtifactIds": sorted(attached_ids),
                "externalIssueKey": issue_key,
                "externalIssueUrl": issue_url,
                "lastError": None,
            },
        )
        logger.info(
            f"[ManualBug:{request.session_id}] Attached video to "
            f"{request.provider} issue {issue_key}"
        )
        return {
            **video_result.model_dump(),
            "report_id": request.report_id,
            "issue_key": issue_key,
            "attachment_name": attachment_name,
        }
    except ProviderError as exc:
        await _report_client.patch_report(
            request.report_id,
            {"status": "failed", "lastError": str(exc)},
        )
        raise
    except Exception as exc:
        logger.exception(f"[ManualBug:{request.report_id}] Processing failed")
        await _report_client.patch_report(
            request.report_id,
            {"status": "failed", "lastError": str(exc)},
        )
        raise
