# Worktab

A daily work feed for your browser's new tab: Bricks, WordPress, web, design,
SEO and AI news, ranked by your own keyword rules. Runs on GitHub Actions twice
a day and publishes to GitHub Pages. AI is optional.

## Setup (once, about 10 minutes)

1. Create a new **public** repo on github.com (free Pages needs public).
2. On the empty repo page, click **uploading an existing file**, drag in
   everything from this folder (including `.github`), and commit.
3. **Settings → Pages → Source: GitHub Actions.**
4. **Actions → Build feed → Run workflow.** When it finishes, the page URL
   shows on the run. Set it as your browser's homepage / new tab.

## Everyday use

- **Tune it:** edit `config.toml` on github.com. Saving triggers a rebuild.
  - `[keywords]`: raise what you care about, use negatives to bury noise.
  - `[[sources]]`: add an RSS feed in 5 lines; `enabled = false` turns one off.
  - `[ranking]`: thresholds for "Act on this" and "Worth reading".
- **Save / Hide** on the page are stored in your browser only.
- The footer shows when it last updated and any source that failed.

## Optional extras (repo secrets: Settings → Secrets and variables → Actions)

| Secret | Turns on |
|---|---|
| `ANTHROPIC_API_KEY` | AI re-scoring of the top 40 items plus a one-line reason. One small call per run. |
| `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` | Reddit sources (Reddit blocks anonymous requests from GitHub). Create a "script" app at reddit.com/prefs/apps, then set the Reddit sources to `enabled = true`. |

If a key is missing or a call fails, the page still builds without that part.

## How it works

```
build.py            entry point: fetch → rank → optional AI → tiers → page
feed/sources.py     fetchers: rss, hn, reddit (registry: FETCHERS)
feed/rank.py        rule scoring, dedupe, tiers
feed/ai.py          optional re-scoring (registry: PROVIDERS)
feed/render.py      inlines the data into template.html → site/index.html
template.html       the page: layout, styles, save/hide/filter in plain JS
tests/              offline tests, run before every build
```

Python 3.11+ standard library only, no dependencies.

## Extending

- **New source type:** add `fetch_<type>(src) -> list[Item]` in
  `feed/sources.py` and register it in `FETCHERS`. Config keys are up to you.
- **New AI provider:** add `call_<name>(prompt, model, api_key) -> str` in
  `feed/ai.py`, register it in `PROVIDERS` with its key's env var, and set
  `[ai].provider` in config.
- **Page changes:** `template.html` only. Data arrives as `DATA.items`
  (see `Item.to_public()` in `feed/models.py`).

Run locally: `python build.py` then open `site/index.html`.
Run tests: `python -m unittest discover -s tests`.
