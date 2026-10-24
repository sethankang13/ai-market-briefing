import json
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import URLError


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fetch_market


class FetchMarketTests(unittest.TestCase):
    def test_snapshot_uses_previous_close_and_marks_failures(self):
        def fake_get(url: str, timeout: int = 15) -> bytes:
            if "all/latest" in url:
                return json.dumps(
                    {
                        "refRates": [
                            {"type": "SOFR", "percentRate": 3.90, "effectiveDate": "2026-10-20"},
                            {
                                "type": "EFFR",
                                "percentRate": 4.33,
                                "effectiveDate": "2026-10-20",
                            },
                        ]
                    }
                ).encode("utf-8")
            if "effr" in url:
                return json.dumps(
                    {"refRates": [{"percentRate": 4.33, "effectiveDate": "2026-10-20"}]}
                ).encode("utf-8")
            if "%5EGSPC" in url or "^GSPC" in url:
                return json.dumps(
                    {
                        "chart": {
                            "result": [
                                {
                                    "meta": {
                                        "previousClose": 5000.0,
                                        "chartPreviousClose": 5000.0,
                                        "regularMarketPrice": 5123.45,
                                        "regularMarketChangePercent": -0.42,
                                    },
                                    "indicators": {
                                        "quote": [{"close": [4980.0, 5000.0, 5123.45]}]
                                    },
                                }
                            ]
                        }
                    }
                ).encode("utf-8")
            if "%5EIXIC" in url:
                raise URLError("nasdaq down")
            if "%5EDJI" in url:
                return json.dumps({"chart": {"result": None, "error": "unavailable"}}).encode(
                    "utf-8"
                )
            raise AssertionError(url)

        with patch.object(fetch_market, "_get_bytes", side_effect=fake_get):
            snapshot = fetch_market.fetch_market_snapshot()

        self.assertEqual(snapshot["fed_funds"]["status"], "ok")
        self.assertEqual(snapshot["fed_funds"]["rate"], 4.33)
        spx = snapshot["indexes"]["^GSPC"]
        self.assertEqual(spx["status"], "ok")
        self.assertEqual(spx["previous_close"], 5000.0)
        self.assertAlmostEqual(spx["percent_change"], -0.42)
        self.assertEqual(snapshot["indexes"]["^IXIC"]["status"], "fetch failed")
        self.assertEqual(snapshot["indexes"]["^DJI"]["status"], "fetch failed")
        self.assertNotIn("previous_close", snapshot["indexes"]["^IXIC"])
        block = fetch_market.render_market_block(snapshot)
        self.assertIn("- Fed Funds: 4.33%", block)
        self.assertIn("- S&P 500:", block)
        self.assertIn("- Nasdaq: fetch failed", block)
        self.assertIn("- Dow: fetch failed", block)

    def test_failed_fed_funds_does_not_invent_a_rate(self):
        with patch.object(fetch_market, "_get_bytes", side_effect=URLError("fed down")):
            result = fetch_market.fetch_fed_funds()
        self.assertEqual(result["status"], "fetch failed")
        self.assertNotIn("rate", result)
        self.assertEqual(fetch_market.format_fed_funds(result), "fetch failed")

    def test_index_quote_uses_yahoo_previous_close_not_last_bar(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "chartPreviousClose": 7659.44,
                            "regularMarketPrice": 7623.68,
                            "regularMarketChangePercent": -0.519,
                        },
                        "indicators": {
                            "quote": [
                                {"close": [7712.57, 7757.17, 7663.43, 7623.68]}
                            ]
                        },
                    }
                ]
            }
        }
        with patch.object(
            fetch_market, "_get_bytes", return_value=json.dumps(payload).encode("utf-8")
        ):
            quote = fetch_market.fetch_index_quote("^GSPC", "S&P 500")
        self.assertEqual(quote["status"], "ok")
        self.assertEqual(quote["previous_close"], 7659.44)
        self.assertAlmostEqual(quote["percent_change"], -0.519)
        self.assertNotEqual(quote["previous_close"], 7623.68)
        block = fetch_market.render_market_block(
            {
                "fed_funds": {"status": "ok", "rate": 4.33},
                "indexes": {"^GSPC": quote, "^IXIC": quote, "^DJI": quote},
            }
        )
        self.assertIn('style="color:#C04545"', block)
        self.assertIn("-0.52%", block)

    def test_mock_fed_funds_is_realistic_and_not_failed(self):
        with patch.object(fetch_market, "_get_bytes", side_effect=AssertionError("network")):
            snapshot = fetch_market.mock_market_snapshot()
        self.assertEqual(snapshot["fed_funds"]["status"], "ok")
        self.assertEqual(snapshot["fed_funds"]["rate"], 4.33)
        formatted = fetch_market.format_fed_funds(snapshot["fed_funds"])
        self.assertEqual(formatted, "4.33%")
        self.assertNotEqual(formatted, "fetch failed")
        self.assertNotIn("fetch failed", fetch_market.render_market_block(snapshot))

    def test_fed_funds_falls_back_when_all_latest_fails(self):
        def fake_get(url: str, timeout: int = 15) -> bytes:
            if "all/latest" in url:
                raise URLError("all latest blocked")
            if "unsecured/effr" in url or "effr" in url:
                return json.dumps(
                    {"refRates": [{"percentRate": 4.33, "effectiveDate": "2026-10-20"}]}
                ).encode("utf-8")
            raise AssertionError(url)

        with patch.object(fetch_market, "_get_bytes", side_effect=fake_get):
            result = fetch_market.fetch_fed_funds()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["rate"], 4.33)
