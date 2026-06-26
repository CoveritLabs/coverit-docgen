from neo4j import AsyncSession

from src.models.guides import (
    ResolvedGuidePath,
    ResolvedGuideState,
    ResolvedGuideTransition,
)
from src.models.queries import RESOLVE_SHORTEST_GUIDE_PATH


class GuideRepository:
    """Neo4j access for user guide shortest-path generation."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve_shortest_path(
        self,
        graph_id: str,
        start_hash: str,
        end_hash: str,
    ) -> ResolvedGuidePath:
        result = await self.session.run(
            RESOLVE_SHORTEST_GUIDE_PATH,
            graph_id=graph_id,
            start_state_hash=start_hash,
            end_state_hash=end_hash,
        )
        record = await result.single()
        if record is None:
            raise ValueError(f"Graph {graph_id} was not found")

        if record.get("start_db_id") is None:
            raise ValueError(
                f"Start state {start_hash} was not found in graph {graph_id}"
            )
        if record.get("end_db_id") is None:
            raise ValueError(
                f"End state {end_hash} was not found in graph {graph_id}"
            )

        states_data = record.get("states") or []
        transitions_data = record.get("transitions") or []
        if not states_data:
            raise ValueError(
                f"No path exists from state {start_hash} to {end_hash} "
                f"in graph {graph_id}"
            )

        states = [self._state_from_mapping(state) for state in states_data]
        by_db_id = {state.db_id: state for state in states}
        transitions: list[ResolvedGuideTransition] = []

        for index, transition_data in enumerate(transitions_data):
            if index + 1 >= len(states):
                raise ValueError("Resolved guide path has inconsistent topology")
            transition = self._transition_from_mapping(
                transition_data,
                states[index],
                states[index + 1],
            )
            transitions.append(transition)

        start_state = by_db_id.get(record["start_db_id"])
        end_state = by_db_id.get(record["end_db_id"])
        if start_state is None or end_state is None:
            raise ValueError("Resolved guide path did not include both endpoints")

        return ResolvedGuidePath(
            start_state=start_state,
            end_state=end_state,
            transitions=transitions,
        )

    @staticmethod
    def _state_from_mapping(data: dict) -> ResolvedGuideState:
        name = data.get("name") or ""
        state_hash = data.get("state_hash") or ""
        if not name.strip():
            raise ValueError(f"Resolved state {state_hash} has no label")
        status = data.get("labeling_status") or ""
        if status != "COMPLETED":
            raise ValueError(f"Resolved state {state_hash} is not labeled")
        return ResolvedGuideState(
            db_id=data.get("db_id") or "",
            state_hash=state_hash,
            name=name,
            description=data.get("description") or "",
            url=data.get("url") or "",
            labeling_status=status,
        )

    @staticmethod
    def _transition_from_mapping(
        data: dict,
        from_state: ResolvedGuideState,
        to_state: ResolvedGuideState,
    ) -> ResolvedGuideTransition:
        action = data.get("action") or ""
        transition_id = data.get("transition_id") or ""
        if not action.strip():
            raise ValueError(f"Resolved transition {transition_id} has no action")
        status = data.get("labeling_status") or ""
        if status != "COMPLETED":
            raise ValueError(f"Resolved transition {transition_id} is not labeled")
        return ResolvedGuideTransition(
            db_id=data.get("db_id") or "",
            transition_id=transition_id,
            name=data.get("name") or "",
            action=action,
            action_type=data.get("action_type") or "",
            locator_value=data.get("locator_value") or "",
            labeling_status=status,
            from_state=from_state,
            to_state=to_state,
        )
