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
        "session_id": "a02caae1-ac52-4458-ac64-61272cbf74df",
        "flows": [
            {
                "checkpoint_hash": "b4e52123b8c2da1abf6b18c23e94b4f39e4e1ed1a73f199917612c574e7772b0",
                "transition_ids": [
                    "4e802e0fd4d2a1fe4b74438d9e15444facf2cbd954be46106c1d19725d9f3765",
                    "1eff2d62c4839b4d8768f7872f5075ac59badb669fd9932b7c1da0dee117e280",
                    "6aba9a0e0f9f636fff2268bdff7af09282a5b992b374877b3821d2c07c72e7ed",
                ],
            }
        ],
    }
    guides_payload = {
        "session_id": "4815ce8f-8233-4786-9f43-dee9f48b1af9",
        "start_state_hash": "2080d89bad002cd649be78af6e80ab6c479bb820c523084828f28a4fec2ebf50",
        "end_state_hash": "65e803f3a41d4af684c2b2f708d649609c6dd061496e5206872a0f6f6ec5f6a9",
    }
    bdd_payload = {
        "session_id": "a02caae1-ac52-4458-ac64-61272cbf74df",
        "flows": [
            {
                "checkpoint_hash": "b4e52123b8c2da1abf6b18c23e94b4f39e4e1ed1a73f199917612c574e7772b0",
                "transition_ids": [
                    "4e802e0fd4d2a1fe4b74438d9e15444facf2cbd954be46106c1d19725d9f3765"
                ],
            },
            {
                "checkpoint_hash": "2080d89bad002cd649be78af6e80ab6c479bb820c523084828f28a4fec2ebf50",
                "transition_ids": [
                    "1eff2d62c4839b4d8768f7872f5075ac59badb669fd9932b7c1da0dee117e280",
                ],
            },
            {
                "checkpoint_hash": "08ab3ecd8d43afcae359f084ee19bc676b5a1d62e3778017f475bd4e9269602a",
                "transition_ids": [
                    "6aba9a0e0f9f636fff2268bdff7af09282a5b992b374877b3821d2c07c72e7ed",
                ],
            },
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
        func(task_report_scenario_to_provider, max_tries=1),
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
