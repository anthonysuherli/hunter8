# json_reply.py
"""Parse a model's text reply into a JSON object.

Models wrap JSON in markdown fences or prose often enough that both agents
need the same tolerance. Kept here so neither has to copy it.
"""
from __future__ import annotations

import json


def parse_object(content: str) -> dict:
    """Return the JSON object in `content`. Raises ValueError if there isn't one."""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"no JSON object in reply: {content[:200]!r}")
