"""ARQ worker entry point."""

from src.core.config import get_settings
from src.core.logging import setup_logging

settings = get_settings()
setup_logging(settings)

import logging
import json
from typing import Any

from arq import cron, func

from src.core.playwright import playwright_manager
from src.core.neo import neo_manager
from src.core.redis import redis_settings
from src.tasks.labeling import (
    task_label_graph,
    task_label_state_by_id,
    task_label_transition_by_id,
)
from src.tasks.poller import cron_poll_unlabeled_data
from src.tasks.bdd import task_generate_bdd
from src.tasks.guides import task_generate_user_guide
from src.tasks.video import task_generate_video
from src.tasks.reporter import (
    cron_poll_scenario_reports,
    task_report_scenario_to_provider,
)
from src.tasks.manual_bug import task_generate_manual_bug_report
from src.utils.helpers import parse_cron_string

logger = logging.getLogger("arq.worker")

CRON_HOURS = parse_cron_string(settings.poller_cron_hours)
CRON_MINUTES = parse_cron_string(settings.poller_cron_minutes)
JIRA_REPORT_CRON_MINUTES = parse_cron_string(settings.jira_report_cron_minutes)


def arq_job_serializer(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")


def arq_job_deserializer(value: bytes) -> Any:
    return json.loads(value.decode("utf-8"))


async def startup(ctx: dict) -> None:
    """Initialize external clients and immediately poll for queued work."""
    neo_manager.init()
    await playwright_manager.start()
    logger.info("Worker initialized external connections")
    payload = {
        "graph_id": "38e62f81-0d53-4faa-93a2-94af3c3290de",
        "flows": [
            {
                "checkpoint_hash": "45e3bf1699fbc67091c51c0fe3293580d128f63b77e67df217c368dd9dd99dad",
                "transition_ids": [
                    "9e5fd44ed9ba279d7dcc07befc5ca4ee1a6f80f20ecbc256af10d6fea7d23539",
                    "7c6b718d7f501d88af2833f3f6073e183eeb7deec3ffc6d8f4b9ac1002330e21",
                    "51e3993c1d8f2240bdc3a19e1a252bfca06c6f9f34f3a552942f7891cf1ee165",
                    "dd1c32ae7966158c9db7c79ed08c9ea70580d1bdd38da1e67245949d8e53d22c",
                    "6581f43c6e97734930e8115305644959d1b4546b7bec35bebcbfee9de57b3578",
                    "f5c1e8a6d4be6bef582660223c28641c12ba9137cbf20040749be03b46454ac7",
                    "12354539e457d269a5734f088c75fbdc9dd1b893725b765a089e797673a03275"
                ],
            }
        ],
    }
    guides_payload = {
        "graph_id": "4815ce8f-8233-4786-9f43-dee9f48b1af9",
        "start_state_hash": "2080d89bad002cd649be78af6e80ab6c479bb820c523084828f28a4fec2ebf50",
        "end_state_hash": "65e803f3a41d4af684c2b2f708d649609c6dd061496e5206872a0f6f6ec5f6a9",
    }
    bdd_payload = {
        "graph_id": "5be4d1d6-9fbd-4663-9ebd-6a021d9762d8",
        "session_id": "5be4d1d6-9fbd-4663-9ebd-6a021d9762d8",
        "flows": [
            {
                "checkpoint_hash": "45e3bf1699fbc67091c51c0fe3293580d128f63b77e67df217c368dd9dd99dad",
                "transition_ids": [
                    "b62a3d6ba6f895e8ebe7faff448a2dfd182c62684f93c26a3f40fd9ba39319c4"
                ],
            },
            # {
            #     "checkpoint_hash": "458a29b4f8c2bc3b53808de0ce4f272ba7057adb025251962d44cea575e555a2",
            #     "transition_ids": [
            #         "233a6a6e4aa6cce0103ae2960c10a62ee644189eefaee0d1e728c22389dc416a",
            #         "e55b5430bfc2a17e9ec3ce9d0256f0a5f28f6a85c60ab54e1beeaa7fa12ef13f"
            #     ],
            # },
        ],
    }
    # await ctx["redis"].enqueue_job(
    #     "task_generate_video", payload=payload, _queue_name="docgen:queue"
    # )
    # await ctx["redis"].enqueue_job(
    #     "task_generate_user_guide", payload=guides_payload, _queue_name="docgen:queue"
    # )
    # await ctx["redis"].enqueue_job(
    #     "task_generate_bdd", payload=bdd_payload, _queue_name="docgen:queue"
    # )


async def shutdown(ctx: dict) -> None:
    """Close external clients during worker shutdown."""
    await neo_manager.close()
    await playwright_manager.stop()
    logger.info("Worker closed external connections")


class WorkerSettings:
    """ARQ hooks, tasks, schedule, and Redis connection settings."""

    queue_name = "docgen:queue"
    on_startup = startup
    on_shutdown = shutdown
    job_serializer = arq_job_serializer
    job_deserializer = arq_job_deserializer
    functions = [
        task_label_state_by_id,
        task_label_transition_by_id,
        task_label_graph,
        func(task_generate_bdd, max_tries=settings.bdd_max_retries),
        func(task_generate_user_guide, max_tries=settings.bdd_max_retries),
        func(task_generate_video, max_tries=settings.video_max_retries),
        func(
            task_generate_manual_bug_report,
            max_tries=settings.manual_report_max_retries,
            timeout=settings.manual_report_timeout_seconds,
        ),
        func(task_report_scenario_to_provider, max_tries=settings.scenario_report_max_retries),
    ]
    cron_jobs = [
        cron(
            cron_poll_unlabeled_data,
            hour=CRON_HOURS or list(range(0, 24, 1)),
            minute=CRON_MINUTES or list(range(0, 60, 1)),
        ),
        cron(
            cron_poll_scenario_reports,
            minute=JIRA_REPORT_CRON_MINUTES or list(range(0, 60, 1))
        )
    ]
    redis_settings = redis_settings
