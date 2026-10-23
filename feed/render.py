"""Write the static page: template.html with the feed data inlined as JSON."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import Item

PLACEHOLDER = "/*__FEED_DATA__*/null"


def render(items: list[Item], errors: list[dict], built_at: datetime,
           ai_used: bool, template: Path, out_dir: Path) -> Path:
    page = template.read_text(encoding="utf-8")
    if PLACEHOLDER not in page:
        raise ValueError(f"{template} is missing the {PLACEHOLDER} placeholder")
    payload = {
        "builtAt": built_at.isoformat(),
        "aiUsed": ai_used,
        "items": [i.to_public() for i in items],
        "errors": errors,
    }
    # "</" escaped so feed text can never close the <script> tag
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(page.replace(PLACEHOLDER, data), encoding="utf-8")
    return out
