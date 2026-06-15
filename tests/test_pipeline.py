import unittest
from unittest.mock import AsyncMock, Mock, patch

from src.models.graph import (
    CrawlerGraph,
    CrawlerState,
    CrawlerTransition,
    LabeledState,
    LabeledTransition,
)
from src.models.queries import (
    CLAIM_UNLABELED_SESSIONS,
    GET_QUEUED_SESSION_STATES,
    GET_QUEUED_SESSION_TRANSITIONS,
    ROLLBACK_CLAIMED_ITEMS,
    SET_STATE_PENDING,
    SET_TRANSITION_PENDING,
    UPDATE_SINGLE_STATE,
)
from src.services.labeling.rule_based import label_crawler_transition
from src.tasks.labeling import task_label_graph, task_label_transition_by_id
from src.tasks.poller import cron_poll_unlabeled_data


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


class QueryInvariantTests(unittest.TestCase):
    def test_claim_only_accepts_null_or_pending_and_sets_queued(self):
        self.assertIn("labeling_status IS NULL", CLAIM_UNLABELED_SESSIONS)
        self.assertIn("labeling_status = 'PENDING'", CLAIM_UNLABELED_SESSIONS)
        self.assertIn("THEN 'QUEUED'", CLAIM_UNLABELED_SESSIONS)
        self.assertIn("THEN $claim_id", CLAIM_UNLABELED_SESSIONS)
        self.assertGreaterEqual(
            CLAIM_UNLABELED_SESSIONS.count(
                "labeling_claim_id = $claim_id"
            ),
            2,
        )
        self.assertNotIn("9220808", CLAIM_UNLABELED_SESSIONS)
        self.assertIn(
            "state.labeling_status = CASE",
            CLAIM_UNLABELED_SESSIONS,
        )
        self.assertNotIn("COMPLETED", CLAIM_UNLABELED_SESSIONS)

    def test_fetches_are_queued_and_session_scoped(self):
        self.assertIn("labeling_status = 'QUEUED'", GET_QUEUED_SESSION_STATES)
        self.assertGreaterEqual(
            GET_QUEUED_SESSION_TRANSITIONS.count(
                "{session_id: $session_id}"
            ),
            2,
        )

    def test_completion_requires_current_queued_status(self):
        self.assertIn("labeling_status = 'QUEUED'", UPDATE_SINGLE_STATE)
        self.assertIn("labeling_status = 'COMPLETED'", UPDATE_SINGLE_STATE)

    def test_state_rollback_uses_only_element_id_and_queued_status(self):
        self.assertIn("elementId(s) = $id", SET_STATE_PENDING)
        self.assertIn("labeling_status = 'QUEUED'", SET_STATE_PENDING)
        self.assertNotIn("$session_id", SET_STATE_PENDING)

    def test_transition_rollback_uses_only_element_id_and_queued_status(self):
        self.assertIn("elementId(t) = $id", SET_TRANSITION_PENDING)
        self.assertIn("labeling_status = 'QUEUED'", SET_TRANSITION_PENDING)
        self.assertNotIn("$session_id", SET_TRANSITION_PENDING)

    def test_claim_rollback_uses_exact_id_lists(self):
        self.assertIn("$state_ids", ROLLBACK_CLAIMED_ITEMS)
        self.assertIn("$transition_ids", ROLLBACK_CLAIMED_ITEMS)
        self.assertIn("elementId(state) = state_id", ROLLBACK_CLAIMED_ITEMS)
        self.assertIn(
            "elementId(transition) = transition_id",
            ROLLBACK_CLAIMED_ITEMS,
        )


class TransitionLabelingTests(unittest.IsolatedAsyncioTestCase):
    async def test_transition_locator_is_awaited(self):
        transition = CrawlerTransition(
            id="t1",
            from_state_id="s1",
            to_state_id="s2",
            locator="#submit",
        )
        state = CrawlerState(id="s1", url="", html="<button>Old</button>")
        marked = (
            "<html><body><button data-pw-locator='marker'>Submit</button>"
            "</body></html>"
        )
        with patch(
            "src.services.labeling.rule_based.handle_locator",
            new=AsyncMock(return_value=(marked, "marker")),
        ) as locator:
            result = await label_crawler_transition(transition, state)

        locator.assert_awaited_once()
        self.assertEqual(result.name, "Submit")
        self.assertEqual(result.action, 'Click "Submit"')

    async def test_missing_locator_fails_instead_of_completing_unknown(self):
        transition = CrawlerTransition(
            id="t1",
            from_state_id="s1",
            to_state_id="s2",
            locator="",
        )
        state = CrawlerState(id="s1", url="", html="<button>Submit</button>")
        with self.assertRaises(ValueError):
            await label_crawler_transition(transition, state)

    async def test_transition_task_rolls_back_by_transition_id_only(self):
        transition = CrawlerTransition(
            id="t1",
            from_state_id="s1",
            to_state_id="s2",
            locator="button",
        )
        state = CrawlerState(
            id="s1",
            url="",
            html="<button>Submit</button>",
        )
        repo = Mock()
        repo.get_single_transition = AsyncMock(return_value=transition)
        repo.get_single_state = AsyncMock(return_value=state)
        repo.save_labeled_transition = AsyncMock()
        repo.set_transition_pending = AsyncMock()

        with (
            patch(
                "src.tasks.labeling.neo_manager.driver",
                Driver(Mock()),
            ),
            patch(
                "src.tasks.labeling.LabelingRepository",
                return_value=repo,
            ),
            patch(
                "src.tasks.labeling.label_crawler_transition",
                new=AsyncMock(side_effect=ValueError("bad transition")),
            ),
        ):
            with self.assertRaises(ValueError):
                await task_label_transition_by_id({}, "t1")

        repo.set_transition_pending.assert_awaited_once_with("t1")


class GraphTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_task_isolates_item_failures(self):
        graph = CrawlerGraph(
            session_id="session",
            states={
                "good": CrawlerState(id="good", url="/good", html=""),
                "bad": CrawlerState(id="bad", url="/bad", html=""),
                "origin": CrawlerState(
                    id="origin",
                    url="/origin",
                    html="<button>Go</button>",
                ),
            },
            skip_states={"origin"},
            transitions=[
                CrawlerTransition(
                    id="transition",
                    from_state_id="origin",
                    to_state_id="good",
                    locator="button",
                )
            ],
        )
        repo = Mock()
        repo.get_graph = AsyncMock(return_value=graph)
        repo.save_labeled_state = AsyncMock()
        repo.save_labeled_transition = AsyncMock()
        repo.set_state_pending = AsyncMock()
        repo.set_transition_pending = AsyncMock()

        def label_state(state):
            if state.id == "bad":
                raise ValueError("bad state")
            return LabeledState(id=state.id, name="Good", description="Good")

        transition_label = LabeledTransition(
            id="transition",
            html_snippet="<button>Go</button>",
            name="Go",
            action='Click "Go"',
        )
        session = Mock()
        driver = Driver(session)

        with (
            patch("src.tasks.labeling.neo_manager.driver", driver),
            patch(
                "src.tasks.labeling.LabelingRepository",
                return_value=repo,
            ),
            patch(
                "src.tasks.labeling.label_crawler_state",
                side_effect=label_state,
            ),
            patch(
                "src.tasks.labeling.label_crawler_transition",
                new=AsyncMock(return_value=transition_label),
            ),
        ):
            result = await task_label_graph({}, "session")

        self.assertEqual(result["status"], "partial_failure")
        self.assertEqual(result["completed_states"], 1)
        self.assertEqual(result["completed_transitions"], 1)
        repo.set_state_pending.assert_awaited_once_with("bad")
        repo.set_transition_pending.assert_not_awaited()


class PollerTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_failure_rolls_back_exact_claim(self):
        result = Mock()
        result.data = AsyncMock(
            return_value=[
                {
                    "id": "session",
                    "state_ids": ["s1"],
                    "transition_ids": ["t1"],
                }
            ]
        )
        session = Mock()
        session.run = AsyncMock(return_value=result)
        repo = Mock()
        repo.rollback_claim = AsyncMock()
        redis = Mock()
        redis.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))

        with (
            patch("src.tasks.poller.neo_manager.driver", Driver(session)),
            patch(
                "src.tasks.poller.LabelingRepository",
                return_value=repo,
            ),
        ):
            await cron_poll_unlabeled_data({"redis": redis})

        repo.rollback_claim.assert_awaited_once_with(
            "session",
            ["s1"],
            ["t1"],
        )
        self.assertIn("claim_id", session.run.await_args.kwargs)


if __name__ == "__main__":
    unittest.main()
