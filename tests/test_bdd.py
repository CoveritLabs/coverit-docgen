import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from arq import Retry

from src.models.bdd import (
    BddFlowInput,
    FeaturePlan,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
    ScenarioPlan,
    StepPlan,
    StepType,
)
from src.models.queries import (
    CLAIM_BDD_SESSION_LABELING,
    GET_BDD_LABELING_STATUS,
    GET_BDD_OUTGOING_LOCATORS,
    RESOLVE_BDD_FLOWS,
)
from src.repositories.bdd_repo import BddRepository
from src.services.bdd.gherkin import render_feature
from src.services.bdd.regression import compile_bdd, infer_feature_name
from src.tasks.bdd import task_generate_bdd


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


def state(db_id, state_hash, name, url="https://shop.example.com"):
    return ResolvedState(
        db_id=db_id,
        state_hash=state_hash,
        name=name,
        description=f"{name} description",
        url=url,
        labeling_status="COMPLETED",
    )


def transition(db_id, transition_id, name, from_state, to_state):
    return ResolvedTransition(
        db_id=db_id,
        transition_id=transition_id,
        name=name,
        action=f'Click "{name}"',
        action_type="click",
        locator_value=f"#{transition_id}",
        labeling_status="COMPLETED",
        from_state=from_state,
        to_state=to_state,
    )


class BddQueryTests(unittest.TestCase):
    def test_preflight_and_claim_are_session_scoped(self):
        self.assertGreaterEqual(
            GET_BDD_LABELING_STATUS.count(
                "{session_id: $session_id}"
            ),
            3,
        )
        self.assertIn("labeling_status IS NULL", CLAIM_BDD_SESSION_LABELING)
        self.assertIn("labeling_claim_id = $claim_id", CLAIM_BDD_SESSION_LABELING)
        self.assertIn("labeling_status = 'QUEUED'", CLAIM_BDD_SESSION_LABELING)

    def test_resolution_preserves_input_order_and_session(self):
        self.assertIn("flow.flow_index", RESOLVE_BDD_FLOWS)
        self.assertIn("transition_index", RESOLVE_BDD_FLOWS)
        self.assertIn("ORDER BY flow_index, transition_index", RESOLVE_BDD_FLOWS)
        self.assertGreaterEqual(
            RESOLVE_BDD_FLOWS.count("session_id: $session_id"),
            4,
        )
        self.assertIn("$state_hashes", GET_BDD_OUTGOING_LOCATORS)


class BddCompilerTests(unittest.TestCase):
    def test_compiles_descriptive_feature_and_exact_gherkin(self):
        home = state("s1", "home", "Shopping Home Page")
        cart = state("s2", "cart", "Shopping Cart Page")
        open_cart = transition("t1", "open-cart", "Open Shopping Cart", home, cart)
        flow = ResolvedFlow(checkpoint=home, transitions=[open_cart])

        compiled = compile_bdd(
            [flow],
            {"home": ["#open-cart"], "cart": []},
        )

        self.assertEqual(compiled.feature_name, "Shopping User Flows")
        self.assertEqual(len(compiled.features), 1)
        self.assertEqual(
            compiled.features[0].feature_name,
            "Shopping User Flows",
        )
        self.assertEqual(
            compiled.feature_text,
            (
                "Feature: Shopping User Flows\n"
                "\n"
                "  Scenario: Open Shopping Cart\n"
                '    Given the UI is in state "S_SHOPPING_HOME_PAGE"\n'
                '    When I perform transition "T_OPEN_SHOPPING_CART"\n'
                '    Then the UI should be in state "S_SHOPPING_CART_PAGE"\n'
            ),
        )
        self.assertEqual(
            compiled.states["S_SHOPPING_HOME_PAGE"]["dom"]["elements"],
            {"#open-cart": {"cssSelector": "#open-cart"}},
        )
        self.assertEqual(
            compiled.transitions["T_OPEN_SHOPPING_CART"]["action"]["stateId"],
            "S_SHOPPING_HOME_PAGE",
        )

    def test_split_enabled_groups_same_destination_area(self):
        home = state("s1", "home", "Shop Home Page")
        search = state("s2", "search", "Shop Search Page")
        cart = state("s3", "cart", "Shop Cart Page", "https://shop.example.com/cart")
        cart_review = state(
            "s4",
            "cart-review",
            "Shop Cart Review Page",
            "https://shop.example.com/cart/review",
        )
        account = state(
            "s5",
            "account",
            "Account Settings Page",
            "https://shop.example.com/account",
        )
        flows = [
            ResolvedFlow(
                checkpoint=home,
                transitions=[
                    transition("t1", "cart", "View Shop Cart", home, cart)
                ],
            ),
            ResolvedFlow(
                checkpoint=search,
                transitions=[
                    transition(
                        "t2",
                        "review-cart",
                        "Review Shop Cart",
                        search,
                        cart_review,
                    )
                ],
            ),
            ResolvedFlow(
                checkpoint=home,
                transitions=[
                    transition(
                        "t3",
                        "account",
                        "Manage Account Settings",
                        home,
                        account,
                    )
                ],
            ),
        ]

        compiled = compile_bdd(
            flows,
            {},
            split_features=True,
            singleton_merge_threshold=0.50,
        )

        self.assertEqual(len(compiled.features), 2)
        self.assertEqual(compiled.features[0].scenario_names, [
            "View Shop Cart",
            "Review Shop Cart",
        ])
        self.assertEqual(compiled.features[1].scenario_names, [
            "Manage Account Settings"
        ])
        self.assertIsNone(compiled.feature_name)
        self.assertIsNone(compiled.feature_text)

    def test_semantically_similar_flows_merge_across_different_anchors(self):
        home = state("s1", "home", "Quote Search Page")
        author = state(
            "s2",
            "author",
            "Quote Author Details Page",
            "https://quotes.example.com/author",
        )
        list_page = state("s3", "list", "Quote List Page")
        tag_page = state(
            "s4",
            "tag",
            "Quote Tag Details Page",
            "https://quotes.example.com/tag",
        )

        compiled = compile_bdd(
            [
                ResolvedFlow(
                    checkpoint=home,
                    transitions=[
                        transition(
                            "t1",
                            "author",
                            "Browse Quote Author Details",
                            home,
                            author,
                        )
                    ],
                ),
                ResolvedFlow(
                    checkpoint=list_page,
                    transitions=[
                        transition(
                            "t2",
                            "tag",
                            "Browse Quote Tag Details",
                            list_page,
                            tag_page,
                        )
                    ],
                ),
            ],
            {},
            split_features=True,
            feature_similarity_threshold=0.30,
        )

        self.assertEqual(len(compiled.features), 1)
        self.assertEqual(compiled.features[0].scenario_names, [
            "Browse Quote Author Details",
            "Browse Quote Tag Details",
        ])

    def test_weak_singleton_remains_separate(self):
        home = state("s1", "home", "Shop Home Page")
        cart = state("s2", "cart", "Shop Cart Page", "https://shop.example.com/cart")
        admin = state("s3", "admin", "Admin Root Page")
        users = state(
            "s4",
            "users",
            "User Management Page",
            "https://shop.example.com/users",
        )
        compiled = compile_bdd(
            [
                ResolvedFlow(
                    checkpoint=home,
                    transitions=[
                        transition("t1", "cart", "View Shop Cart", home, cart)
                    ],
                ),
                ResolvedFlow(
                    checkpoint=admin,
                    transitions=[
                        transition(
                            "t2",
                            "users",
                            "Manage User Roles",
                            admin,
                            users,
                        )
                    ],
                ),
            ],
            {},
            split_features=True,
        )

        self.assertEqual(len(compiled.features), 2)

    def test_feature_name_collisions_are_numbered(self):
        first = state("s1", "first", "Shopping Home Page")
        cart = state(
            "s2",
            "cart",
            "Shopping Cart Page",
            "https://shop.example.com/cart",
        )
        second = state("s3", "second", "Shopping Search Page")
        checkout = state(
            "s4",
            "checkout",
            "Shopping Checkout Page",
            "https://shop.example.com/checkout",
        )
        compiled = compile_bdd(
            [
                ResolvedFlow(
                    checkpoint=first,
                    transitions=[
                        transition(
                            "t1",
                            "cart",
                            "Open Shopping Cart",
                            first,
                            cart,
                        )
                    ],
                ),
                ResolvedFlow(
                    checkpoint=second,
                    transitions=[
                        transition(
                            "t2",
                            "checkout",
                            "Open Shopping Checkout",
                            second,
                            checkout,
                        )
                    ],
                ),
            ],
            {},
            split_features=True,
            feature_similarity_threshold=1.0,
            singleton_merge_threshold=1.0,
        )

        self.assertEqual(
            [feature.feature_name for feature in compiled.features],
            ["Shopping User Flows 1", "Shopping User Flows 2"],
        )

    def test_duplicate_labels_number_every_collision(self):
        first = state("s1", "product-1", "Product Page")
        second = state("s2", "product-2", "Product Page")
        done = state("s3", "done", "Done Page")
        first_open = transition("t1", "open-1", "Open Item", first, done)
        second_open = transition("t2", "open-2", "Open Item", second, done)

        compiled = compile_bdd(
            [
                ResolvedFlow(checkpoint=first, transitions=[first_open]),
                ResolvedFlow(checkpoint=second, transitions=[second_open]),
            ],
            {},
        )

        self.assertIn("S_PRODUCT_PAGE_1", compiled.states)
        self.assertIn("S_PRODUCT_PAGE_2", compiled.states)
        self.assertIn("T_OPEN_ITEM_1", compiled.transitions)
        self.assertIn("T_OPEN_ITEM_2", compiled.transitions)
        self.assertEqual(
            compiled.states["S_PRODUCT_PAGE_1"]["className"],
            "ProductPage1State",
        )
        self.assertIn("Open Item Scenario 1", compiled.feature_text)
        self.assertIn("Open Item Scenario 2", compiled.feature_text)

    def test_long_scenario_uses_start_and_outcome(self):
        states = [
            state(f"s{index}", f"state-{index}", f"Checkout Step {index}")
            for index in range(5)
        ]
        transitions = [
            transition(
                f"t{index}",
                f"transition-{index}",
                f"Complete Step {index}",
                states[index],
                states[index + 1],
            )
            for index in range(4)
        ]
        compiled = compile_bdd(
            [ResolvedFlow(checkpoint=states[0], transitions=transitions)],
            {},
        )
        self.assertIn(
            "Scenario: Navigate from Checkout Step 0 to Checkout Step 4",
            compiled.feature_text,
        )

    def test_feature_name_uses_hostname_fallback(self):
        start = state("s1", "start", "Home Page", "https://billing.example.com")
        end = state("s2", "end", "Receipt Screen", "https://billing.example.com")
        pay = transition("t1", "pay", "Submit Payment", start, end)
        self.assertEqual(
            infer_feature_name(
                [ResolvedFlow(checkpoint=start, transitions=[pay])]
            ),
            "Billing User Flows",
        )

    def test_renderer_is_extensible_for_hooks_and_assertions(self):
        plan = FeaturePlan(
            name="Checkout User Flows",
            scenarios=[
                ScenarioPlan(
                    name="Pay",
                    steps=[
                        StepPlan(
                            type=StepType.ACTION_HOOK,
                            id="H_WAIT",
                            keyword="And",
                            metadata={"timing": "after"},
                        ),
                        StepPlan(
                            type=StepType.ASSERTION,
                            id="A_PAID",
                            keyword="And",
                        ),
                    ],
                )
            ],
        )
        text = render_feature(plan)
        self.assertIn('And after action I run hook "H_WAIT"', text)
        self.assertIn('And I assert "A_PAID"', text)


class BddRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnected_flow_is_rejected(self):
        result = Mock()
        result.data = AsyncMock(
            return_value=[
                {
                    "flow_index": 0,
                    "transition_index": 0,
                    "checkpoint_db_id": "s1",
                    "checkpoint_hash": "start",
                    "checkpoint_name": "Start Page",
                    "checkpoint_description": "",
                    "checkpoint_url": "/",
                    "checkpoint_status": "COMPLETED",
                    "transition_db_id": "t1",
                    "transition_id": "go",
                    "transition_name": "Go",
                    "transition_action": "Click Go",
                    "action_type": "click",
                    "locator_value": "#go",
                    "transition_status": "COMPLETED",
                    "from_db_id": "wrong",
                    "from_hash": "wrong",
                    "from_name": "Wrong Page",
                    "from_description": "",
                    "from_url": "/wrong",
                    "from_status": "COMPLETED",
                    "to_db_id": "s2",
                    "to_hash": "end",
                    "to_name": "End Page",
                    "to_description": "",
                    "to_url": "/end",
                    "to_status": "COMPLETED",
                }
            ]
        )
        session = Mock()
        session.run = AsyncMock(return_value=result)

        with self.assertRaisesRegex(ValueError, "does not continue"):
            await BddRepository(session).resolve_flows(
                "session",
                [
                    BddFlowInput(
                        checkpoint_hash="start",
                        transition_ids=["go"],
                    )
                ],
            )


class BddTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_labeling_is_claimed_enqueued_and_deferred(self):
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
        redis.enqueue_job = AsyncMock(return_value=Mock())

        with (
            patch("src.tasks.bdd.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.bdd.BddRepository", return_value=repo),
        ):
            with self.assertRaises(Retry):
                await task_generate_bdd(
                    {"redis": redis, "job_try": 1},
                    {
                        "session_id": "session",
                        "flows": [
                            {
                                "checkpoint_hash": "start",
                                "transition_ids": ["go"],
                            }
                        ],
                    },
                )

        redis.enqueue_job.assert_awaited_once_with(
            "task_label_graph",
            "session",
        )
        repo.rollback_claim.assert_not_awaited()

    async def test_enqueue_failure_rolls_back_exact_claim(self):
        repo = Mock()
        repo.get_labeling_status = AsyncMock(
            return_value={
                "state_count": 1,
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
        redis.enqueue_job = AsyncMock(side_effect=RuntimeError("down"))

        with (
            patch("src.tasks.bdd.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.bdd.BddRepository", return_value=repo),
        ):
            with self.assertRaisesRegex(RuntimeError, "down"):
                await task_generate_bdd(
                    {"redis": redis, "job_try": 1},
                    {
                        "session_id": "session",
                        "flows": [
                            {
                                "checkpoint_hash": "start",
                                "transition_ids": ["go"],
                            }
                        ],
                    },
                )

        repo.rollback_claim.assert_awaited_once_with(
            "session",
            ["s1"],
            [],
        )

    async def test_success_payload_contains_features_and_bullmq_job(self):
        home = state("s1", "home", "Shopping Home Page")
        cart = state("s2", "cart", "Shopping Cart Page")
        flow = ResolvedFlow(
            checkpoint=home,
            transitions=[
                transition("t1", "open-cart", "Open Shopping Cart", home, cart)
            ],
        )
        repo = Mock()
        repo.get_labeling_status = AsyncMock(
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
        repo.resolve_flows = AsyncMock(return_value=[flow])
        repo.get_outgoing_locators = AsyncMock(return_value={"home": ["#cart"]})
        redis = Mock()

        with (
            patch("src.tasks.bdd.neo_manager.driver", Driver(Mock())),
            patch("src.tasks.bdd.BddRepository", return_value=repo),
            patch("src.tasks.bdd._enqueue_bullmq_job", new=AsyncMock()) as enqueue,
        ):
            result = await task_generate_bdd(
                {"redis": redis, "job_try": 1},
                {
                    "session_id": "session",
                    "flows": [
                        {
                            "checkpoint_hash": "home",
                            "transition_ids": ["open-cart"],
                        }
                    ],
                },
            )

        self.assertEqual(len(result["features"]), 1)
        self.assertEqual(result["feature_name"], "Shopping User Flows")
        self.assertIn("feature_text", result)
        enqueue.assert_awaited_once()
        self.assertFalse(Path("src/session.feature").exists())


class LoggingStyleTests(unittest.TestCase):
    def test_src_logger_calls_do_not_use_percent_args(self):
        root = Path(__file__).resolve().parents[1] / "src"
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if "logger." not in line:
                    continue
                if '"%s"' in line or "'%s'" in line:
                    offenders.append(f"{path}:{line_number}")
                if '"%d"' in line or "'%d'" in line:
                    offenders.append(f"{path}:{line_number}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
