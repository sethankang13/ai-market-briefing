import base64
import sys
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
    def test_sources_are_the_eight_v25_feeds(self):
        names = [feed["source"] for feed in collect_stories.SOURCES]
        self.assertEqual(
            names,
            [
                "Reuters AI",
                "CNBC Tech & Markets",
                "AP News Policy",
                "FT & WSJ Proxy",
                "TechCrunch AI",
                "VentureBeat AI",
                "OpenAI News",
                "Google AI Blog",
            ],
        )
        self.assertIn("site:reuters.com", collect_stories.SOURCES[0]["url"])
        self.assertEqual(
            collect_stories.SOURCES[4]["url"],
            "https://techcrunch.com/category/artificial-intelligence/feed/",
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
        </item></channel></rss>
        """.encode("utf-8")

        class Response:
            def read(self):
                return rss

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch.object(collect_stories, "urlopen", return_value=Response()):
            stories = collect_stories.fetch_feed(
                {"source": "Reuters AI", "url": "https://news.google.com/rss/search?q=ai"}
            )

        self.assertEqual(stories[0]["headline"], "AI earnings beat")
        self.assertEqual(stories[0]["description"], "Stock valuation rose.")
        self.assertEqual(stories[0]["link"], publisher)
        self.assertEqual(stories[0]["source"], "Reuters AI")


if __name__ == "__main__":
    unittest.main()
