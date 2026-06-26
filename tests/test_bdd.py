import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from arq import Retry

from src.models.bdd import (
    BddTransitionAction,
    BddFlowInput,
    FeaturePlan,
    FlowEditorDraftStep,
    FlowEditorPosition,
    FlowEditorPositionEdge,
    FlowEditorStepKind,
    ResolvedFlow,
    ResolvedState,
    ResolvedTransition,
    ScenarioPlan,
    SemanticAssertion,
    StepPlan,
    StepType,
)
from src.models.queries import (
    CLAIM_BDD_FLOW_LABELING,
    CLAIM_BDD_GRAPH_LABELING,
    GET_BDD_FLOW_LABELING_STATUS,
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


def resolved_row(**overrides):
    row = {
        "flow_index": 0,
        "transition_index": 0,
        "checkpoint_db_id": "s1",
        "checkpoint_hash": "start",
        "checkpoint_name": "Start Page",
        "checkpoint_description": "",
        "checkpoint_url": "/",
        "checkpoint_html": "<h1>Start</h1>",
        "checkpoint_status": "COMPLETED",
        "transition_db_id": "t1",
        "transition_id": "go",
        "transition_name": "Go",
        "transition_action": "Click Go",
        "action_type": "click",
        "locator_value": "#go",
        "action_value": "",
        "transition_status": "COMPLETED",
        "from_db_id": "s1",
        "from_hash": "start",
        "from_name": "Start Page",
        "from_description": "",
        "from_url": "/",
        "from_html": "<h1>Start</h1>",
        "from_status": "COMPLETED",
        "to_db_id": "s2",
        "to_hash": "end",
        "to_name": "End Page",
        "to_description": "",
        "to_url": "/end",
        "to_html": "<h1>End</h1>",
        "to_status": "COMPLETED",
    }
    row.update(overrides)
    return row


class BddQueryTests(unittest.TestCase):
    def test_preflight_and_claim_are_graph_scoped(self):
        self.assertGreaterEqual(
            GET_BDD_LABELING_STATUS.count(
                "{graph_id: $graph_id}"
            ),
            3,
        )
        self.assertIn("labeling_status IS NULL", CLAIM_BDD_GRAPH_LABELING)
        self.assertIn("labeling_claim_id = $claim_id", CLAIM_BDD_GRAPH_LABELING)
        self.assertIn("labeling_status = 'QUEUED'", CLAIM_BDD_GRAPH_LABELING)

    def test_flow_preflight_and_claim_are_requested_flow_scoped(self):
        self.assertIn("UNWIND $flows AS flow", GET_BDD_FLOW_LABELING_STATUS)
        self.assertIn("flow.checkpoint_hash", GET_BDD_FLOW_LABELING_STATUS)
        self.assertIn("flow.transition_ids", GET_BDD_FLOW_LABELING_STATUS)
        self.assertIn("UNWIND $flows AS flow", CLAIM_BDD_FLOW_LABELING)
        self.assertIn("flow.checkpoint_hash", CLAIM_BDD_FLOW_LABELING)
        self.assertIn("flow.transition_ids", CLAIM_BDD_FLOW_LABELING)
        self.assertIn("labeling_claim_id = $claim_id", CLAIM_BDD_FLOW_LABELING)

    def test_resolution_preserves_input_order_and_graph(self):
        self.assertIn("flow.flow_index", RESOLVE_BDD_FLOWS)
        self.assertIn("transition_index", RESOLVE_BDD_FLOWS)
        self.assertIn("ORDER BY flow_index, transition_index", RESOLVE_BDD_FLOWS)
        self.assertIn("checkpoint.html AS checkpoint_html", RESOLVE_BDD_FLOWS)
        self.assertIn("from.html AS from_html", RESOLVE_BDD_FLOWS)
        self.assertIn("to.html AS to_html", RESOLVE_BDD_FLOWS)
        self.assertIn("transition.action_value AS action_value", RESOLVE_BDD_FLOWS)
        self.assertGreaterEqual(
            RESOLVE_BDD_FLOWS.count("graph_id: $graph_id"),
            4,
        )
        self.assertIn("$state_hashes", GET_BDD_OUTGOING_LOCATORS)


class BddCompilerTests(unittest.TestCase):
    def test_user_editor_steps_use_generated_names_in_bdd_and_mappings(self):
        home = state("s1", "home", "Checkout Page")
        done = state("s2", "done", "Done Page")
        submit = transition("t1", "submit", "Submit Checkout", home, done)
        flow = ResolvedFlow(
            checkpoint=home,
            transitions=[submit],
            editor_steps=[
                FlowEditorDraftStep(
                    id="editor-assertion",
                    kind=FlowEditorStepKind.ASSERTION,
                    position=FlowEditorPosition(
                        transitionId="submit",
                        edge=FlowEditorPositionEdge.AFTER,
                    ),
                    label="Check success message",
                ),
                FlowEditorDraftStep(
                    id="editor-hook",
                    kind=FlowEditorStepKind.ACTION_HOOK,
                    position=FlowEditorPosition(
                        transitionId="submit",
                        edge=FlowEditorPositionEdge.BEFORE,
                    ),
                    label="Wait before submit",
                ),
                FlowEditorDraftStep(
                    id="editor-design",
                    kind=FlowEditorStepKind.DESIGN_CLASS,
                    position=FlowEditorPosition(
                        transitionId="submit",
                        edge=FlowEditorPositionEdge.AFTER,
                    ),
                    label="Checkout visual rules",
                ),
            ],
        )

        compiled = asyncio.run(compile_bdd([flow], {}))
        feature_text = compiled.features[0].feature_text

        self.assertIn('And I assert "ASSERTION_1"', feature_text)
        self.assertIn('And before action I run hook "HOOK_1"', feature_text)
        self.assertIn('And I use design class "DESIGN_CLASS_1"', feature_text)
        self.assertNotIn("Check success message", feature_text)
        self.assertNotIn("Wait before submit", feature_text)
        self.assertNotIn("Checkout visual rules", feature_text)

        self.assertIn("ASSERTION_1", compiled.assertions)
        self.assertIn("HOOK_1", compiled.action_hooks)
        self.assertIn("DESIGN_CLASS_1", compiled.design_classes)
        self.assertNotIn("editor-assertion", compiled.assertions)
        self.assertNotIn("editor-hook", compiled.action_hooks)
        self.assertNotIn("editor-design", compiled.design_classes)

        assertion = compiled.assertions["ASSERTION_1"]
        hook = compiled.action_hooks["HOOK_1"]
        design = compiled.design_classes["DESIGN_CLASS_1"]

        self.assertEqual(assertion["id"], "ASSERTION_1")
        self.assertEqual(assertion["transitionId"], "T_SUBMIT_CHECKOUT")
        self.assertEqual(assertion["stateId"], "S_DONE_PAGE")
        self.assertEqual(hook["id"], "HOOK_1")
        self.assertEqual(hook["transitionId"], "T_SUBMIT_CHECKOUT")
        self.assertEqual(design["id"], "DESIGN_CLASS_1")
        self.assertEqual(design["transitionId"], "T_SUBMIT_CHECKOUT")
        self.assertEqual(design["stateId"], "S_DONE_PAGE")

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
        transition_mapping = compiled.transitions["T_OPEN_SHOPPING_CART"]
        self.assertNotIn("action", transition_mapping)
        self.assertEqual(
            transition_mapping["actions"],
            [
                {
                    "type": "click",
                    "stateId": "S_SHOPPING_HOME_PAGE",
                    "locatorKey": "#open-cart",
                }
            ],
        )
        self.assertEqual(compiled.assertions, {})

    def test_compiles_multistep_transition_actions_and_locators(self):
        login = state("s1", "login", "Login Page")
        dashboard = state("s2", "dashboard", "Dashboard Page")
        submit_login = ResolvedTransition(
            db_id="t1",
            transition_id="login",
            name="Login",
            action='Fill "Email" then Click "Sign in"',
            action_type="click",
            locator_value="#submit",
            actions=[
                BddTransitionAction(
                    selector="#email",
                    action_type="type",
                    value="user@example.com",
                ),
                BddTransitionAction(selector="#submit", action_type="click"),
            ],
            labeling_status="COMPLETED",
            from_state=login,
            to_state=dashboard,
        )

        compiled = compile_bdd(
            [ResolvedFlow(checkpoint=login, transitions=[submit_login])],
            {"login": []},
        )

        transition_mapping = compiled.transitions["T_LOGIN"]
        self.assertEqual(
            transition_mapping["actions"],
            [
                {
                    "type": "fill",
                    "stateId": "S_LOGIN_PAGE",
                    "locatorKey": "#email",
                    "value": "user@example.com",
                },
                {
                    "type": "click",
                    "stateId": "S_LOGIN_PAGE",
                    "locatorKey": "#submit",
                },
            ],
        )
        self.assertEqual(
            compiled.states["S_LOGIN_PAGE"]["dom"]["elements"],
            {
                "#email": {"cssSelector": "#email"},
                "#submit": {"cssSelector": "#submit"},
            },
        )

    def test_compiles_navigate_action_with_url(self):
        home = state("s1", "home", "Home Page")
        account = state("s2", "account", "Account Page")
        open_account = ResolvedTransition(
            db_id="t1",
            transition_id="open-account",
            name="Open Account",
            action="Navigate to account",
            action_type="navigate",
            locator_value="https://shop.example.com/account",
            actions=[
                BddTransitionAction(
                    selector="https://shop.example.com/account",
                    action_type="navigate",
                    value="https://shop.example.com/account",
                )
            ],
            labeling_status="COMPLETED",
            from_state=home,
            to_state=account,
        )

        compiled = compile_bdd(
            [ResolvedFlow(checkpoint=home, transitions=[open_account])],
            {"home": []},
        )

        action = compiled.transitions["T_OPEN_ACCOUNT"]["actions"][0]
        self.assertEqual(
            action,
            {
                "type": "navigate",
                "stateId": "S_HOME_PAGE",
                "url": "https://shop.example.com/account",
            },
        )
        self.assertEqual(compiled.states["S_HOME_PAGE"]["dom"]["elements"], {})

    def test_compiles_scenario_level_semantic_assertion(self):
        home = state("s1", "home", "Product Page")
        cart = state("s2", "cart", "Cart Page")
        add_to_cart = transition("t1", "add-cart", "Add Product To Cart", home, cart)
        assertion = SemanticAssertion(
            id="A_SCENARIO_CART_CONTAINS_ADDED_PRODUCT",
            db_id="semantic:scenario:0:A_SCENARIO_CART_CONTAINS_ADDED_PRODUCT",
            label="Cart contains the added product",
            description="Validates the complete add-to-cart scenario outcome.",
            target_state_db_id="s2",
            context_id="scenario:0",
            definition={
                "type": "element",
                "assertion": "text",
                "stateId": "s2",
                "locatorKey": ".cart-items",
                "expectedText": "Product name",
            },
            semantic={
                "scope": "scenario",
                "source": "model",
                "confidence": 0.82,
            },
        )

        compiled = compile_bdd(
            [ResolvedFlow(checkpoint=home, transitions=[add_to_cart])],
            {"cart": [".cart-items"]},
            semantic_assertions_by_flow_index={0: [assertion]},
        )

        self.assertIn(
            'And I assert "A_SCENARIO_CART_CONTAINS_ADDED_PRODUCT"',
            compiled.feature_text,
        )
        assertion_mapping = compiled.assertions[
            "A_SCENARIO_CART_CONTAINS_ADDED_PRODUCT"
        ]
        self.assertEqual(assertion_mapping["targetId"], "S_CART_PAGE")
        self.assertEqual(
            assertion_mapping["definition"]["stateId"],
            "S_CART_PAGE",
        )
        self.assertEqual(assertion_mapping["semantic"]["scope"], "scenario")

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

    def test_renderer_adds_flow_id_comment_before_scenario(self):
        plan = FeaturePlan(
            name="Checkout User Flows",
            scenarios=[
                ScenarioPlan(
                    name="Pay",
                    flow_id="flow-1",
                    steps=[
                        StepPlan(
                            type=StepType.ACTION_HOOK,
                            id="H_WAIT",
                            keyword="And",
                        ),
                    ],
                )
            ],
        )

        self.assertIn(
            "  # Flow ID: flow-1\n  Scenario: Pay",
            render_feature(plan),
        )


class BddRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolved_flow_preserves_input_flow_id(self):
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
                    "checkpoint_html": "<h1>Start</h1>",
                    "checkpoint_status": "COMPLETED",
                    "transition_db_id": "t1",
                    "transition_id": "go",
                    "transition_name": "Go",
                    "transition_action": "Click Go",
                    "action_type": "click",
                    "locator_value": "#go",
                    "action_value": "",
                    "transition_status": "COMPLETED",
                    "from_db_id": "s1",
                    "from_hash": "start",
                    "from_name": "Start Page",
                    "from_description": "",
                    "from_url": "/",
                    "from_html": "<h1>Start</h1>",
                    "from_status": "COMPLETED",
                    "to_db_id": "s2",
                    "to_hash": "end",
                    "to_name": "End Page",
                    "to_description": "",
                    "to_url": "/end",
                    "to_html": "<h1>End</h1>",
                    "to_status": "COMPLETED",
                }
            ]
        )
        session = Mock()
        session.run = AsyncMock(return_value=result)

        flows = await BddRepository(session).resolve_flows(
            "graph-1",
            [
                BddFlowInput(
                    flow_id="flow-1",
                    checkpoint_hash="start",
                    transition_ids=["go"],
                )
            ],
        )

        self.assertEqual(flows[0].flow_id, "flow-1")
        self.assertEqual(flows[0].transitions[0].actions[0].selector, "#go")
        self.assertEqual(flows[0].transitions[0].actions[0].action_type, "click")

    async def test_resolved_transition_parses_multistep_action_value(self):
        result = Mock()
        result.data = AsyncMock(
            return_value=[
                resolved_row(
                    transition_id="login",
                    transition_name="Login",
                    transition_action='Fill "Email" then Click "Sign in"',
                    action_value=(
                        '[{"s":"#email","t":"type","v":"user@example.com"},'
                        '{"s":"#submit","t":"click","d":"Click Sign in"}]'
                    ),
                )
            ]
        )
        session = Mock()
        session.run = AsyncMock(return_value=result)

        flows = await BddRepository(session).resolve_flows(
            "graph-1",
            [BddFlowInput(checkpoint_hash="start", transition_ids=["login"])],
        )

        actions = flows[0].transitions[0].actions
        self.assertEqual([action.selector for action in actions], ["#email", "#submit"])
        self.assertEqual([action.action_type for action in actions], ["fill", "click"])
        self.assertEqual(actions[0].value, "user@example.com")

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
                    "checkpoint_html": "<h1>Start</h1>",
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
                    "from_html": "<h1>Wrong</h1>",
                    "from_status": "COMPLETED",
                    "to_db_id": "s2",
                    "to_hash": "end",
                    "to_name": "End Page",
                    "to_description": "",
                    "to_url": "/end",
                    "to_html": "<h1>End</h1>",
                    "to_status": "COMPLETED",
                }
            ]
        )
        session = Mock()
        session.run = AsyncMock(return_value=result)

        with self.assertRaisesRegex(ValueError, "does not continue"):
            await BddRepository(session).resolve_flows(
                "graph-1",
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
                        "graph_id": "graph-1",
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
            "graph-1",
        )
        repo.claim_unlabeled.assert_awaited_once()
        self.assertEqual(repo.claim_unlabeled.await_args.args[0], "graph-1")
        self.assertEqual(
            repo.claim_unlabeled.await_args.args[2],
            repo.get_labeling_status.await_args.args[1],
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
            result = await task_generate_bdd(
                {"redis": redis, "job_try": 1},
                {
                    "graph_id": "graph-1",
                    "flows": [
                        {
                            "checkpoint_hash": "start",
                            "transition_ids": ["go"],
                        }
                    ],
                },
            )

        repo.rollback_claim.assert_awaited_once_with(
            "graph-1",
            ["s1"],
            [],
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["graph_id"], "graph-1")
        self.assertEqual(result["lastError"], "down")

    async def test_success_payload_contains_features_and_bullmq_job(self):
        home = state("s1", "home", "Shopping Home Page")
        cart = state("s2", "cart", "Shopping Cart Page")
        flow = ResolvedFlow(
            flow_id="flow-1",
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
                    "graph_id": "graph-1",
                    "session_id": "session-1",
                    "flow_ids": ["flow-top"],
                    "regression_codebase_id": "codebase-1",
                    "codegen_config": {
                        "codegenBranch": "auto-tests",
                        "prTargetBranch": "main",
                    },
                    "flows": [
                        {
                            "flow_id": "flow-1",
                            "checkpoint_hash": "home",
                            "transition_ids": ["open-cart"],
                        }
                    ],
                },
            )

        self.assertEqual(len(result["features"]), 1)
        self.assertEqual(result["graph_id"], "graph-1")
        self.assertEqual(result["feature_name"], "Shopping User Flows")
        self.assertIn("feature_text", result)
        self.assertIn("# Flow ID: flow-1", result["feature_text"])
        self.assertEqual(result["flow_ids"], ["flow-top", "flow-1"])
        self.assertEqual(result["regression_codebase_id"], "codebase-1")
        self.assertEqual(
            result["codegen_config"],
            {
                "codegenBranch": "auto-tests",
                "prTargetBranch": "main",
            },
        )
        enqueue.assert_awaited_once()
        repo.get_labeling_status.assert_awaited_once()
        self.assertEqual(repo.get_labeling_status.await_args.args[0], "graph-1")
        self.assertEqual(
            repo.get_labeling_status.await_args.args[1],
            repo.resolve_flows.await_args.args[1],
        )
        repo.resolve_flows.assert_awaited_once()
        self.assertEqual(repo.resolve_flows.await_args.args[0], "graph-1")
        repo.get_outgoing_locators.assert_awaited_once()
        self.assertEqual(repo.get_outgoing_locators.await_args.args[0], "graph-1")
        self.assertEqual(enqueue.await_args.args[3]["graph_id"], "graph-1")
        self.assertEqual(enqueue.await_args.args[3]["flow_ids"], ["flow-top", "flow-1"])
        self.assertEqual(enqueue.await_args.args[3]["regression_codebase_id"], "codebase-1")
        self.assertFalse(Path("src/session.feature").exists())

    async def test_artifact_save_failure_does_not_enqueue_bullmq_job(self):
        home = state("s1", "home", "Shopping Home Page")
        cart = state("s2", "cart", "Shopping Cart Page")
        flow = ResolvedFlow(
            flow_id="flow-1",
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
            patch(
                "src.tasks.bdd.save_result_payload",
                side_effect=RuntimeError("disk down"),
            ),
            patch("src.tasks.bdd._enqueue_bullmq_job", new=AsyncMock()) as enqueue,
        ):
            result = await task_generate_bdd(
                {"redis": redis, "job_try": 1},
                {
                    "graph_id": "graph-1",
                    "session_id": "session-1",
                    "flows": [
                        {
                            "flow_id": "flow-1",
                            "checkpoint_hash": "home",
                            "transition_ids": ["open-cart"],
                        }
                    ],
                },
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["graph_id"], "graph-1")
        self.assertEqual(result["lastError"], "disk down")
        enqueue.assert_not_awaited()


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
