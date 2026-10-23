# Loop: AI Market Briefing

**Active version: v4.0: Local web UI (Phase 1).** A Streamlit app reads existing daily briefs and `data/loop.db` in the browser. It does not call Gemini or OpenAI. Weekday LaunchAgent automation from v3.5 is unchanged. Live pipeline runs still need a gitignored `.env` in the project root.

## Purpose

Build a personal, daily briefing that turns reliable public news into a short explanation of the market, economic, and policy developments that matter.

This is a learning project. We will make one small decision, build one small piece, and test it before adding the next capability.

## V1: the smallest useful version

Start with a script you run yourself that:

1. Reads headlines from one free public news source.
2. Selects a small set of finance/economy/policy stories.
3. Produces a readable briefing with links.

No paid news API, database, website, or automated email yet.

## Learning roadmap

| Milestone | What we build | What it teaches |
| --- | --- | --- |
| 0. Define the brief | Audience, scope, source, and success criteria | Product thinking and trade-offs |
| 1. Collect | Get headlines from one free RSS feed | HTTP, structured data, and parsing |
| 2. Filter | Keep stories relevant to the brief | Lists, functions, and simple rules |
| 3. Write | Render a clean local daily brief | Strings, templates, and files |
| 4. Improve | Add a second source and remove duplicates | Data quality and testing assumptions |
| 5. Explain | Add concise “why it matters” analysis | Prompt design and source discipline |
| 6. Automate | Run daily and deliver the result | Scheduling, secrets, and reliability |

## Decisions log

| Date | Decision | Why |
| --- | --- | --- |
| 2026-10-21 | Keep the RSS/original `headline` as the only story title; Gemini writes `ai_summary` only | Headline rewriting spent tokens without improving the brief. |
| 2026-10-21 | Use eight public feeds, including Bloomberg, Reuters markets, Politico, and a narrower AP policy search | Broader AI market and policy coverage from still-free RSS. |
| 2026-10-21 | Rebrand to Loop: AI Market Briefing; daily files use `# Looping... (YYYY-MM-DD)`; historical reports use `# The Loop` | One product name for the daily habit and a separate title for the archive. |
| 2026-10-21 | Put a Market Snapshot (Fed Funds, S&P 500, Nasdaq, Dow) above story sections; failed quotes say fetch failed | The brief should open with observable market context, never invented numbers. |
| 2026-10-23 | Group the daily brief by taxonomy tag with one Gemini pattern note per tag, then a Daily Summary; colored `#Tag-Name` links open a local Streamlit tag archive | Kill per-story Why It Matters and tag lines under headlines; keep one Gemini call per run. |
| 2026-10-23 | Infer the daily macro report from RSS headlines and snippets plus 14 days of `loop.db`; archive per-article HTML extraction | Publisher pages 403 / paywall; headlines plus stored context are enough for clusters, drift, and a research radar. |
| 2026-10-21 | Drop RSS items older than 48 hours; summarize from full article body; Gemini cascade; append each run to gitignored `data/loop.db` | Recency, body-grounded copy, and a durable history without storing secrets. |
| 2026-09-19 | Begin with a manually run, free V1 | It keeps costs and moving parts near zero while making every step observable. |
| 2026-09-19 | Rank stories by immediate market impact, long-term outlook, economic policy, global relations/cost of living, and conversation relevance; include an occasional fun or interesting story | The brief should be useful for investing and economic understanding, but engaging enough to become a daily habit. |
| 2026-09-19 | Keep the V1 story record to headline, source, link, and publication time | A small, observable data shape makes collection easy to understand and debug. |
| 2026-09-19 | Start V1 with three free public feeds: one general-news, one finance-focused, and one policy/economics-focused | This gives broad coverage and makes duplication a real, learnable data-quality problem. |

## Story-selection standard (draft)

A story is a candidate for the daily top five when it has one or more of these qualities:

1. It has immediate potential to move markets.
2. It changes the long-term economic or business outlook.
3. It matters for economic policy.
4. It affects global relations or the cost of living.
5. It is highly visible in public conversation.

The final brief can also contain one clearly labeled **Interesting aside** when there is a genuinely fun or surprising story. It is not allowed to displace a more consequential story from the top five.

### Current priority order

When space is limited, select in this order:

1. Direct market and economic-policy significance (for example, interest-rate guidance).
2. Geopolitical developments with plausible effects on energy, trade, inflation, or the cost of living.
3. Technology or culture stories that are notable enough to help with informed conversation.
4. Celebrity-driven virality only when it crosses into a real business, market, or policy consequence.

## Later ideas (not V1)

- **Entity tracking:** identify and count recurring people, companies, institutions, and countries, then make them searchable for follow-up research.
- **AI-supported story clusters:** combine coverage of one event into a single summary, retain every supporting source link, and distinguish directly reported facts from market-impact interpretation.

## V1 source plan

Use one free public RSS feed from each category:

| Category | Job in the briefing |
| --- | --- |
| General news | Catch major world, political, and geopolitical developments |
| Finance | Catch market and company developments |
| Policy/economics | Catch central-bank, fiscal, trade, and macroeconomic developments |

We will choose the specific feeds after deciding how V1 should handle the same event appearing across multiple sources.

### Selected feeds

| Source | Feed |
| --- | --- |
| FT, WSJ & Bloomberg Proxy | [Google News search](https://news.google.com/rss/search?q=(site:ft.com+OR+site:wsj.com+OR+site:bloomberg.com)+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en) |
| Reuters Business & Markets | [Google News search](https://news.google.com/rss/search?q=site:reuters.com+(AI+OR+%22artificial+intelligence%22)+market&hl=en-US&gl=US&ceid=US:en) |
| CNBC Tech & Markets | [Google News search](https://news.google.com/rss/search?q=site:cnbc.com+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en) |
| Politico AI Policy | [Google News search](https://news.google.com/rss/search?q=site:politico.com+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en) |
| AP News Policy | [Google News search](https://news.google.com/rss/search?q=site:apnews.com+(AI+OR+%22artificial+intelligence%22)+(policy+OR+government+OR+law)&hl=en-US&gl=US&ceid=US:en) |
| TechCrunch AI | [Category feed](https://techcrunch.com/category/artificial-intelligence/feed/) |
| OpenAI News | [RSS](https://openai.com/news/rss.xml) |
| Google AI Blog | [RSS](https://blog.google/technology/ai/rss/) |

These are public RSS feeds, so the briefing needs no account or paid subscription. Each saved story keeps its headline, source, link, publication time, and native RSS description/snippet. A Google News redirect is resolved to the publisher URL when the story is collected. The live pipeline does not fetch publisher article HTML. The raw JSON file is not edited after it is written.

### Availability behavior

If a feed is unavailable, continue with the other feeds. The eventual email will cite the sources actually used rather than interrupt the reader with an error. A local run record will keep track of source failures for debugging.

### Raw data and preview behavior

- Save every collected story, even when it later turns out to be duplicated or low priority.
- Show a short preview rather than the whole raw collection.
- In V1, use repeated independent coverage as a possible importance signal. RSS feeds do not reliably provide article view counts, so popularity is a future enhancement rather than a V1 rule.
- Keep source records unchanged and create a separate enriched collection for derived tags. This preserves the evidence while allowing tagging rules to improve over time.
- Leave `tags` as an empty list when no keyword matches. The reader still sees only selected stories, not the full raw collection.
- An untagged story cannot take a top-five slot from a tagged story, and the selected set keeps at most one untagged story.

### V2.5 tag rules

Keyword matching looks at the headline and the RSS description. A story can receive several of these labels:

- `Market-Valuations`: earnings, stock, market cap, valuation
- `Venture-&-M&A`: funding, venture, acquisition, seed, valuation
- `Legislation-&-Policy`: bill, law, government, executive order, policy
- `Antitrust-&-Compliance`: FTC, regulation, EU AI Act, probe, investigation
- `Copyright-&-IP`: copyright, lawsuit, licensing, data scraping, IP
- `Geopolitics-&-Trade`: export controls, chips, sanctions, China, national security
- `Labor-&-Economy`: jobs, workforce, productivity, economy, lay-offs
- `Enterprise-Adoption`: enterprise, ROI, corporate, B2B, SaaS
- `Foundation-Models`: LLM, GPT, Claude, Gemini, weights, benchmark

Tags are a list of those strings. A word such as “valuation” can match more than one label. When nothing matches, the list is empty.

### Tag-history decision

- A newly introduced tag may start tracking from its introduction date onward.
- When redefining an existing tag's meaning, rebuild the enriched archive from the unchanged raw records so the new definition applies to prior stories too.
- The tag configuration will eventually record each rule's effective date and whether it should be applied retroactively.

## Future citation rule

For a cluster of reports about the same event, an AI-generated summary may use only claims supported by the supplied source material. The briefing will keep links to all sources that support the cluster. AI helps organize, compare, and explain; it does not replace the underlying reporting.

## Fact and interpretation rule

- State a claim as a **fact** only when the supplied reporting supports it.
- Label a market-impact or causal explanation as an **interpretation** unless the evidence directly establishes it.
- When sources materially disagree, preserve the disagreement rather than pretending there is certainty.

## Workspace

```text
ai-market-briefing/
├── README.md            # roadmap and decisions
├── config/config.yaml   # feeds, recency, models, taxonomy, output paths
├── src/                 # the small programs we build together
├── src/app.py           # Phase 1 Streamlit UI (briefs + Loop explorer)
├── scripts/             # launchd, Streamlit start/stop, Loop.app installer
├── logs/                # gitignored launchd and pipeline logs
├── data/raw/            # saved incoming story data, if we choose to retain it
├── data/enriched/       # saved copies with derived tags
├── data/selected/       # saved top-story candidates and their score explanation
├── data/summarized/     # selected stories plus the run-level macro report
├── data/loop.db         # gitignored SQLite history for The Loop
└── briefs/              # generated readable daily briefings
```

Raw inputs and generated outputs are separate so we can inspect what the program received before trusting what it produced.

## v4.0: Local web UI (Phase 1)

Browse generated briefs and stored Loop history without running the pipeline or calling a model.

```bash
pip3 install -r requirements.txt
bash scripts/start_app.sh
```

Stop it with `bash scripts/stop_app.sh`. Install a double-clickable macOS app with `bash scripts/install_app_launcher.sh`, then open `~/Applications/Loop.app` (drag that to the Dock or Desktop if you want). `osacompile` writes an applet whose `Contents/MacOS` executable runs `scripts/start_app.sh`. `start_app.sh` puts Homebrew on `PATH` so Finder/`osascript` can find `streamlit`, uses `lsof` on port 8501 to avoid a second copy, `nohup`s Streamlit, writes `logs/streamlit.pid`, and opens http://localhost:8501. You can still run `streamlit run src/app.py` from the project folder. Re-run the installer only if the start script path changes.

The app resolves the project root from `src/app.py`, so `config/`, `briefs/`, and `data/` are found even when Streamlit's working directory is `src/`. The sidebar shows stored article count (`data/loop.db`, or zero if the file is missing), the newest `briefs/YYYY-MM-DD.md` date, and the active feed count from `config/config.yaml`. Headlines are Markdown links to the RSS story (`target=_blank` in the explorer). Clustered coverage uses a `🔗 Sources (N)` popover. The UI never prints a raw URL as standalone text.

| Tab | What it shows |
| --- | --- |
| Daily Briefings | Date selector (newest first) and the Markdown file. At a Glance and story titles are hyperlinked RSS headlines; `also covered by` stays exact-headline. Color-coded `#Tag-Name` headings link to the local tag archive. |
| The Loop Explorer | SQLite filters: taxonomy tag, source, and headline/summary search. Results are expander cards with a linked headline, the same colored clickable hashtag chips, and a sources popover when more than one publisher used the same headline. |
| Tag archive (`?tag=`) | All `loop.db` rows whose stored tags contain that label (`tags LIKE ?`), grouped by date, newest first. Example: `http://127.0.0.1:8501/?tag=Legislation-%26-Policy`. Local Streamlit only; not a public website. |

Phase 1 only: no generate-brief button, no new Gemini calls, no writes to the database from the UI.

## v3.5: Local Automation & Passive Ingestion

A user LaunchAgent runs `python3 src/run_briefing.py` at **8:00 AM Monday–Friday**. There are no new LLM calls; the job is the same live pipeline as a manual run. The Mac must be on (and logged in) at 8:00 AM on weekdays, or that day's interval is skipped. A gitignored `.env` with `GEMINI_API_KEY` (and any OpenAI fallback) must exist in the project root for live runs. Do not put API keys in the plist or shell scripts.

Install (or reinstall) the job:

```bash
bash scripts/install_automation.sh
```

The installer `chmod +x`s `scripts/run_daily.sh`, copies `scripts/com.loop.dailybriefing.plist` to `~/Library/LaunchAgents/com.loop.dailybriefing.plist`, unloads any previous copy, and loads the job. It does not start a briefing.

| Path | Role |
| --- | --- |
| `logs/launchd.log` | Combined stdout/stderr from `run_briefing.py` (`>>` / `2>&1` in `run_daily.sh`) |
| `logs/launchd_stdout.log` | launchd `StandardOutPath` for the bash wrapper |
| `logs/launchd_stderr.log` | launchd `StandardErrorPath` for the bash wrapper |

Run once without waiting for 8 AM:

```bash
launchctl start com.loop.dailybriefing
```

That starts a **live** briefing (Gemini if `.env` is present). Use `python3 src/run_briefing.py --mock` when you want an offline pipeline instead.

## Run the full briefing

From the project folder, run `python3 src/run_briefing.py`. It collects feeds from the last 48 hours, enriches tags, selects stories, fetches a Market Snapshot, writes one run-level Gemini payload (per-tag pattern notes, daily summary, research radar), writes `# Looping... (YYYY-MM-DD)`, and appends the selected stories plus that copy to `data/loop.db`. It stops at the first step that fails. Add `--open` to open `briefs/YYYY-MM-DD.md` when the run finishes (`open` on macOS; other platforms print the path and do not launch a viewer). Every run, mock or live, prints a completion banner with the output path, story count, Market Snapshot status, and `failed_sources` when a feed was skipped.

For a briefing that does not call a model, run `python3 src/run_briefing.py --mock`. It still collects the RSS feeds, enriches tags, selects stories, and fetches market quotes. Per-tag notes and the daily summary are offline mock copy, even when `.env` contains an API key, and it never talks to Gemini. Live runs never write `AI Summary Pending`, `AI Headline Pending`, or `AI Summary goes HERE`. A feed that fails is skipped, and the brief is written from the feeds that succeeded. Failed market quotes are labeled `fetch failed`. Combine flags as needed, for example `python3 src/run_briefing.py --mock --open`.

## Current enrichment step

After collecting a run, create its tagged copy with:

```bash
python3 src/enrich_stories.py
```

The program chooses the latest file in `data/raw/`, adds a `tags` list to each story from the headline and description, and saves the result under `data/enriched/` with the same date-based filename. It never changes the raw run. To re-enrich a specific historical run, pass its path, for example `python3 src/enrich_stories.py data/raw/2026-09-20.json`.

## Current selection step

Create up to five briefing candidates from the latest enriched run with:

```bash
python3 src/select_stories.py
```

Each assigned tag is worth one point, and a story's score is the count of its tags. Ties retain the original feed order. The selected copy includes both the score and a short rule-based reason. The selected set is the top five by that score, plus the highest-scoring story for each of the nine Loop tags that appears that day. One story can cover more than one tag, a missing tag is skipped, and the list can be longer than five. An untagged story still cannot take a top-five slot from a tagged story, and the whole set keeps at most one untagged story. The step prints how many stories were evaluated, tag density across the nine labels, and a recency score.

## Current summarization step (headline-based macro inference)

Create one run-level macro report from the latest selected run with:

```bash
python3 src/summarize_stories.py
```

The program reads `data/selected/YYYY-MM-DD.json` and the last 14 days of stored briefing records from `data/loop.db` (`WHERE published_date >= date('now', '-14 days')`). It writes `data/summarized/YYYY-MM-DD.json`, creating `data/summarized/` if it does not exist. Input is RSS headlines plus native snippets, grouped by taxonomy tag, not fetched article bodies. There is **one** Gemini Flash completion per run. When `GEMINI_API_KEY` is set, models are tried in order: `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`, then `gemini-2.5-flash`. HTTP 429 and connection errors move to the next model; that is still one successful completion, not one call per story. The model returns JSON (or clearly delimited sections) with `tag_notes` (one paragraph per tag that has a selected story today), `daily_summary`, and `research_radar` (3–5 follow-up topics). A plain `python3 src/run_briefing.py` or `python3 src/summarize_stories.py` loads a gitignored `.env` in the project root first, and does not replace a value already set in the shell. Market-impact language is labeled as interpretation. OpenAI `gpt-4o-mini` is the fallback after the Gemini cascade. If every live attempt fails, the step raises instead of writing pending placeholders. `--mock` writes deterministic per-tag notes and a daily summary and does not use the network. Selected files are left unchanged. The pipeline never writes `AI Summary Pending`, `AI Headline Pending`, or a per-story Why It Matters line.

Per-article HTML extraction (trafilatura / BeautifulSoup) and per-story Gemini summaries live in `src/archived_article_summarizer.py`. That module is reserved for a future paywall or subscription-authenticated scrape. The live pipeline does not import or call it.

## Current writing step

Create a readable Markdown briefing from the latest summarized run (or selected run, if summaries are missing) with:

```bash
python3 src/write_brief.py
```

The briefing title is `# Looping... (YYYY-MM-DD)`. A Market Snapshot (Fed Funds, S&P 500, Nasdaq, Dow previous close and percent change) sits above **At a Glance**, a list of RSS headlines linked to the original story URL. The RSS headline is the only title; Gemini does not write an AI headline.

Stories are then grouped under every V2.5 tag that has at least one selected story that day, in config order. Each tag heading is a color-coded, clickable `#Tag-Name` that opens the local Streamlit tag archive at `http://127.0.0.1:8501/?tag=...` (for example `?tag=Legislation-%26-Policy`). Under the heading: RSS headline links, plus `also covered by [Source B]` for exact-headline duplicates. After those links, one **Why it might matter / pattern** paragraph for the tag (today’s headlines in that tag plus 14-day `loop.db` history). There is no italic tags line and no per-story Why It Matters. A story with several tags appears under each of them.

**Daily Summary** follows the tag sections: what happened today across all headlines, what it could mean, then research topics to look into more. Historical reports from `data/loop.db` are titled `# The Loop: Macro Summary (Last N Days)`.

## Config (`config/config.yaml`)

Shared settings live in YAML and are loaded with `src/config_loader.py` (`yaml.safe_load`). Collect, tag, select, summarize, write, and SQLite history all read this file. If the file is missing, the loader returns the same internal defaults so mocked unit tests still run.

| Key | What it controls |
| --- | --- |
| `pipeline.recency_cutoff_hours` | Drop RSS items older than this many hours (48). |
| `pipeline.top_selected_stories` | Top tagged slots in selection (5). |
| `pipeline.output_dir` | Daily briefs and `THE_LOOP.md` (default `briefs`). |
| `pipeline.db_path` | SQLite history file (default `data/loop.db`). |
| `feeds` | The eight public RSS names and URLs. |
| `models.gemini` | Cascade order (`gemini-3.8-flash` down through `gemini-2.5-flash`). |
| `models.openai_fallback` | OpenAI model after Gemini (`gpt-4o-mini`). |
| `taxonomy` | The nine Loop tags and their keyword lists. |

Changing a feed, tag keyword, cutoff, or model name here is enough; the Python modules do not keep a second copy of those values as the source of truth.

## Historical Loop (`src/write_the_loop.py`)

Write a windowed archive from `data/loop.db` (no new model calls):

```bash
python3 src/write_the_loop.py
python3 src/write_the_loop.py --days 14 --tag Copyright-&-IP --limit 15
python3 src/write_the_loop.py --out briefs/THE_LOOP.md --open
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--days N` | 7 | `WHERE published_date >= date('now', '-N days')` (N is a bound parameter). |
| `--tag TAG` | none | Keep rows whose stored tags contain this label. |
| `--limit N` | 15 | Maximum stories. |
| `--out FILEPATH` | `briefs/THE_LOOP.md` | Markdown output path. |
| `--open` | off | macOS `open` via `subprocess.run`; other platforms print the path. |

The report opens with **At a Glance**, then market-snapshot *trends from stored runs* (or an explicit note that those numbers are missing), then the same topic groups / exact-headline / `also covered by` rules as the daily brief.

## Rules for this project

- Prefer free, public, linkable sources in V1.
- Keep source links with every claim.
- Separate facts from our interpretation of market impact.
- Add automation only after the manual version is useful.
- Do not spend money until a free option has been tested and found insufficient.
