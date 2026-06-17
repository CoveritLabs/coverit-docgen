import logging

from neo4j import AsyncSession

from src.models.graph import (
    CrawlerGraph,
    CrawlerState,
    CrawlerTransition,
    LabeledState,
    LabeledTransition,
)
from src.models.queries import (
    GET_QUEUED_SESSION_STATES,
    GET_QUEUED_SESSION_TRANSITIONS,
    GET_STATE,
    GET_TRANSITION,
    ROLLBACK_CLAIMED_ITEMS,
    SET_STATE_PENDING,
    SET_TRANSITION_PENDING,
    UPDATE_SINGLE_STATE,
    UPDATE_SINGLE_TRANSITION,
)

logger = logging.getLogger(__name__)


class LabelingRepository:
    """Read and update incrementally labeled Neo4j graph records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _update_state(self, tx, state: LabeledState) -> None:
        result = await tx.run(
            UPDATE_SINGLE_STATE,
            id=state.id,
            name=state.name,
            description=state.description,
        )
        await result.consume()

    async def _update_transition(self, tx, transition: LabeledTransition) -> None:
        result = await tx.run(
            UPDATE_SINGLE_TRANSITION,
            id=transition.id,
            name=transition.name,
            action=transition.action,
        )
        await result.consume()

    async def get_single_state(self, state_id: str) -> CrawlerState:
        """Return one state by Neo4j element ID.

        Raises:
            ValueError: If the state does not exist.
        """
        result = await self.session.run(GET_STATE, id=state_id)
        record = await result.single()

        if not record:
            raise ValueError(f"State with id {state_id} not found")

        node = record["s"]
        return CrawlerState(
            id=state_id,
            url=node.get("url", ""),
            html=node.get("html", "") or "",
        )

    async def get_single_transition(self, transition_id: str) -> CrawlerTransition:
        """Return one transition by Neo4j element ID.

        Raises:
            ValueError: If the transition does not exist.
        """
        result = await self.session.run(GET_TRANSITION, id=transition_id)
        record = await result.single()

        if not record:
            raise ValueError(f"Transition with id {transition_id} not found")
        if record["session_id"] != record["to_session_id"]:
            raise ValueError(
                f"Transition {transition_id} connects states from different sessions"
            )

        return CrawlerTransition(
            id=transition_id,
            from_state_id=record["from_id"],
            to_state_id=record["to_id"],
            locator=record["locator"] or "",
        )

    async def get_graph(self, session_id: str) -> CrawlerGraph | None:
        """Return only records currently queued for one session.

        Completed records are excluded. Origin states needed solely to label queued
        transitions are included in ``states`` and marked in ``skip_states`` so
        their existing labels are not overwritten.
        """
        states: dict[str, CrawlerState] = {}
        skip_states: set[str] = set()
        transitions: list[CrawlerTransition] = []

        states_result = await self.session.run(
            GET_QUEUED_SESSION_STATES, session_id=session_id
        )
        async for record in states_result:
            states[record["id"]] = CrawlerState(
                id=record["id"],
                url=record["url"] or "",
                html=record["html"] or "",
            )

        transitions_result = await self.session.run(
            GET_QUEUED_SESSION_TRANSITIONS, session_id=session_id
        )
        async for record in transitions_result:
            transitions.append(
                CrawlerTransition(
                    id=record["id"],
                    from_state_id=record["from_id"],
                    to_state_id=record["to_id"],
                    locator=record["locator"] or "",
                )
            )
            if record["from_id"] not in states:
                states[record["from_id"]] = CrawlerState(
                    id=record["from_id"],
                    url=record["from_url"] or "",
                    html=record["from_html"] or "",
                )
                skip_states.add(record["from_id"])

        if not transitions and not states:
            logger.warning(f"No queued data found for session {session_id}")
            return None

        return CrawlerGraph(
            session_id=session_id,
            states=states,
            transitions=transitions,
            skip_states=skip_states,
        )

    async def save_labeled_state(self, state: LabeledState) -> None:
        """Save a state label and change its queued status to completed."""
        await self.session.execute_write(self._update_state, state)

    async def save_labeled_transition(self, transition: LabeledTransition) -> None:
        """Save a transition label and change its queued status to completed."""
        await self.session.execute_write(self._update_transition, transition)

    async def set_state_pending(self, state_id: str) -> None:
        """Return one queued state to pending after its labeling attempt fails."""
        result = await self.session.run(SET_STATE_PENDING, id=state_id)
        await result.consume()

    async def set_transition_pending(self, transition_id: str) -> None:
        """Return one queued transition to pending after its attempt fails."""
        result = await self.session.run(SET_TRANSITION_PENDING, id=transition_id)
        await result.consume()

    async def rollback_claim(
        self,
        session_id: str,
        state_ids: list[str],
        transition_ids: list[str],
    ) -> None:
        """Return exactly the supplied queued claim to pending."""
        result = await self.session.run(
            ROLLBACK_CLAIMED_ITEMS,
            session_id=session_id,
            state_ids=state_ids,
            transition_ids=transition_ids,
        )
        await result.consume()
