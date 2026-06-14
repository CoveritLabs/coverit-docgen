from fastapi import HTTPException
from neo4j import AsyncSession
from src.models.graph import LabeledGraph, LabeledState, LabeledTransition
from src.models.graph import CrawlerState, CrawlerTransition, CrawlerGraph
from src.models.queries import *


class LabelingRepository:
    """Repository handling database operations for labeled artifacts."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def _update_state(self, tx, state: LabeledState):
        await tx.run(
            UPDATE_SINGLE_STATE,
            id=state.id,
            name=state.name,
            description=state.description,
        )

    async def _update_transition(self, tx, transition: LabeledTransition):
        await tx.run(
            UPDATE_SINGLE_TRANSITION,
            id=transition.id,
            name=transition.name,
            action=transition.action,
        )

    async def _update_graph(self, tx, graph: LabeledGraph):
        state_updates = [
            {
                "id": state_id,
                "props": {
                    "name": labeled_state.name,
                    "description": labeled_state.description,
                },
            }
            for state_id, labeled_state in graph.state_labels.items()
        ]

        transition_updates = [
            {
                "id": trans_id,
                "props": {"name": labeled_trans.name, "action": labeled_trans.action},
            }
            for trans_id, labeled_trans in graph.transition_labels.items()
        ]

        await tx.run(UPDATE_STATES, updates=state_updates)
        await tx.run(UPDATE_TRANSITIONS, updates=transition_updates)

    async def get_single_state(self, state_id: str) -> CrawlerState:
        """Gets a state from the database."""

        result = await self.session.run(GET_STATE, id=state_id)
        record = await result.single()

        if not record:
            raise HTTPException(
                status_code=404, detail=f"State with id {state_id} not found"
            )

        node = record["s"]

        return CrawlerState(id=state_id, url=node["url"], html=node.get("html", ""))

    async def get_single_transition(self, transition_id: str) -> CrawlerTransition:
        """Gets a Transition from the database."""
        result = await self.session.run(GET_TRANSITION, id=transition_id)
        record = await result.single()

        if not record:
            raise HTTPException(
                status_code=404, detail=f"Transition with id {transition_id} not found"
            )

        return CrawlerTransition(
            id=transition_id,
            from_state_id=record["from_id"],
            to_state_id=record["to_id"],
            locator=record["locator"],
        )

    async def get_graph(self, session_id: str) -> CrawlerGraph:
        states = {}
        transitions = []

        # Fetch all states for the session
        states_result = await self.session.run(
            GET_SESSION_STATES, session_id=session_id
        )

        async for record in states_result:
            node = record["s"]
            states[node.element_id] = CrawlerState(
                id=node.element_id, url=node["url"], html=node.get("html", "")
            )

        if not states:
            raise HTTPException(
                status_code=404,
                detail=f"No data found for session {session_id}",
            )

        # Fetch all transitions for the session
        transitions_result = await self.session.run(
            GET_SESSION_TRANSITIONS, session_id=session_id
        )

        async for record in transitions_result:
            transitions.append(
                CrawlerTransition(
                    id=record["id"],
                    from_state_id=record["from_id"],
                    to_state_id=record["to_id"],
                    locator=record["locator"],
                )
            )

        return CrawlerGraph(
            session_id=session_id, states=states, transitions=transitions
        )

    async def save_labeled_state(self, state: LabeledState):
        """Saves a single labeled state to Neo4j."""
        await self.session.execute_write(self._update_state, state)

    async def save_labeled_transition(self, transition: LabeledTransition):
        """Saves a single labeled transition to Neo4j."""
        await self.session.execute_write(self._update_transition, transition)

    async def save_labeled_graph(self, graph: LabeledGraph):
        """Saves a labeled graph to neo4j database."""
        await self.session.execute_write(self._update_graph, graph)
