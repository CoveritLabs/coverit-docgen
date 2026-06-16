from neo4j import AsyncSession

from src.models.bdd import (
    BddFlowInput,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
)
from src.models.queries import (
    CLAIM_BDD_SESSION_LABELING,
    GET_BDD_LABELING_STATUS,
    GET_BDD_OUTGOING_LOCATORS,
    RESOLVE_BDD_FLOWS,
    ROLLBACK_CLAIMED_ITEMS,
)


class BddRepository:
    """Neo4j access for BDD generation and its labeling dependency."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_labeling_status(self, session_id: str) -> dict:
        result = await self.session.run(
            GET_BDD_LABELING_STATUS,
            session_id=session_id,
        )
        record = await result.single()
        if record is None:
            raise ValueError(f"Session {session_id} was not found")
        return dict(record)

    async def claim_unlabeled(self, session_id: str, claim_id: str) -> dict:
        result = await self.session.run(
            CLAIM_BDD_SESSION_LABELING,
            session_id=session_id,
            claim_id=claim_id,
        )
        record = await result.single()
        return (
            dict(record)
            if record
            else {
                "state_ids": [],
                "transition_ids": [],
            }
        )

    async def rollback_claim(
        self,
        session_id: str,
        state_ids: list[str],
        transition_ids: list[str],
    ) -> None:
        result = await self.session.run(
            ROLLBACK_CLAIMED_ITEMS,
            session_id=session_id,
            state_ids=state_ids,
            transition_ids=transition_ids,
        )
        await result.consume()

    async def resolve_flows(
        self,
        session_id: str,
        flows: list[BddFlowInput],
    ) -> list[ResolvedFlow]:
        query_flows = [
            {
                "flow_index": index,
                "checkpoint_hash": flow.checkpoint_hash,
                "transition_ids": flow.transition_ids,
            }
            for index, flow in enumerate(flows)
        ]
        result = await self.session.run(
            RESOLVE_BDD_FLOWS,
            session_id=session_id,
            flows=query_flows,
        )
        records = await result.data()
        by_flow: dict[int, list[dict]] = {}
        for record in records:
            by_flow.setdefault(record["flow_index"], []).append(record)

        resolved: list[ResolvedFlow] = []
        for flow_index, requested in enumerate(flows):
            rows = sorted(
                by_flow.get(flow_index, []),
                key=lambda row: row["transition_index"],
            )
            if not rows or rows[0].get("checkpoint_db_id") is None:
                raise ValueError(
                    f"Checkpoint {requested.checkpoint_hash} was not found "
                    f"in session {session_id}"
                )
            if len(rows) != len(requested.transition_ids):
                raise ValueError(f"Flow {flow_index} did not resolve completely")

            checkpoint = self._state_from_row(rows[0], "checkpoint")
            transitions: list[ResolvedTransition] = []
            expected_source_hash = checkpoint.state_hash

            for transition_index, row in enumerate(rows):
                requested_id = requested.transition_ids[transition_index]
                if row.get("transition_db_id") is None:
                    raise ValueError(
                        f"Transition {requested_id} was not found in session "
                        f"{session_id}"
                    )
                if not row.get("transition_name"):
                    raise ValueError(f"Transition {requested_id} has no label")
                if not row.get("locator_value"):
                    raise ValueError(f"Transition {requested_id} has no locator")

                from_state = self._state_from_row(row, "from")
                to_state = self._state_from_row(row, "to")
                if from_state.state_hash != expected_source_hash:
                    raise ValueError(
                        f"Transition {requested_id} does not continue flow "
                        f"{flow_index}"
                    )

                transitions.append(
                    ResolvedTransition(
                        db_id=row["transition_db_id"],
                        transition_id=row["transition_id"],
                        name=row["transition_name"] or "",
                        action=row["transition_action"] or "",
                        action_type=row["action_type"] or "",
                        locator_value=row["locator_value"] or "",
                        labeling_status=row["transition_status"] or "",
                        from_state=from_state,
                        to_state=to_state,
                    )
                )
                expected_source_hash = to_state.state_hash

            resolved.append(
                ResolvedFlow(
                    checkpoint=checkpoint,
                    transitions=transitions,
                )
            )
        return resolved

    async def get_outgoing_locators(
        self,
        session_id: str,
        state_hashes: list[str],
    ) -> dict[str, list[str]]:
        result = await self.session.run(
            GET_BDD_OUTGOING_LOCATORS,
            session_id=session_id,
            state_hashes=state_hashes,
        )
        records = await result.data()
        return {record["state_hash"]: record["locators"] or [] for record in records}

    @staticmethod
    def _state_from_row(row: dict, prefix: str) -> ResolvedState:
        name = row.get(f"{prefix}_name") or ""
        if not name:
            raise ValueError(f"Resolved state {row.get(f'{prefix}_hash')} has no label")
        return ResolvedState(
            db_id=row[f"{prefix}_db_id"],
            state_hash=row[f"{prefix}_hash"],
            name=name,
            description=row.get(f"{prefix}_description") or "",
            url=row.get(f"{prefix}_url") or "",
            labeling_status=row.get(f"{prefix}_status") or "",
        )
