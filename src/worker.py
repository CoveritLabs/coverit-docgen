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
        func(task_generate_video, max_tries=settings.video_max_retries, timeout=1200),
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
