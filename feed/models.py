"""The one data shape every part of the pipeline passes around."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class Item:
    title: str
    url: str
    source: str                      # display name from config, e.g. "Bricks releases"
    group: str                       # filter group from config, e.g. "WordPress"
    published: datetime | None = None
    summary: str = ""
    points: int | None = None        # HN points / Reddit score, when the source has them
    comments: int | None = None
    discussion_url: str = ""
    source_weight: float = 0.0
    source_tier: str = ""            # forces a tier, e.g. "act" for changelogs
    # Filled in by rank.py / ai.py
    score: float = 0.0
    tier: str = ""
    matches: list[str] = field(default_factory=list)
    why: str = ""                    # one-line AI note, empty when AI is off

    @property
    def id(self) -> str:
        return hashlib.sha1(self.url.encode()).hexdigest()[:12]

    def to_public(self) -> dict:
        """Fields the page needs; internal ranking inputs stay out."""
        data = asdict(self)
        for key in ("source_weight", "source_tier"):
            data.pop(key)
        data["id"] = self.id
        data["published"] = self.published.isoformat() if self.published else None
        data["score"] = round(self.score, 1)
        return data
