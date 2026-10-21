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
                                    "meta": {},
                                    "indicators": {"quote": [{"close": [5000.0, 5123.45]}]},
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
        self.assertEqual(spx["previous_close"], 5123.45)
        self.assertAlmostEqual(spx["percent_change"], (5123.45 - 5000.0) / 5000.0 * 100)
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
