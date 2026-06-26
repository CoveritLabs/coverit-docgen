import asyncio
import json
import urllib.request
import urllib.error

from src.services.assertions.providers.base import AssertionModelProvider


class GeminiProvider(AssertionModelProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: int,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def propose_assertions(self, prompt: str, schema: dict) -> dict:
        return await asyncio.to_thread(self._request, prompt)

    def _request(self, prompt: str) -> dict:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": _gemini_compatible_schema(),
            },
        }

        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise RuntimeError(f"Gemini API error {e.code}: {error_body}") from e

        text = body["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)


def _gemini_compatible_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "assertions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "purpose": {"type": "string"},
                        "targetStateDbId": {"type": "string"},
                        "contextTransitionDbId": {"type": "string"},
                        "label": {"type": "string"},
                        "description": {"type": "string"},
                        "severity": {
                            "type": "string",
                            "enum": ["blocking", "warning", "info"],
                        },
                        "definition": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["page", "element"],
                                },
                                "assertion": {
                                    "type": "string",
                                    "enum": [
                                        "title",
                                        "url-fragment",
                                        "visibility",
                                        "text",
                                        "value",
                                        "attribute",
                                    ],
                                },
                                "stateId": {"type": "string"},
                                "locatorKey": {"type": "string"},
                                "locator": {"type": "object"},
                                "visible": {"type": "boolean"},
                                "expectedText": {"type": "string"},
                                "expectedFragment": {"type": "string"},
                                "expectedValue": {"type": "string"},
                                "attributeName": {"type": "string"},
                            },
                            "required": ["type", "assertion"],
                        },
                        "confidence": {"type": "number"},
                        "reason": {"type": "string"},
                    },
                    "required": [
                        "purpose",
                        "targetStateDbId",
                        "label",
                        "severity",
                        "definition",
                        "confidence",
                        "reason",
                    ],
                },
            },
        },
        "required": ["assertions"],
    }
