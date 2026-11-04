import base64
import sys
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.request import Request


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import collect_stories


def google_article_link(publisher_url: str) -> str:
    token = base64.urlsafe_b64encode(publisher_url.encode("utf-8")).decode("ascii").rstrip("=")
    return f"https://news.google.com/rss/articles/{token}"


class CollectStoriesTests(unittest.TestCase):
    def test_sources_are_the_twenty_feeds(self):
        self.assertEqual(len(collect_stories.SOURCES), 20)
        self.assertEqual(len(collect_stories.FEED_ENTRIES), 20)
        self.assertEqual(
            list(collect_stories.SOURCES),
            [
                "Politico / Elections & Campaigns",
                "Politico / Congress & Policy",
                "AP News / Politics",
                "Washington Post / Politics",
                "CBS News / Politics",
                "WSJ, Bloomberg & FT / Markets",
                "WSJ, Bloomberg & FT / Geopolitics",
                "Reuters / Business & Markets",
                "Reuters / Economy & Labor",
                "Reuters / Geopolitics",
                "Reuters / Tech & Hardware",
                "Reuters / M&A & Private Equity",
                "CNBC / Markets",
                "CNBC / Economy & Fed",
                "CNBC / Tech & Enterprise",
                "MarketWatch / Top Stories",
                "Federal Reserve / Press Releases",
                "BBC / World News",
                "TechCrunch / General",
                "Axios / Feed",
            ],
        )
        self.assertEqual(
            collect_stories.SOURCES["CBS News / Politics"],
            "https://www.cbsnews.com/latest/rss/main",
        )
        self.assertEqual(
            collect_stories.SOURCES["TechCrunch / General"],
            "https://techcrunch.com/feed/",
        )
        self.assertEqual(
            collect_stories.SOURCES["Axios / Feed"],
            "https://www.axios.com/feeds/feed.rss",
        )
        self.assertIn(
            "site:politico.com",
            collect_stories.SOURCES["Politico / Elections & Campaigns"],
        )

    def test_google_news_token_resolves_without_a_second_request(self):
        publisher = "https://www.reuters.com/technology/ai-story"
        link = google_article_link(publisher)
        with patch.object(collect_stories, "urlopen") as urlopen:
            resolved = collect_stories.resolve_publisher_url(link)
        self.assertEqual(resolved, publisher)
        urlopen.assert_not_called()

    def test_google_news_redirect_uses_the_final_url_when_the_token_has_none(self):
        class Response:
            def geturl(self):
                return "https://www.cnbc.com/2026/10/05/ai-markets.html"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(collect_stories, "urlopen", return_value=Response()) as urlopen:
            resolved = collect_stories.resolve_publisher_url(
                "https://news.google.com/rss/articles/not-a-url"
            )
        self.assertEqual(resolved, "https://www.cnbc.com/2026/10/05/ai-markets.html")
        sent = urlopen.call_args.args[0]
        self.assertIsInstance(sent, Request)

    def test_fetch_feed_stores_description_and_publisher_link(self):
        publisher = "https://www.reuters.com/technology/ai-story"
        rss = f"""<?xml version="1.0"?>
        <rss><channel><item>
          <title>AI earnings beat</title>
          <link>{google_article_link(publisher)}</link>
          <pubDate>Mon, 05 Oct 2026 12:00:00 GMT</pubDate>
          <description>&lt;p&gt;Stock valuation rose.&lt;/p&gt;</description>
          <content:encoded xmlns:content="http://purl.org/rss/1.0/modules/content/">&lt;p&gt;Full earnings body with valuation details for the model.&lt;/p&gt;</content:encoded>
        </item></channel></rss>
        """.encode("utf-8")

        class Response:
            def read(self):
                return rss

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        now = datetime(2026, 10, 5, 13, 0, tzinfo=timezone.utc)
        with patch.object(collect_stories, "feedparser_module", None):
            with patch.object(collect_stories, "urlopen", return_value=Response()):
                stories = collect_stories.fetch_feed(
                    {"source": "Reuters AI", "url": "https://news.google.com/rss/search?q=ai"},
                    now=now,
                )

        self.assertEqual(stories[0]["headline"], "AI earnings beat")
        self.assertEqual(stories[0]["description"], "Stock valuation rose.")
        self.assertNotIn("full_text", stories[0])
        self.assertNotIn(
            "Full earnings body with valuation details for the model.",
            stories[0]["description"],
        )
        self.assertEqual(stories[0]["link"], publisher)
        self.assertEqual(stories[0]["source"], "Reuters AI")
        self.assertEqual(stories[0]["sub_feed"], "Reuters AI")

    def test_fetch_feed_drops_items_older_than_48_hours(self):
        rss = b"""<?xml version="1.0"?>
        <rss><channel>
          <item>
            <title>Fresh story</title>
            <link>https://example.com/fresh</link>
            <pubDate>Tue, 06 Oct 2026 10:00:00 GMT</pubDate>
            <description>New</description>
          </item>
          <item>
            <title>Stale story</title>
            <link>https://example.com/stale</link>
            <pubDate>Sun, 04 Oct 2026 09:00:00 GMT</pubDate>
            <description>Old</description>
          </item>
        </channel></rss>
        """

        class Response:
            def read(self):
                return rss

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        with patch.object(collect_stories, "feedparser_module", None):
            with patch.object(collect_stories, "urlopen", return_value=Response()):
                stories = collect_stories.fetch_feed(
                    {"source": "Reuters AI", "url": "https://example.com/rss"},
                    now=now,
                )

        headlines = [story["headline"] for story in stories]
        self.assertEqual(headlines, ["Fresh story"])

    def test_published_parsed_tuple_is_used_for_recency(self):
        now = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
        fresh = collect_stories.story_published_at(
            "ignored", published_parsed=(2026, 10, 5, 12, 0, 0, 0, 0, 0)
        )
        stale = collect_stories.story_published_at(
            "ignored", updated_parsed=(2026, 10, 3, 12, 0, 0, 0, 0, 0)
        )
        self.assertTrue(collect_stories.is_recent(fresh, now))
        self.assertFalse(collect_stories.is_recent(stale, now))

    def test_collector_does_not_fetch_article_html(self):
        source = Path(collect_stories.__file__).read_text(encoding="utf-8")
        self.assertNotIn("trafilatura", source)
        self.assertNotIn("archived_article_summarizer", source)
        self.assertNotIn("item_full_text", source)
        self.assertIn("RSS description/snippet only", collect_stories.__doc__)


if __name__ == "__main__":
    unittest.main()
