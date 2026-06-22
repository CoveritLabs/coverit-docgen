from neo4j import AsyncSession

from src.models.bdd import BddFlowInput
from src.models.queries import RESOLVE_VIDEO_FLOWS
from src.models.video import (
    VideoResolvedFlow,
    VideoResolvedTransition,
    parse_video_action_values,
)


class VideoRepository:
    """Neo4j access for video generation flow resolution."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve_flows(
        self,
        session_id: str,
        flows: list[BddFlowInput],
    ) -> list[VideoResolvedFlow]:
        query_flows = [
            {
                "flow_index": index,
                "checkpoint_hash": flow.checkpoint_hash,
                "transition_ids": flow.transition_ids,
            }
            for index, flow in enumerate(flows)
        ]
        result = await self.session.run(
            RESOLVE_VIDEO_FLOWS,
            session_id=session_id,
            flows=query_flows,
        )
        records = await result.data()
        by_flow: dict[int, list[dict]] = {}
        for record in records:
            by_flow.setdefault(record["flow_index"], []).append(record)

        resolved: list[VideoResolvedFlow] = []
        for flow_index, requested in enumerate(flows):
            rows = sorted(
                by_flow.get(flow_index, []),
                key=lambda row: row["transition_index"],
            )
            if not rows or rows[0].get("checkpoint_hash") is None:
                raise ValueError(
                    f"Checkpoint {requested.checkpoint_hash} was not found "
                    f"in session {session_id}"
                )
            if len(rows) != len(requested.transition_ids):
                raise ValueError(f"Video flow {flow_index} did not resolve completely")

            checkpoint_hash = rows[0].get("checkpoint_hash") or ""
            start_url = rows[0].get("checkpoint_url") or ""
            if not start_url.strip():
                raise ValueError(f"Checkpoint {checkpoint_hash} has empty URL")

            transitions: list[VideoResolvedTransition] = []
            expected_source_hash = checkpoint_hash

            for transition_index, row in enumerate(rows):
                requested_id = requested.transition_ids[transition_index]
                if row.get("transition_id") is None:
                    raise ValueError(
                        f"Transition {requested_id} was not found in session "
                        f"{session_id}"
                    )

                from_hash = row.get("from_hash") or ""
                to_hash = row.get("to_hash") or ""
                if from_hash != expected_source_hash:
                    raise ValueError(
                        f"Transition {requested_id} does not continue video flow "
                        f"{flow_index}"
                    )

                action_value = parse_video_action_values(
                    row.get("action_value"),
                    row.get("locator_value") or "",
                    row.get("action_type") or "",
                )
                transitions.append(
                    VideoResolvedTransition(
                        transition_id=row["transition_id"],
                        action_type=row.get("action_type") or "",
                        locator_value=row.get("locator_value") or "",
                        action_value=action_value,
                    )
                )
                expected_source_hash = to_hash

            resolved.append(
                VideoResolvedFlow(
                    start_url=start_url,
                    transitions=transitions,
                )
            )

        return resolved
