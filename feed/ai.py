"""Optional AI pass. Off unless the provider's API key is in the environment.
Any failure leaves the rule-based ranking untouched.

To add a provider: write `call_<name>(prompt, model, api_key) -> str` and add
it to PROVIDERS with the environment variable that holds its key.
"""
from __future__ import annotations

import json
import logging
import os
import re

from .models import Item
from .sources import http_get

log = logging.getLogger(__name__)


def call_anthropic(prompt: str, model: str, api_key: str) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    raw = http_get(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        data=body,
    )
    return "".join(b.get("text", "") for b in json.loads(raw)["content"])


PROVIDERS = {
    # name: (env var holding the key, call function)
    "anthropic": ("ANTHROPIC_API_KEY", call_anthropic),
}

PROMPT = """You rank news for one reader. About them:
{about}

Score each item 0-10 for how useful it is to them today, and write a short
reason (max 12 words) for anything scoring 7 or more. Reply with JSON only:
[{{"id": "...", "score": 0, "why": ""}}]

Items (id | source | title | summary):
{items}"""


def _parse(text: str) -> list[dict]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON array in reply")
    return json.loads(match.group(0))


def rerank(items: list[Item], cfg: dict) -> bool:
    """Adjust scores of the top items in place. Returns True if AI ran."""
    ai_cfg = cfg.get("ai", {})
    name = ai_cfg.get("provider", "anthropic")
    if not ai_cfg.get("enabled", True) or name not in PROVIDERS:
        return False
    env_var, call = PROVIDERS[name]
    api_key = os.environ.get(env_var)
    if not api_key:
        log.info("AI off: %s is not set", env_var)
        return False

    top = items[: ai_cfg.get("max_items", 40)]
    lines = "\n".join(f"{i.id} | {i.source} | {i.title} | {i.summary[:160]}" for i in top)
    prompt = PROMPT.format(about=ai_cfg.get("about", "").strip(), items=lines)
    try:
        results = _parse(call(prompt, ai_cfg["model"], api_key))
    except Exception as exc:
        log.warning("AI skipped, rule ranking kept: %s", exc)
        return False

    by_id = {i.id: i for i in top}
    weight = ai_cfg.get("weight", 1.0)
    for result in results:
        item = by_id.get(str(result.get("id")))
        if item is None:
            continue
        try:
            ai_score = float(result.get("score", 5))
        except (TypeError, ValueError):
            continue
        item.score += (ai_score - 5) * weight   # 5 = neutral, no change
        item.why = str(result.get("why", ""))[:120]
    log.info("AI re-scored %d items with %s", len(top), name)
    return True
