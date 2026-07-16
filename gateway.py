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
        # Some gateway models reject response_format; ask for JSON in the prompt
        # and parse (strip markdown fences if present).
        sys = system + "\n\nRespond with a single JSON object only. No markdown."
        try:
            comp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": sys},
                          {"role": "user", "content": user}],
                temperature=0.2,
            )
        except openai.APIStatusError as exc:
            if getattr(exc.response, "status_code", None) == 402:
                raise GatewayError(
                    "AI Gateway has no credit (402). Top up at "
                    "vercel.com → AI → top-up, or set a different key."
                ) from exc
            raise GatewayError(f"AI Gateway error: {exc}") from exc

        content = (comp.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:].strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            # Last resort: extract first {...} block
            start, end = content.find("{"), content.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    pass
            raise GatewayError(f"Gateway returned non-JSON: {content[:200]!r}") from exc
