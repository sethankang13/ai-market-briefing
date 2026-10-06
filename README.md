# AI Market Briefing

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

### Selected V2.5 feeds

| Source | Feed |
| --- | --- |
| Reuters AI | [Google News search](https://news.google.com/rss/search?q=site:reuters.com+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en) |
| CNBC Tech & Markets | [Google News search](https://news.google.com/rss/search?q=site:cnbc.com+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en) |
| AP News Policy | [Google News search](https://news.google.com/rss/search?q=site:apnews.com+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en) |
| FT & WSJ Proxy | [Google News search](https://news.google.com/rss/search?q=(site:ft.com+OR+site:wsj.com)+(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en) |
| TechCrunch AI | [Category feed](https://techcrunch.com/category/artificial-intelligence/feed/) |
| VentureBeat AI | [Category feed](https://venturebeat.com/category/ai/feed/) |
| OpenAI News | [RSS](https://openai.com/news/rss.xml) |
| Google AI Blog | [RSS](https://blog.google/technology/ai/rss/) |

These are public RSS feeds, so the briefing needs no account or paid subscription. Each saved story keeps its headline, source, link, publication time, and RSS description. A Google News redirect is resolved to the publisher URL when the story is collected, and again before an article is fetched if the stored link is still a Google News URL. The raw JSON file is not edited after it is written.

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
├── src/                 # the small programs we build together
├── data/raw/            # saved incoming story data, if we choose to retain it
├── data/enriched/       # saved copies with derived tags
├── data/selected/       # saved top-story candidates and their score explanation
├── data/summarized/     # selected stories plus AI Why It Matters text
└── briefs/              # generated readable daily briefings
```

Raw inputs and generated outputs are separate so we can inspect what the program received before trusting what it produced.

## Run the full briefing

From the project folder, run `python3 src/run_briefing.py`. It collects the feeds, enriches tags, selects stories, adds Why It Matters summaries, and writes the Markdown brief, stopping at the first step that fails.

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

Each assigned tag is worth one point, and a story's score is the count of its tags. Ties retain the original feed order. The selected copy includes both the score and a short rule-based reason. The selected set is the top five by that score, plus the highest-scoring story for each tag that appears that day. One story can cover more than one tag, a missing tag is skipped, and the list can be longer than five. An untagged story still cannot take a top-five slot from a tagged story, and the whole set keeps at most one untagged story.

## Current summarization step (V2)

Create AI "Why It Matters" copy from the latest selected run with:

```bash
python3 src/summarize_stories.py
```

The program reads `data/selected/YYYY-MM-DD.json` and writes `data/summarized/YYYY-MM-DD.json`, creating `data/summarized/` if it does not exist. For each story it fetches `link` with the standard library, extracts readable article text, and sends a capped excerpt to the model. If the fetch or extract fails, the model sees only the headline, source, tags, and selection reason, and the story records `article_read: false` with `Article was not read.` Gemini `gemini-3.6-flash` is used when `GEMINI_API_KEY` is set. A plain `python3 src/run_briefing.py` or `python3 src/summarize_stories.py` loads a gitignored `.env` in the project root first, and does not replace a value already set in the shell. It returns `ai_headline` (a short line that states why the story matters) and `ai_summary` (one or two sentences) from the article text. Market-impact language is labeled as interpretation. OpenAI `gpt-4o-mini` is the fallback. With no usable key, the story stores `[AI Headline Pending: <Headline>]` and `[AI Summary Pending: <Headline>]`. Selected files are left unchanged.

## Current writing step

Create a readable Markdown briefing from the latest summarized run (or selected run, if summaries are missing) with:

```bash
python3 src/write_brief.py
```

The briefing groups stories by the V2.5 tag labels, then Other. Stories with more than one tag appear once, under the first matching label in that order, while displaying every assigned tag. When `ai_headline` is present, that line leads, followed by the original headline and link, then an italic line such as `*Tags: #Legislation-&-Policy #Enterprise-Adoption*`, then **Why It Matters:** from `ai_summary`. Stories without `ai_headline` keep the original headline as the first line.

## Rules for this project

- Prefer free, public, linkable sources in V1.
- Keep source links with every claim.
- Separate facts from our interpretation of market impact.
- Add automation only after the manual version is useful.
- Do not spend money until a free option has been tested and found insufficient.
