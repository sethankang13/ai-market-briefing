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

### Selected V1 feeds

| Category | Feed | Why it is in V1 |
| --- | --- | --- |
| General news | [BBC World](https://feeds.bbci.co.uk/news/world/rss.xml) | Broad international and geopolitical coverage |
| Finance | [BBC Business](https://feeds.bbci.co.uk/news/business/rss.xml) | Accessible business, company, and market-adjacent reporting |
| Economics | [NPR Economy](https://feeds.npr.org/1017/rss.xml) | Economic context and cost-of-living coverage |

These are public RSS feeds, so V1 needs no account, paid subscription, or API key. The Federal Reserve's official press-release feed is a future primary-source supplement, not one of the three general daily feeds.

### Availability behavior

If a feed is unavailable, continue with the other feeds. The eventual email will cite the sources actually used rather than interrupt the reader with an error. A local run record will keep track of source failures for debugging.

### Raw data and preview behavior

- Save every collected story, even when it later turns out to be duplicated or low priority.
- Show a short preview rather than the whole raw collection.
- In V1, use repeated independent coverage as a possible importance signal. RSS feeds do not reliably provide article view counts, so popularity is a future enhancement rather than a V1 rule.
- Keep source records unchanged and create a separate enriched collection for derived tags. This preserves the evidence while allowing tagging rules to improve over time.
- Tag stories that match none of the initial topic rules as `misc`. The reader still sees only selected stories, not the full raw collection.
- Reserve at most one email slot for a `misc` story. In V1, it is a candidate for a conversationally interesting item; RSS does not provide a reliable virality measure, so popularity scoring is a future enhancement.

### Initial tag rules

- `oil`: “oil” or “crude” appears in the headline. Oil stories also receive the broader `energy` tag.
- `energy`: “energy,” “solar,” or “nuclear” appears in the headline.
- `technology`: a relevant technology term appears; energy technologies may receive both `energy` and `technology`.
- `policy`: central-bank/rate decisions, inflation, tariffs and trade restrictions, tax-policy phrases (for example, “new taxes” or “tax cuts”), sanctions, government spending, or budgets appear in the headline. A generic reference to tax, such as “tax exile,” does not qualify.
- `misc`: no initial topic rule matched. This preserves an avenue for a worthwhile but otherwise uncategorized story.

Tags are lists, so a story can belong to more than one topic and can later be queried by one tag or a combination.

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
├── README.md       # roadmap and decisions
├── src/            # the small programs we build together
├── data/raw/       # saved incoming story data, if we choose to retain it
├── data/enriched/  # saved copies with derived topic tags
├── data/selected/  # saved top-story candidates and their score explanation
└── briefs/         # generated readable daily briefings
```

Raw inputs and generated outputs are separate so we can inspect what the program received before trusting what it produced.

## Current enrichment step

After collecting a run, create its tagged copy with:

```bash
python3 src/enrich_stories.py
```

The program chooses the latest file in `data/raw/`, adds a `topics` list to each story, and saves the result under `data/enriched/` with the same date-based filename. It never changes the raw run. To re-enrich a specific historical run, pass its path, for example `python3 src/enrich_stories.py data/raw/2026-09-20.json`.

## Current selection step

Create up to five briefing candidates from the latest enriched run with:

```bash
python3 src/select_stories.py
```

The initial ranking is deliberately simple and visible: `oil` is worth 5 points, `policy` 4, `energy` 3, and `technology` 2. A story's score is the sum of its tags, and ties retain the original feed order. The selected copy includes both the score and a short rule-based reason. A `misc` story can fill one otherwise unused slot, but cannot displace a tagged story.

## Current writing step

Create a readable Markdown briefing from the latest selected run with:

```bash
python3 src/write_brief.py
```

The briefing groups stories into Policy & economics, Energy, Technology, and Interesting aside. Stories with more than one tag appear once, under their most decision-relevant section, while displaying all their tags. V1 includes only source-supported metadata and a link to the original report; analysis comes later when we have source text to support it.

## Rules for this project

- Prefer free, public, linkable sources in V1.
- Keep source links with every claim.
- Separate facts from our interpretation of market impact.
- Add automation only after the manual version is useful.
- Do not spend money until a free option has been tested and found insufficient.
