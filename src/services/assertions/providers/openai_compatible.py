import asyncio
import json
import urllib.request

from src.services.assertions.providers.base import AssertionModelProvider


class OpenAICompatibleProvider(AssertionModelProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: int,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def propose_assertions(self, prompt: str, schema: dict) -> dict:
        return await asyncio.to_thread(self._request, prompt, schema)

    def _request(self, prompt: str, schema: dict) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate executable, scenario-level BDD assertions. "
                        "Return JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "semantic_assertions",
                    "schema": schema,
                    "strict": True,
                },
            },
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)
