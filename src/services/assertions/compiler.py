import json
import logging

from src.core.config import Settings
from src.models.bdd import ResolvedFlow, SemanticAssertion
from src.services.assertions.providers import (
    AssertionModelProvider,
    GeminiProvider,
    OpenAICompatibleProvider,
)
from src.services.assertions.scenario_context import build_scenario_contexts
from src.services.assertions.selector import select_semantic_assertions

logger = logging.getLogger("arq.worker.assertions")


class SemanticAssertionService:
    def __init__(
        self,
        settings: Settings,
        provider: AssertionModelProvider | None = None,
    ):
        self.settings = settings
        self.provider = provider or self._provider_from_settings()

    async def generate(
        self,
        flows: list[ResolvedFlow],
        scenario_names: list[str],
    ) -> dict[int, list[SemanticAssertion]]:
        if not self.settings.semantic_assertions_enabled:
            return {}
        if self.provider is None:
            logger.warning(
                "[Assertions] Semantic assertions enabled but no provider is configured"
            )
            return {}

        contexts = build_scenario_contexts(
            flows,
            scenario_names,
            self.settings.semantic_assertions_html_summary_max_chars,
        )
        assertions_by_flow: dict[int, list[SemanticAssertion]] = {}
        for context in contexts:
            try:
                raw = await self.provider.propose_assertions(
                    self._prompt(context.model_payload()),
                    {},
                )
            except Exception as error:
                logger.warning(
                    f"[Assertions] Model provider failed for scenario {context.index}: {error}"
                )
                continue
            print("Model response:")
            print(raw)
            print("=" * 10)
            selected = select_semantic_assertions(
                raw,
                context,
                self.settings.semantic_assertions_min_confidence,
                self.settings.semantic_assertions_max_assertions_per_scenario,
            )
            if selected:
                assertions_by_flow[context.index] = selected

        return assertions_by_flow

    def _provider_from_settings(self) -> AssertionModelProvider | None:
        provider = self.settings.semantic_assertions_provider
        if provider == "gemini":
            if not self.settings.gemini_api_key:
                return None
            return GeminiProvider(
                api_key=self.settings.gemini_api_key,
                model=self.settings.semantic_assertions_gemini_model,
                timeout_seconds=self.settings.semantic_assertions_timeout_seconds,
            )
        if provider == "local_openai_compatible":
            return OpenAICompatibleProvider(
                base_url=self.settings.semantic_assertions_model_base_url,
                model=self.settings.semantic_assertions_model_name,
                timeout_seconds=self.settings.semantic_assertions_timeout_seconds,
            )
        logger.warning(f"[Assertions] Unknown provider '{provider}'")
        return None

    @staticmethod
    def _prompt(context_payload: dict) -> str:
        return (
            "Choose scenario-level semantic assertions for this BDD scenario.\n"
            "The assertion must validate the entire scenario outcome, not just an "
            "isolated page fact.\n\n"
            "RETURN JSON ONLY with this top-level shape:\n"
            '{"assertions":[{"purpose":"...","targetStateDbId":"...",'
            '"label":"...","severity":"blocking","definition":{...},'
            '"confidence":0.0,"reason":"..."}]}\n\n'
            "MUST FOLLOW EXACTLY:\n"
            "- definition must never be {}.\n"
            "- Every definition must include both definition.type and definition.assertion.\n"
            "- Every assertion must use exactly one of the valid definition JSON shapes below.\n"
            "- Use actual state database IDs from the scenario context for targetStateDbId and definition.stateId.\n"
            "- Do not use human labels like 'Login Page' as targetStateDbId or definition.stateId.\n"
            "- For element assertions, use locatorKey from the candidate selector when possible.\n"
            "- If you cannot build one of the valid executable definition shapes, return exactly: "
            '{"assertions":[]}\n\n'
            "VALID definition shapes:\n"
            "1. Page title:\n"
            '{"type":"page","assertion":"title","expectedText":"Login"}\n\n'
            "2. Page URL fragment:\n"
            '{"type":"page","assertion":"url-fragment","expectedFragment":"/login"}\n\n'
            "3. Element visibility:\n"
            '{"type":"element","assertion":"visibility","stateId":"STATE_DB_ID",'
            '"locatorKey":".selector-or-existing-key","visible":true}\n\n'
            "4. Element text:\n"
            '{"type":"element","assertion":"text","stateId":"STATE_DB_ID",'
            '"locatorKey":".selector-or-existing-key","expectedText":"Welcome"}\n\n'
            "5. Element value:\n"
            '{"type":"element","assertion":"value","stateId":"STATE_DB_ID",'
            '"locatorKey":"input[name=\'email\']","expectedValue":"user@example.com"}\n\n'
            "6. Element attribute:\n"
            '{"type":"element","assertion":"attribute","stateId":"STATE_DB_ID",'
            '"locatorKey":"[aria-selected=\'true\']","attributeName":"aria-selected",'
            '"expectedValue":"true"}\n\n'
            "INVALID outputs:\n"
            '- Invalid: "definition": {}\n'
            "- Invalid: definition without type\n"
            "- Invalid: definition without assertion\n"
            "- Invalid: unsupported definition.type values: state, design-operation, user-assertion\n"
            "- Invalid: targetStateDbId or definition.stateId set to a page name instead of an actual state database ID\n"
            "- Invalid: timestamps, UUIDs, random IDs, session tokens, or raw full-page DOM as expected values\n\n"
            "Prefer the final state. Use scenario intent plus final DOM evidence. "
            "If no strong executable scenario assertion exists, return an empty assertions array.\n\n"
            f"Scenario context:\n{json.dumps(context_payload, ensure_ascii=False)}"
        )
