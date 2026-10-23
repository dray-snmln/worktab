"""Offline tests: parsing, ranking and rendering. Run: python -m unittest discover -s tests"""
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from feed import rank, render, sources  # noqa: E402
from feed.models import Item  # noqa: E402

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>Bricks 2.2 &amp; more</title><link>https://ex.com/a</link>
<pubDate>Thu, 22 Oct 2026 08:00:00 +0000</pubDate>
<description>&lt;p&gt;New &lt;b&gt;CSS&lt;/b&gt; tools&lt;/p&gt;</description></item>
<item><title>No link</title></item></channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom post</title><link rel="alternate" href="https://ex.com/b"/>
<updated>2026-10-21T10:00:00Z</updated><summary>Hello</summary></entry></feed>"""


def item(title, url, weight=0.0, days_old=0, **kw):
    return Item(title=title, url=url, source="S", group="G", source_weight=weight,
                published=NOW - timedelta(days=days_old), **kw)


class Parsing(unittest.TestCase):
    def test_rss(self):
        entry = sources.parse_feed(RSS)[0]
        self.assertEqual(entry["title"], "Bricks 2.2 & more")
        self.assertEqual(entry["summary"], "New CSS tools")
        self.assertEqual(entry["published"].day, 22)

    def test_atom(self):
        entry = sources.parse_feed(ATOM)[0]
        self.assertEqual(entry["url"], "https://ex.com/b")
        self.assertEqual(entry["published"].tzinfo, UTC)

    def test_bad_dates_are_none(self):
        self.assertIsNone(sources.parse_date("not a date"))
        self.assertIsNone(sources.parse_date(""))

    def test_unknown_source_type_is_rejected(self):
        with self.assertRaises(ValueError):
            sources.validate([{"name": "x", "type": "nope"}])


class Ranking(unittest.TestCase):
    CFG = {"keywords": {"Bricks": 6, "crypto": -10}, "ranking": {"max_age_days": 7}}

    def test_keywords_and_mutes(self):
        items = rank.rank([item("Bricks update", "https://a"), item("crypto news", "https://b")],
                          self.CFG, NOW)
        self.assertEqual([i.title for i in items], ["Bricks update"])  # crypto dropped
        self.assertEqual(items[0].matches, ["Bricks"])

    def test_whole_word_only(self):
        items = rank.rank([item("Bricksville fair", "https://a")], self.CFG, NOW)
        self.assertEqual(items[0].matches, [])

    def test_dedupe_keeps_heavier_source(self):
        a, b = item("Same story", "https://a", weight=1), item("Same  story!", "https://b", weight=5)
        self.assertEqual(rank.dedupe([a, b]), [b])

    def test_old_items_dropped(self):
        self.assertEqual(rank.rank([item("Bricks", "https://a", days_old=9)], self.CFG, NOW), [])

    def test_source_tier_wins(self):
        i = item("Quiet changelog", "https://a", source_tier="act")
        rank.assign_tiers([i], {})
        self.assertEqual(i.tier, "act")


class Rendering(unittest.TestCase):
    def test_script_breakout_is_escaped(self):
        i = item("</script><script>alert(1)</script>", "https://a")
        rank.assign_tiers([i], {})
        with tempfile.TemporaryDirectory() as tmp:
            out = render.render([i], [], NOW, False, ROOT / "template.html", Path(tmp))
            page = out.read_text(encoding="utf-8")
        self.assertNotIn("</script><script>alert", page)
        self.assertNotIn("/*__FEED_DATA__*/null", page)


if __name__ == "__main__":
    unittest.main()
