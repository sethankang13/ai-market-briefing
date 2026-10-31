# LOOP: AI Market Briefing

**LOOP** (uppercase) — descriptor **AI Market Briefing**. No slogan.

A personal daily briefing that turns public RSS into a local Markdown file and a local Streamlit reader. It is a deterministic **ETL pipeline**, **one Gemini Flash `generateContent` call per run** (not per story), and a read-only Streamlit UI. Not a chatbot, not email, not a public website.

**Architecture: v4.1 (SHIPPED).** **v4.2 is IN PROGRESS.**

## Architecture (v4.1)

| Piece | What it is |
| --- | --- |
| Brand | **LOOP: AI Market Briefing**. Daily file `# Looping... (YYYY-MM-DD)` (app title `Daily Loop: YYYY-MM-DD`). History `# The Loop: Macro Summary (Last N Days)`. |
| ETL | Collect → enrich/tag → select → market snapshot → one Gemini Flash macro → write brief → upsert `data/loop.db`. Raw JSON is immutable. Publisher HTML is not fetched on the live path. |
| Model | One Gemini Flash completion per live run (`gemini-3.8-flash` → `3.7` → `3.6` → `2.5-flash`). OpenAI `gpt-4o-mini` is the fallback. `--mock` skips models. |
| UI | Local Streamlit on `http://127.0.0.1:8501` (`Daily Loop`, `The Loop`, `?tag=` archive). Streamlit ⋮ Light / Dark / System only. Loop.app starts the UI; it does not run Gemini. |
| Schedule | LaunchAgent `com.loop.dailybriefing`: **8:00 AM every day** (7 days) and `RunAtLoad`. Wrapper `scripts/run_daily.sh` → live `python3 src/run_briefing.py`. |
| Memory | All collected RSS (selected and not) upserts into gitignored `data/loop.db` (`is_selected` marks brief picks). |
| Taxonomy | Six unhyphenated tags with integer weights (highest assigned tag owns the brief section). |

Appearance: Light is ivory `#F7F6F2` with ink `#171C25`; Dark is the inverse; System follows macOS. Palette also uses Navy `#263B60`, Slate `#64748B`, Ice `#A7C7E7`, Mist `#E5EAF0`. Type: Inter. Tag chips are muted pastels.

## Six tags (weights)

Keyword match on headline + RSS snippet. A story may receive several labels. The brief section is the highest weight.

| Tag | Weight |
| --- | --- |
| US Politics | 100 |
| Market Valuations | 80 |
| Labor & Economy | 70 |
| Geopolitics & Trade | 60 |
| Tech & Innovation | 50 |
| Venture & M&A | 40 |

Archive URLs keep the internal label (`?tag=US+Politics`). Slug for US Politics is `us-politics`.

## Twenty RSS feeds

Names and URLs live in `config/config.yaml` `feeds`. Collection writes every item into `loop.db`. A failed feed is listed in `failed_sources`; the others still save.

| Group | Sources |
| --- | --- |
| US Politics & Government | Politico Elections & Campaigns; Politico Congress & Policy; AP News Politics; Washington Post Politics; CBS News Politics |
| Markets & Wall Street | WSJ, Bloomberg & FT Markets; Reuters Business & Markets; CNBC Markets; MarketWatch Top Stories |
| Fed & Economy | CNBC Economy & Fed; Reuters Economy & Labor; Federal Reserve Press Releases |
| Geopolitics & Trade | FT & WSJ Geopolitics; Reuters Geopolitics; BBC World News |
| Tech & Innovation | TechCrunch General; Reuters Tech & Hardware; CNBC Tech & Enterprise |
| Venture & M&A | Reuters M&A & Private Equity; Axios Feed |

## How to run

From the project folder:

```bash
pip3 install -r requirements.txt
python3 src/run_briefing.py                 # live: loads gitignored .env (GEMINI_API_KEY); never print .env
python3 src/run_briefing.py --mock          # live RSS + tags + select; mock market + mock copy; no Gemini/OpenAI
python3 src/run_briefing.py --mock --force  # allow --mock to replace today's briefs/YYYY-MM-DD.md
python3 src/run_briefing.py --mock --open   # macOS `open` on the written brief
python3 src/write_the_loop.py               # historical report from data/loop.db (no new model calls)
bash scripts/start_app.sh                   # Streamlit on 127.0.0.1:8501
bash scripts/stop_app.sh
python3 -m unittest
```

`src/run_briefing.py` stops on the first failed step and names it. Live runs load `.env` without overriding variables already set in the shell. `--mock` still collects all twenty feeds. If `briefs/YYYY-MM-DD.md` already exists, `--mock` prints a warning, exits 1, and does not touch that file or `data/loop.db` unless you pass `--force`.

Install the daily job (load, not `launchctl start`):

```bash
bash scripts/install_automation.sh
```

`scripts/run_daily.sh` exits 0 when today’s brief already exists; otherwise it holds `logs/briefing.lock` and runs **live** `python3 src/run_briefing.py`. Opening Loop.app kicks that wrapper if today’s file is missing. Do not put API keys in the plist.

```bash
bash scripts/install_app_launcher.sh   # writes ~/Applications/Loop.app
```

## Pipeline

Each day is a snapshot `YYYY-MM-DD.json`. Downstream steps never rewrite earlier files.

1. **Collect** `src/collect_stories.py` → `data/raw/` — HTTP GET of the twenty YAML feeds; drop items older than 48 hours; store headline, source, link, `published_at`, native RSS snippet.
2. **Enrich** `src/enrich_stories.py` / `src/tag_stories.py` → `data/enriched/` — word-boundary keyword tags; not an LLM.
3. **Select** `src/select_stories.py` → `data/selected/` — score = tag count; prefer same calendar day; top 5 plus the best remaining story per tag that appeared that day.
4. **Market** `src/fetch_market.py` — Fed Funds + S&P 500, Nasdaq, Dow previous close. `--mock` uses a realistic offline snapshot (`4.33%`, 2026-scale indexes). Live failures say `fetch failed`.
5. **Summarize** `src/summarize_stories.py` → `data/summarized/` — **one** Gemini Flash call: `tag_notes`, `daily_summary`, `research_radar`, plus 14-day `loop.db` history. Market-impact language is interpretation.
6. **Write** `src/write_brief.py` → `briefs/YYYY-MM-DD.md` — Market Snapshot, At a Glance, one weighted-tag section per story, Daily Summary.
7. **Persist** `src/db.py` — upsert every collected RSS row into `data/loop.db`.

Per-article HTML scrape lives in `src/archived_article_summarizer.py` and is not on the live path.

## Workspace

```text
ai-market-briefing/
├── README.md
├── VERSION                 # 4.1.1
├── config/config.yaml      # feeds, taxonomy, tag_weights, models, paths
├── src/run_briefing.py     # orchestrator
├── src/app.py              # Streamlit
├── scripts/com.loop.dailybriefing.plist
├── scripts/run_daily.sh
├── data/raw|enriched|selected|summarized/
├── data/loop.db            # gitignored
└── briefs/                 # daily Markdown
```

## Roadmap (v1–v5.1)

| Version | Status | What it is |
| --- | --- | --- |
| v1 | SHIPPED | Manual run: free RSS in, small local Markdown brief out. No paid API, no GUI. |
| v2 | SHIPPED | Gemini summarization with source discipline (facts vs interpretation). |
| v2.5 | SHIPPED | Keyword taxonomy on headline + snippet; immutable raw vs enriched copy. |
| v3 | SHIPPED | `config/config.yaml`, `data/loop.db`, `write_the_loop.py` history CLI. |
| v3.5 | SHIPPED | LaunchAgent `com.loop.dailybriefing` wrapping live `run_briefing.py`. |
| v4.0 | SHIPPED | Local Streamlit: Daily Loop + The Loop; Loop.app launcher. |
| v4.0.1 | SHIPPED | `RunAtLoad`, skip-if-today’s-brief-exists, lockfile UI, honest Fed Funds. |
| v4.1 | **SHIPPED** | LOOP brand, ⋮ Light/Dark/System, Daily Loop date select, **8:00 AM every day**, full RSS in `loop.db`, one Gemini Flash per run. |
| v4.2 | **IN PROGRESS** | Six-tag weighted taxonomy, twenty RSS sources, `--mock --force` overwrite guard, Daily Loop explorer polish. |
| v5.0 | Planned | Delivery after the local habit is solid (PDF / email), still citing the sources actually used. |
| v5.1 | Planned | Entity tracking and source-grounded story clusters (one event, every supporting link, facts vs interpretation). |

## Rules

- Prefer free, public, linkable sources.
- Keep source links with every claim.
- State a **fact** only when the supplied reporting supports it; label market-impact language as **interpretation**.
- When sources disagree, preserve the disagreement.
- Do not spend money until a free option has been tested and found insufficient.
- Never print or commit `.env`.
