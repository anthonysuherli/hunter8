# gateway.py
from __future__ import annotations

import json

import openai
from openai import OpenAI

DEFAULT_BASE_URL = "https://ai-gateway.vercel.sh/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


class GatewayError(RuntimeError):
    """Raised for gateway failures with an actionable message."""


class Gateway:
    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL,
                 base_url: str = DEFAULT_BASE_URL) -> None:
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat_json(self, system: str, user: str) -> dict:
        """One chat turn expected to return a JSON object. Raises GatewayError with
        a clear message on 402 (out of credit) or unparseable output."""
        try:
            comp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        except openai.APIStatusError as exc:
            if getattr(exc.response, "status_code", None) == 402:
                raise GatewayError(
                    "AI Gateway has no credit (402). Top up at "
                    "vercel.com → AI → top-up, or set a different key."
                ) from exc
            raise GatewayError(f"AI Gateway error: {exc}") from exc

        content = comp.choices[0].message.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise GatewayError(f"Gateway returned non-JSON: {content[:200]!r}") from exc
