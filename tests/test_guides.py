import unittest
from unittest.mock import AsyncMock, Mock, patch

from arq import Retry

from src.models.guides import (
    ResolvedGuidePath,
    ResolvedGuideState,
    ResolvedGuideTransition,
)
from src.models.queries import RESOLVE_SHORTEST_GUIDE_PATH
from src.repositories.guide_repo import GuideRepository
from src.services.guides.formatter import format_user_guide
from src.tasks.guides import task_generate_user_guide


class AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class Driver:
    def __init__(self, session):
        self._session = session

    def session(self):
        return AsyncContext(self._session)


def guide_state(db_id, state_hash, name):
    return ResolvedGuideState(
        db_id=db_id,
        state_hash=state_hash,
        name=name,
        description=f"{name} description",
        url=f"https://example.test/{state_hash}",
        labeling_status="COMPLETED",
    )


def guide_transition(db_id, transition_id, action, from_state, to_state):
    return ResolvedGuideTransition(
        db_id=db_id,
        transition_id=transition_id,
        name=transition_id,
        action=action,
        action_type="click",
        locator_value=f"#{transition_id}",
        labeling_status="COMPLETED",
        from_state=from_state,
        to_state=to_state,
    )


def state_mapping(db_id, state_hash, name, status="COMPLETED"):
    return {
        "db_id": db_id,
        "state_hash": state_hash,
        "name": name,
        "description": f"{name} description",
        "url": f"https://example.test/{state_hash}",
        "labeling_status": status,
    }


def transition_mapping(db_id, transition_id, action, status="COMPLETED"):
    return {
        "db_id": db_id,
        "transition_id": transition_id,
        "name": transition_id,
        "action": action,
        "action_type": "click",
        "locator_value": f"#{transition_id}",
        "labeling_status": status,
    }


class GuideQueryTests(unittest.TestCase):
    def test_shortest_path_query_is_graph_scoped_and_hash_based(self):
        self.assertIn("state_hash: $start_state_hash", RESOLVE_SHORTEST_GUIDE_PATH)
        self.assertIn("state_hash: $end_state_hash", RESOLVE_SHORTEST_GUIDE_PATH)
        self.assertGreaterEqual(
            RESOLVE_SHORTEST_GUIDE_PATH.count("graph_id: $graph_id"),
            2,
        )
        self.assertIn("shortestPath", RESOLVE_SHORTEST_GUIDE_PATH)
        self.assertIn("transition.graph_id = $graph_id", RESOLVE_SHORTEST_GUIDE_PATH)

    def test_query_returns_ordered_path_lists(self):
        self.assertIn("state IN nodes(path)", RESOLVE_SHORTEST_GUIDE_PATH)
        self.assertIn("transition IN relationships(path)", RESOLVE_SHORTEST_GUIDE_PATH)
        self.assertIn("AS states", RESOLVE_SHORTEST_GUIDE_PATH)
        self.assertIn("AS transitions", RESOLVE_SHORTEST_GUIDE_PATH)


class GuideRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_multi_step_path_in_order(self):
        record = {
            "start_db_id": "s1",
            "end_db_id": "s3",
            "states": [
                state_mapping("s1", "start", "Start Page"),
                state_mapping("s2", "middle", "Middle Page"),
                state_mapping("s3", "end", "End Page"),
            ],
            "transitions": [
                transition_mapping("t1", "open-middle", 'Click "Next"'),
                transition_mapping("t2", "open-end", 'Click "Finish"'),
            ],
        }
        result = Mock()
        result.single = AsyncMock(return_value=record)
        session = Mock()
        session.run = AsyncMock(return_value=result)

        path = await GuideRepository(session).resolve_shortest_path(
            "session",
            "start",
            "end",
        )

        self.assertEqual(path.start_state.state_hash, "start")
        self.assertEqual(path.end_state.state_hash, "end")
        self.assertEqual(
            [transition.transition_id for transition in path.transitions],
            ["open-middle", "open-end"],
        )
        self.assertEqual(path.transitions[0].from_state.state_hash, "start")
        self.assertEqual(path.transitions[0].to_state.state_hash, "middle")

    async def test_rejects_missing_start(self):
        result = Mock()
        result.single = AsyncMock(return_value={"start_db_id": None, "end_db_id": "s2"})
        session = Mock()
        session.run = AsyncMock(return_value=result)

        with self.assertRaisesRegex(ValueError, "Start state start was not found"):
            await GuideRepository(session).resolve_shortest_path(
                "session",
                "start",
                "end",
            )

    async def test_rejects_no_path(self):
        result = Mock()
        result.single = AsyncMock(
            return_value={
                "start_db_id": "s1",
                "end_db_id": "s2",
                "states": [],
                "transitions": [],
            }
        )
        session = Mock()
        session.run = AsyncMock(return_value=result)

        with self.assertRaisesRegex(ValueError, "No path exists"):
            await GuideRepository(session).resolve_shortest_path(
                "session",
                "start",
                "end",
            )

    async def test_rejects_incomplete_labels_and_empty_actions(self):
        session = Mock()
        result = Mock()
        session.run = AsyncMock(return_value=result)
        repo = GuideRepository(session)

        result.single = AsyncMock(
            return_value={
                "start_db_id": "s1",
                "end_db_id": "s2",
                "states": [
                    state_mapping("s1", "start", "Start", "PENDING"),
                    state_mapping("s2", "end", "End"),
                ],
                "transitions": [transition_mapping("t1", "go", 'Click "Go"')],
            }
        )
        with self.assertRaisesRegex(ValueError, "is not labeled"):
            await repo.resolve_shortest_path("session", "start", "end")

        result.single = AsyncMock(
            return_value={
                "start_db_id": "s1",
                "end_db_id": "s2",
                "states": [
                    state_mapping("s1", "start", "Start"),
                    state_mapping("s2", "end", "End"),
                ],
                "transitions": [transition_mapping("t1", "go", "")],
            }
        )
        with self.assertRaisesRegex(ValueError, "has no action"):
            await repo.resolve_shortest_path("session", "start", "end")

    async def test_supports_same_start_and_end_with_zero_actions(self):
        result = Mock()
        result.single = AsyncMock(
            return_value={
                "start_db_id": "s1",
                "end_db_id": "s1",
                "states": [state_mapping("s1", "same", "Dashboard Page")],
                "transitions": [],
            }
        )
        session = Mock()
        session.run = AsyncMock(return_value=result)

        path = await GuideRepository(session).resolve_shortest_path(
            "session",
            "same",
            "same",
        )

        self.assertEqual(path.start_state.state_hash, "same")
        self.assertEqual(path.transitions, [])


class GuideFormatterTests(unittest.TestCase):
    def test_formats_stable_numbered_guide_without_internal_ids(self):
        start = guide_state("s1", "start", "Home Page")
        cart = guide_state("s2", "cart", "Cart Page")
        checkout = guide_state("s3", "checkout", "Checkout Page")
        path = ResolvedGuidePath(
            start_state=start,
            end_state=checkout,
            transitions=[
                guide_transition("t1", "open-cart", 'Click "Cart"', start, cart),
                guide_transition("t2", "checkout", 'Click "Checkout"', cart, checkout),
            ],
        )

        guide = format_user_guide(path)

        self.assertEqual(
            guide,
            (
                "Start on the Home Page.\n"
                "Home Page description.\n"
                '1. Click "Cart". This takes you to the Cart Page.\n'
                '2. Click "Checkout". This takes you to the Checkout Page.\n'
                "You should now be on the Checkout Page."
            ),
        )
        self.assertNotIn("s1", guide)
        self.assertNotIn("open-cart", guide)


class GuideTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_labeling_is_claimed_enqueued_and_deferred(self):
        repo = Mock()
        repo.get_labeling_status = AsyncMock(
            return_value={
                "state_count": 2,
                "transition_count": 1,
                "pending_states": 1,
                "pending_transitions": 0,
                "queued_states": 0,
                "queued_transitions": 0,
                "invalid_states": 0,
                "invalid_transitions": 0,
            }
        )
        repo.claim_unlabeled = AsyncMock(
            return_value={"state_ids": ["s1"], "transition_ids": []}
        )
        repo.rollback_claim = AsyncMock()
        redis = Mock()
        redis.enqueue_job = AsyncMock(return_value=Mock())

        with (
            patch("src.tasks.guides.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.guides.BddRepository", return_value=repo),
        ):
            with self.assertRaises(Retry):
                await task_generate_user_guide(
                    {"redis": redis, "job_try": 1},
                    {
                        "graph_id": "graph-1",
                        "start_state_hash": "start",
                        "end_state_hash": "end",
                    },
                )

        redis.enqueue_job.assert_awaited_once_with("task_label_graph", "graph-1")
        repo.rollback_claim.assert_not_awaited()

    async def test_enqueue_failure_rolls_back_exact_claim(self):
        repo = Mock()
        repo.get_labeling_status = AsyncMock(
            return_value={
                "state_count": 2,
                "transition_count": 1,
                "pending_states": 1,
                "pending_transitions": 1,
                "queued_states": 0,
                "queued_transitions": 0,
                "invalid_states": 0,
                "invalid_transitions": 0,
            }
        )
        repo.claim_unlabeled = AsyncMock(
            return_value={"state_ids": ["s1"], "transition_ids": ["t1"]}
        )
        repo.rollback_claim = AsyncMock()
        redis = Mock()
        redis.enqueue_job = AsyncMock(side_effect=RuntimeError("down"))

        with (
            patch("src.tasks.guides.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.guides.BddRepository", return_value=repo),
        ):
            result = await task_generate_user_guide(
                {"redis": redis, "job_try": 1},
                {
                    "graph_id": "graph-1",
                    "start_state_hash": "start",
                    "end_state_hash": "end",
                },
            )

        repo.rollback_claim.assert_awaited_once_with("graph-1", ["s1"], ["t1"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["lastError"], "down")

    async def test_success_returns_guide_and_step_count(self):
        start = guide_state("s1", "start", "Home Page")
        end = guide_state("s2", "end", "End Page")
        path = ResolvedGuidePath(
            start_state=start,
            end_state=end,
            transitions=[
                guide_transition("t1", "go", 'Click "Go"', start, end),
            ],
        )
        bdd_repo = Mock()
        bdd_repo.get_labeling_status = AsyncMock(
            return_value={
                "state_count": 2,
                "transition_count": 1,
                "pending_states": 0,
                "pending_transitions": 0,
                "queued_states": 0,
                "queued_transitions": 0,
                "invalid_states": 0,
                "invalid_transitions": 0,
            }
        )
        guide_repo = Mock()
        guide_repo.resolve_shortest_path = AsyncMock(return_value=path)

        with (
            patch("src.tasks.guides.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.guides.BddRepository", return_value=bdd_repo),
            patch("src.tasks.guides.GuideRepository", return_value=guide_repo),
        ):
            result = await task_generate_user_guide(
                {"redis": Mock(), "job_try": 1},
                {
                    "graph_id": "graph-1",
                    "start_state_hash": "start",
                    "end_state_hash": "end",
                },
            )

        self.assertEqual(result["status"], "success")
        self.assertIn('1. Click "Go".', result["userGuide"])


if __name__ == "__main__":
    unittest.main()
