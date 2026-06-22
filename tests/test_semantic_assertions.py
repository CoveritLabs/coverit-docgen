import unittest

from src.core.config import Settings
from src.models.bdd import ResolvedFlow, ResolvedState, ResolvedTransition
from src.services.assertions.compiler import SemanticAssertionService
from src.services.assertions.html_summarizer import summarize_html
from src.services.assertions.scenario_context import build_scenario_contexts
from src.services.assertions.selector import select_semantic_assertions



def state(db_id, state_hash, name, html, url="https://shop.example.com"):
    return ResolvedState(
        db_id=db_id,
        state_hash=state_hash,
        name=name,
        description=f"{name} description",
        url=url,
        html=html,
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


class DummyProvider:
    def __init__(self, response):
        self.response = response
        self.prompts = []

    async def propose_assertions(self, prompt: str, schema: dict) -> dict:
        self.prompts.append((prompt, schema))
        return self.response


class SemanticAssertionTests(unittest.TestCase):
    def test_html_summary_extracts_stable_candidate_selectors(self):
        summary = summarize_html(
            """
            <html><title>Cart</title><body>
              <h1>Your Cart</h1>
              <div data-testid="cart-items">Product name</div>
              <span>2026-06-22</span>
            </body></html>
            """
        )

        self.assertEqual(summary.title, "Cart")
        self.assertIn("Your Cart", summary.headings)
        self.assertNotIn("2026-06-22", summary.visible_text)
        self.assertIn(
            '[data-testid="cart-items"]',
            [candidate.selector for candidate in summary.candidates],
        )

    def test_builds_scenario_context_for_entire_flow(self):
        product = state("s1", "product", "Product Page", "<h1>Product</h1>")
        cart = state(
            "s2",
            "cart",
            "Cart Page",
            '<h1>Cart</h1><div class="cart-items">Product name</div>',
        )
        flow = ResolvedFlow(
            checkpoint=product,
            transitions=[transition("t1", "add-cart", "Add Product To Cart", product, cart)],
        )

        contexts = build_scenario_contexts([flow], ["Add Product To Cart"], 12000)

        self.assertEqual(contexts[0].model_payload()["scope"], "scenario")
        self.assertEqual(contexts[0].final_state.db_id, "s2")
        self.assertEqual(contexts[0].transitions[0].name, "Add Product To Cart")

    def test_selector_accepts_supported_scenario_assertion(self):
        product = state("s1", "product", "Product Page", "<h1>Product</h1>")
        cart = state("s2", "cart", "Cart Page", '<div class="cart-items">Product name</div>')
        context = build_scenario_contexts(
            [
                ResolvedFlow(
                    checkpoint=product,
                    transitions=[transition("t1", "add-cart", "Add Product To Cart", product, cart)],
                )
            ],
            ["Add Product To Cart"],
            12000,
        )[0]
        raw = {
            "assertions": [
                {
                    "purpose": "cart contains added product",
                    "targetStateDbId": "s2",
                    "label": "Cart contains added product",
                    "severity": "blocking",
                    "definition": {
                        "type": "element",
                        "assertion": "text",
                        "stateId": "s2",
                        "locatorKey": ".cart-items",
                        "expectedText": "Product name",
                    },
                    "confidence": 0.9,
                    "reason": "The scenario adds a product and lands on the cart.",
                }
            ]
        }

        selected = select_semantic_assertions(raw, context, 0.65, 1)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].semantic["scope"], "scenario")
        self.assertEqual(selected[0].definition["assertion"], "text")

    def test_selector_rejects_low_confidence_and_unsupported_types(self):
        product = state("s1", "product", "Product Page", "<h1>Product</h1>")
        cart = state("s2", "cart", "Cart Page", "<h1>Cart</h1>")
        context = build_scenario_contexts(
            [
                ResolvedFlow(
                    checkpoint=product,
                    transitions=[transition("t1", "add-cart", "Add Product To Cart", product, cart)],
                )
            ],
            ["Add Product To Cart"],
            12000,
        )[0]
        raw = {
            "assertions": [
                {
                    "purpose": "cart screenshot matches",
                    "targetStateDbId": "s2",
                    "label": "Cart screenshot matches",
                    "severity": "blocking",
                    "definition": {
                        "type": "state",
                        "assertion": "screenshot",
                        "stateId": "s2",
                    },
                    "confidence": 0.99,
                    "reason": "Unsupported in v1.",
                },
                {
                    "purpose": "cart url",
                    "targetStateDbId": "s2",
                    "label": "Cart URL",
                    "severity": "blocking",
                    "definition": {
                        "type": "page",
                        "assertion": "url-fragment",
                        "expectedFragment": "/cart",
                    },
                    "confidence": 0.1,
                    "reason": "Too weak.",
                },
            ]
        }

        self.assertEqual(select_semantic_assertions(raw, context, 0.65, 1), [])

    def test_selector_rejects_empty_and_incomplete_definitions(self):
        product = state("s1", "product", "Product Page", "<h1>Product</h1>")
        login = state("s2", "login", "Login Page", "<h1>Login</h1>")
        context = build_scenario_contexts(
            [
                ResolvedFlow(
                    checkpoint=product,
                    transitions=[transition("t1", "open-login", "Open Login", product, login)],
                )
            ],
            ["Open Login"],
            12000,
        )[0]
        raw = {
            "assertions": [
                {
                    "purpose": "validate successful login",
                    "targetStateDbId": "s2",
                    "label": "Login page is displayed",
                    "severity": "blocking",
                    "definition": {},
                    "confidence": 1.0,
                    "reason": "Empty definitions are not executable.",
                },
                {
                    "purpose": "validate login title",
                    "targetStateDbId": "s2",
                    "label": "Login title is displayed",
                    "severity": "blocking",
                    "definition": {"type": "page", "expectedText": "Login"},
                    "confidence": 1.0,
                    "reason": "Missing assertion field.",
                },
            ]
        }

        self.assertEqual(select_semantic_assertions(raw, context, 0.65, 1), [])

    def test_selector_accepts_valid_page_definition_shapes(self):
        product = state("s1", "product", "Product Page", "<h1>Product</h1>")
        login = state("s2", "login", "Login Page", "<title>Login</title>")
        context = build_scenario_contexts(
            [
                ResolvedFlow(
                    checkpoint=product,
                    transitions=[transition("t1", "open-login", "Open Login", product, login)],
                )
            ],
            ["Open Login"],
            12000,
        )[0]

        title_result = select_semantic_assertions(
            {
                "assertions": [
                    {
                        "purpose": "login title is visible",
                        "targetStateDbId": "s2",
                        "label": "Login title is visible",
                        "severity": "blocking",
                        "definition": {
                            "type": "page",
                            "assertion": "title",
                            "expectedText": "Login",
                        },
                        "confidence": 0.9,
                        "reason": "The scenario ends on the login page.",
                    }
                ]
            },
            context,
            0.65,
            1,
        )
        fragment_result = select_semantic_assertions(
            {
                "assertions": [
                    {
                        "purpose": "login url is reached",
                        "targetStateDbId": "s2",
                        "label": "Login URL is reached",
                        "severity": "blocking",
                        "definition": {
                            "type": "page",
                            "assertion": "url-fragment",
                            "expectedFragment": "/login",
                        },
                        "confidence": 0.9,
                        "reason": "The scenario should navigate to the login area.",
                    }
                ]
            },
            context,
            0.65,
            1,
        )

        self.assertEqual(title_result[0].definition["assertion"], "title")
        self.assertEqual(
            fragment_result[0].definition["assertion"],
            "url-fragment",
        )

    def test_selector_generates_compact_assertion_ids_from_definition(self):
        home = state("s1", "home", "Home Page", "<h1>Home</h1>")
        login = state("s2", "login", "Login Page", "<h1>Login</h1>")
        context = build_scenario_contexts(
            [
                ResolvedFlow(
                    checkpoint=home,
                    transitions=[transition("t1", "open-login", "Open Login", home, login)],
                )
            ],
            ["Open Login"],
            12000,
        )[0]

        selected = select_semantic_assertions(
            {
                "assertions": [
                    {
                        "purpose": "verify the user is on the login page after clicking the login link",
                        "targetStateDbId": "s2",
                        "label": "Login page is displayed",
                        "severity": "blocking",
                        "definition": {
                            "type": "page",
                            "assertion": "url-fragment",
                            "expectedFragment": "/login",
                        },
                        "confidence": 0.9,
                        "reason": "The scenario should navigate to the login page.",
                    }
                ]
            },
            context,
            0.65,
            1,
        )

        self.assertEqual(selected[0].id, "A_LOGIN_URL_FRAGMENT")
        self.assertNotIn("VERIFY_THE_USER", selected[0].id)

    def test_prompt_names_exact_definition_shapes_and_invalid_examples(self):
        prompt = SemanticAssertionService._prompt(
            {
                "scenarioIndex": 0,
                "scenarioName": "Open Login",
                "scope": "scenario",
            }
        )

        self.assertIn("definition must never be {}", prompt)
        self.assertIn('"type":"page","assertion":"title"', prompt)
        self.assertIn('"type":"page","assertion":"url-fragment"', prompt)
        self.assertIn('"type":"element","assertion":"text"', prompt)
        self.assertIn('- Invalid: "definition": {}', prompt)


class SemanticAssertionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_service_uses_provider_and_returns_assertions_by_flow_index(self):
        product = state("s1", "product", "Product Page", "<h1>Product</h1>")
        cart = state("s2", "cart", "Cart Page", '<div class="cart-items">Product name</div>')
        flow = ResolvedFlow(
            checkpoint=product,
            transitions=[transition("t1", "add-cart", "Add Product To Cart", product, cart)],
        )
        provider = DummyProvider(
            {
                "assertions": [
                    {
                        "purpose": "cart contains added product",
                        "targetStateDbId": "s2",
                        "label": "Cart contains added product",
                        "severity": "blocking",
                        "definition": {
                            "type": "element",
                            "assertion": "text",
                            "stateId": "s2",
                            "locatorKey": ".cart-items",
                            "expectedText": "Product name",
                        },
                        "confidence": 0.9,
                        "reason": "The scenario adds a product and lands on the cart.",
                    }
                ]
            }
        )
        settings = Settings(semantic_assertions_enabled=True)

        result = await SemanticAssertionService(settings, provider).generate(
            [flow],
            ["Add Product To Cart"],
        )

        self.assertIn(0, result)
        self.assertEqual(result[0][0].semantic["source"], "model")
        self.assertIn("scenario-level", provider.prompts[0][0])


if __name__ == "__main__":
    unittest.main()
