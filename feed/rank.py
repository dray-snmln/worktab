"""Rule-based ranking. No AI needed; every number here comes from [ranking]
and [keywords] in config.toml."""
from __future__ import annotations

import math
import re
from datetime import datetime

from .models import Item

TIERS = ("act", "read", "fyi")


def _pattern(term: str) -> re.Pattern:
    # Whole-term match that still works for "Node.js", "C++", "core web vitals"
    return re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def dedupe(items: list[Item]) -> list[Item]:
    """Same URL or same title counts as one item; the higher-weight source wins."""
    best: dict[str, Item] = {}
    for item in sorted(items, key=lambda i: i.source_weight, reverse=True):
        keys = (item.id, _norm_title(item.title))
        if not any(k in best for k in keys):
            for k in keys:
                best[k] = item
    return list({id(i): i for i in best.values()}.values())


def score(item: Item, keywords: list[tuple[str, re.Pattern, float]], rules: dict, now: datetime) -> None:
    total = item.source_weight
    for term, pattern, weight in keywords:
        if pattern.search(item.title):
            total += weight
        elif pattern.search(item.summary):
            total += weight * rules.get("summary_match_factor", 0.5)
        else:
            continue
        if weight > 0:
            item.matches.append(term)

    # Discussion activity: log scale so one viral post doesn't drown the rest
    activity = (item.points or 0) + 2 * (item.comments or 0)
    total += min(math.log10(1 + activity) * rules.get("activity_factor", 1.5),
                 rules.get("activity_cap", 4))

    if item.published:
        age_days = max((now - item.published).total_seconds(), 0) / 86400
        total -= age_days * rules.get("age_penalty_per_day", 1.0)
    item.score = total


def rank(items: list[Item], cfg: dict, now: datetime) -> list[Item]:
    """Dedupe, drop stale items, score, cap per source, sort best first."""
    rules = cfg.get("ranking", {})
    keywords = [(t, _pattern(t), float(w)) for t, w in cfg.get("keywords", {}).items()]
    max_age = rules.get("max_age_days", 7)

    fresh = [
        i for i in dedupe(items)
        if i.published is None or (now - i.published).days < max_age
    ]
    for item in fresh:
        score(item, keywords, rules, now)

    fresh.sort(key=lambda i: i.score, reverse=True)
    per_source: dict[str, int] = {}
    kept = []
    for item in fresh:
        if item.score < rules.get("drop_below", -5):
            continue
        per_source[item.source] = per_source.get(item.source, 0) + 1
        if per_source[item.source] <= rules.get("max_per_source", 8):
            kept.append(item)
    return kept[: rules.get("max_items", 120)]


def assign_tiers(items: list[Item], cfg: dict) -> None:
    """Run after any AI adjustment so tiers reflect the final score."""
    rules = cfg.get("ranking", {})
    act_at, read_at = rules.get("act_at", 8), rules.get("read_at", 3)
    for item in items:
        if item.source_tier in TIERS:
            item.tier = item.source_tier
        elif item.score >= act_at:
            item.tier = "act"
        elif item.score >= read_at:
            item.tier = "read"
        else:
            item.tier = "fyi"
    items.sort(key=lambda i: (TIERS.index(i.tier), -i.score))
