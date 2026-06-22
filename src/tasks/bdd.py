import os
import logging
import uuid
import json
import time

from arq import Retry

from src.core.config import get_settings
from src.core.neo import neo_manager
from src.models.bdd import BddGenerationInput
from src.repositories.bdd_repo import BddRepository
from src.services.assertions import SemanticAssertionService
from src.services.bdd.regression import compile_bdd, scenario_names_for_flows

settings = get_settings()
logger = logging.getLogger("arq.worker.bdd")

BULLMQ_QUEUE = "bdd-processing-queue"
BULLMQ_JOB_NAME = "task_process_bdd_output"


async def _enqueue_bullmq_job(redis, queue: str, job_name: str, data: dict) -> str:
    """
    Push a job onto a BullMQ queue by writing the required Redis keys directly.
    BullMQ stores jobs as hashes at  bull:<queue>:<job_id>
    and lists the id in  bull:<queue>:wait
    """
    job_id = uuid.uuid4().hex
    key_prefix = f"bull:{queue}"
    job_key = f"{key_prefix}:{job_id}"
    timestamp = int(time.time() * 1000)

    job_json = json.dumps(data, ensure_ascii=False)

    await redis.hset(
        job_key,
        mapping={
            "id": job_id,
            "name": job_name,
            "data": job_json,
            "opts": json.dumps(
                {"attempts": 3, "backoff": {"type": "exponential", "delay": 500}}
            ),
            "timestamp": timestamp,
        },
    )

    await redis.lpush(f"{key_prefix}:wait", job_id)

    logger.info(
        f"[BDD] Enqueued BullMQ job '{job_name}' (id={job_id}) " f"onto queue '{queue}'"
    )
    return job_id


async def task_generate_bdd(ctx: dict, payload: dict) -> dict:
    """Generate BDD artifacts after all graph records are labeled."""
    request = BddGenerationInput.model_validate(payload)
    session_id = request.session_id
    graph_id = request.graph_id or session_id
    job_try = int(ctx.get("job_try", 1))
    flow_ids = list(
        dict.fromkeys(
            [
                *(flow_id for flow_id in request.flow_ids if flow_id),
                *(flow.flow_id for flow in request.flows if flow.flow_id),
            ]
        )
    )

    async with neo_manager.driver.session() as session:
        repo = BddRepository(session)
        status = await repo.get_labeling_status(graph_id)
        if status["state_count"] == 0:
            raise ValueError(f"Graph {graph_id} contains no states")

        invalid = status["invalid_states"] + status["invalid_transitions"]
        if invalid:
            raise ValueError(
                f"Graph {graph_id} contains {invalid} invalid labeling statuses"
            )

        pending = status["pending_states"] + status["pending_transitions"]
        queued = status["queued_states"] + status["queued_transitions"]
        if pending or queued:
            logger.info(
                f"[BDD:{session_id}] Incomplete labeling detected. "
                f"States (Pending: {status['pending_states']}, "
                f"Queued: {status['queued_states']}) | "
                f"Transitions (Pending: {status['pending_transitions']}, "
                f"Queued: {status['queued_transitions']})"
            )
            if job_try >= settings.bdd_max_retries:
                raise RuntimeError(
                    f"Labeling did not complete for session {session_id} "
                    f"after {job_try} attempts"
                )

            if pending:
                claim = await repo.claim_unlabeled(
                    graph_id,
                    uuid.uuid4().hex,
                )
                state_ids = claim.get("state_ids") or []
                transition_ids = claim.get("transition_ids") or []
                if state_ids or transition_ids:
                    try:
                        job = await ctx["redis"].enqueue_job(
                            "task_label_graph",
                            graph_id,
                        )
                        if job is None:
                            raise RuntimeError("ARQ did not enqueue the labeling job")
                    except Exception:
                        logger.error(f"Labeling session {session_id} Failed")
                        await repo.rollback_claim(
                            graph_id,
                            state_ids,
                            transition_ids,
                        )
                        raise

            logger.info(
                f"[BDD:{session_id}] Waiting for labeling completion "
                f"on attempt {job_try}"
            )
            raise Retry(defer=settings.bdd_retry_delay_seconds)

        flows = await repo.resolve_flows(graph_id, request.flows)
        state_hashes = list(
            dict.fromkeys(
                state.state_hash
                for flow in flows
                for transition in flow.transitions
                for state in (transition.from_state, transition.to_state)
            )
        )
        outgoing_locators = await repo.get_outgoing_locators(
            graph_id,
            state_hashes,
        )

    semantic_assertions_by_flow_index = await SemanticAssertionService(settings).generate(
        flows,
        scenario_names_for_flows(flows),
    )
    compiled = compile_bdd(
        flows,
        outgoing_locators,
        semantic_assertions_by_flow_index=semantic_assertions_by_flow_index,
        split_features=settings.bdd_split_features,
        feature_similarity_threshold=settings.bdd_feature_similarity_threshold,
        singleton_merge_threshold=settings.bdd_singleton_merge_threshold,
    )
    logger.info(
        f"[BDD:{session_id}] Generated {len(compiled.features)} feature(s) "
        f"with {len(flows)} scenarios"
    )

    result_payload = {
        "status": "success",
        "session_id": session_id,
        "features": [
            {
                "id": feature.id,
                "feature_name": feature.feature_name,
                "feature_text": feature.feature_text,
                "scenario_names": feature.scenario_names,
            }
            for feature in compiled.features
        ],
        "states": compiled.states,
        "transitions": compiled.transitions,
        "assertions": compiled.assertions,
        "action_hooks": {},
        "flow_ids": flow_ids,
    }

    if request.regression_codebase_id:
        result_payload["regression_codebase_id"] = request.regression_codebase_id

    if request.codegen_config:
        result_payload["codegen_config"] = request.codegen_config

    if compiled.feature_name is not None and compiled.feature_text is not None:
        result_payload["feature_name"] = compiled.feature_name
        result_payload["feature_text"] = compiled.feature_text

    # add a job for the code-gen worker
    await _enqueue_bullmq_job(
        ctx["redis"],
        BULLMQ_QUEUE,
        BULLMQ_JOB_NAME,
        result_payload,
    )
    save_result_payload(result_payload, "artifacts")

    return result_payload


import json
from pathlib import Path


def save_result_payload(result_payload: dict, output_dir: str = "output") -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Save full JSON
    json_path = output_path / "result.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result_payload, f, indent=4, ensure_ascii=False)

    # Save feature files from result_payload["features"]
    for feature in result_payload.get("features", []):
        feature_name = feature["feature_name"]
        feature_text = feature["feature_text"]

        feature_file = output_path / f"{feature_name}.feature"

        with open(feature_file, "w", encoding="utf-8") as f:
            f.write(feature_text)

    # Save top-level feature_text if it exists
    if "feature_text" in result_payload:
        feature_name = result_payload.get("feature_name", "main_feature")
        feature_file = output_path / f"{feature_name}.feature"

        with open(feature_file, "w", encoding="utf-8") as f:
            f.write(result_payload["feature_text"])
