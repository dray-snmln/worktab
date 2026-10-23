"""Fetch items from sources.

To add a source type: write `fetch_<type>(src) -> list[Item]` and add it to
FETCHERS at the bottom. `src` is one [[sources]] table from config.toml.
"""
from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import Item

log = logging.getLogger(__name__)

USER_AGENT = "worktab-feed/1.0"
TIMEOUT_SECONDS = 20
SUMMARY_CHARS = 280


# ---------------------------------------------------------------- helpers

def http_get(url: str, headers: dict | None = None, data: bytes | None = None) -> bytes:
    req = Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return resp.read()


_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


def clean_text(raw: str, limit: int = SUMMARY_CHARS) -> str:
    """HTML fragment -> short plain text."""
    text = _SPACES.sub(" ", html.unescape(_TAGS.sub(" ", raw or ""))).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def parse_date(value: str) -> datetime | None:
    """RFC 822 (RSS) or ISO 8601 (Atom/APIs) -> aware UTC datetime."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_web_url(url: str) -> bool:
    return url.startswith(("https://", "http://"))


def make_item(src: dict, **fields) -> Item:
    return Item(
        source=src["name"],
        group=src.get("group", "Other"),
        source_weight=float(src.get("weight", 0)),
        source_tier=src.get("tier", ""),
        **fields,
    )


# ---------------------------------------------------------------- RSS / Atom

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]          # drop XML namespace


def _first_text(el: ET.Element, *names: str) -> str:
    for child in el:
        if _local(child.tag) in names and (child.text or "").strip():
            return child.text.strip()
    return ""


def _link(el: ET.Element) -> str:
    """Atom: <link rel="alternate" href>; RSS: <link>text</link>."""
    fallback = ""
    for child in el:
        if _local(child.tag) != "link":
            continue
        href = child.get("href")
        if href and child.get("rel", "alternate") == "alternate":
            return href
        fallback = fallback or href or (child.text or "").strip()
    return fallback


def parse_feed(data: bytes) -> list[dict]:
    entries = []
    for el in ET.fromstring(data).iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        entries.append({
            "title": clean_text(_first_text(el, "title"), limit=200),
            "url": _link(el),
            "published": parse_date(_first_text(el, "pubDate", "published", "updated", "date")),
            "summary": clean_text(_first_text(el, "description", "summary", "encoded", "content")),
        })
    return entries


def fetch_rss(src: dict) -> list[Item]:
    return [
        make_item(src, **entry)
        for entry in parse_feed(http_get(src["url"]))
        if entry["title"] and is_web_url(entry["url"])
    ]


# ---------------------------------------------------------------- Hacker News

def fetch_hn(src: dict) -> list[Item]:
    """Stories matching `query` with at least `min_points`, from the last `days`."""
    since = int(time.time()) - int(src.get("days", 3)) * 86400
    params = urlencode({
        "query": src["query"],
        "tags": "story",
        "numericFilters": f"points>={src.get('min_points', 50)},created_at_i>={since}",
        "hitsPerPage": 30,
    })
    hits = json.loads(http_get(f"https://hn.algolia.com/api/v1/search?{params}"))["hits"]
    # Algolia also matches story text and URLs; keep only title matches
    in_title = re.compile(rf"(?<!\w){re.escape(src['query'])}(?!\w)", re.IGNORECASE)
    items = []
    for hit in hits:
        if not in_title.search(hit.get("title") or ""):
            continue
        discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        url = hit.get("url") or discussion
        if not hit.get("title") or not is_web_url(url):
            continue
        items.append(make_item(
            src,
            title=hit["title"],
            url=url,
            published=parse_date(hit.get("created_at", "")),
            points=hit.get("points"),
            comments=hit.get("num_comments"),
            discussion_url=discussion,
        ))
    return items


# ---------------------------------------------------------------- Reddit

def _reddit_token() -> str:
    """App-only OAuth token. Reddit blocks anonymous requests from cloud
    servers (including GitHub Actions), so credentials are required there."""
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    secret = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (client_id and secret):
        raise RuntimeError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set")
    auth = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    body = json.loads(http_get(
        "https://www.reddit.com/api/v1/access_token",
        headers={"Authorization": f"Basic {auth}"},
        data=b"grant_type=client_credentials",
    ))
    return body["access_token"]


def fetch_reddit(src: dict) -> list[Item]:
    """Top posts in `subreddit` for `period` (day/week)."""
    params = urlencode({"t": src.get("period", "day"), "limit": 25})
    listing = json.loads(http_get(
        f"https://oauth.reddit.com/r/{src['subreddit']}/top?{params}",
        headers={"Authorization": f"Bearer {_reddit_token()}"},
    ))
    min_score = int(src.get("min_points", 0))
    items = []
    for child in listing["data"]["children"]:
        post = child["data"]
        if post.get("stickied") or post.get("score", 0) < min_score:
            continue
        discussion = f"https://www.reddit.com{post['permalink']}"
        items.append(make_item(
            src,
            title=html.unescape(post["title"]),
            url=discussion,
            published=datetime.fromtimestamp(post["created_utc"], UTC),
            summary=clean_text(post.get("selftext", "")),
            points=post.get("score"),
            comments=post.get("num_comments"),
            discussion_url=discussion,
        ))
    return items


# ---------------------------------------------------------------- registry

FETCHERS = {
    "rss": fetch_rss,
    "hn": fetch_hn,
    "reddit": fetch_reddit,
}


def validate(sources: list[dict]) -> None:
    for src in sources:
        if src.get("type") not in FETCHERS:
            raise ValueError(
                f"Source {src.get('name')!r} has type {src.get('type')!r}; "
                f"valid types: {', '.join(FETCHERS)}"
            )


def fetch_all(sources: list[dict]) -> tuple[list[Item], list[dict]]:
    """Fetch every enabled source in parallel. One failing source never stops the run."""
    enabled = [s for s in sources if s.get("enabled", True)]
    validate(enabled)

    def run(src: dict):
        try:
            return FETCHERS[src["type"]](src), None
        except Exception as exc:  # network, HTTP, parse: report and move on
            log.warning("%s failed: %s", src["name"], exc)
            return [], {"source": src["name"], "error": str(exc)[:160]}

    items, errors = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for got, err in pool.map(run, enabled):
            items.extend(got)
            if err:
                errors.append(err)
    log.info("Fetched %d items from %d sources (%d failed)", len(items), len(enabled), len(errors))
    return items, errors
