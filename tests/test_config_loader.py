import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import config_loader


class LoadConfigTests(unittest.TestCase):
    def test_load_config_reads_the_project_yaml(self):
        config = config_loader.load_config()
        self.assertEqual(config["pipeline"]["recency_cutoff_hours"], 48)
        self.assertEqual(config["pipeline"]["top_selected_stories"], 5)
        self.assertEqual(config["pipeline"]["output_dir"], "briefs")
        self.assertEqual(config["pipeline"]["db_path"], "data/loop.db")
        self.assertEqual(len(config["feeds"]), 20)
        self.assertEqual(
            list(config["feeds"]),
            [
                "Politico Elections & Campaigns",
                "Politico Congress & Policy",
                "AP News Politics",
                "Washington Post Politics",
                "CBS News Politics",
                "WSJ, Bloomberg & FT Markets",
                "Reuters Business & Markets",
                "CNBC Markets",
                "MarketWatch Top Stories",
                "CNBC Economy & Fed",
                "Reuters Economy & Labor",
                "Federal Reserve Press Releases",
                "FT & WSJ Geopolitics",
                "Reuters Geopolitics",
                "BBC World News",
                "TechCrunch General",
                "Reuters Tech & Hardware",
                "CNBC Tech & Enterprise",
                "Reuters M&A & Private Equity",
                "Axios Feed",
            ],
        )
        self.assertEqual(
            config["models"]["gemini"],
            [
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-2.5-flash",
            ],
        )
        self.assertEqual(config["models"]["openai_fallback"], "gpt-4o-mini")
        self.assertEqual(len(config["taxonomy"]), 6)
        self.assertEqual(
            list(config["taxonomy"]),
            [
                "US Politics",
                "Market Valuations",
                "Labor & Economy",
                "Geopolitics & Trade",
                "Tech & Innovation",
                "Venture & M&A",
            ],
        )
        self.assertIn("bill", config["taxonomy"]["US Politics"])
        self.assertEqual(config["tag_weights"]["US Politics"], 100)
        self.assertGreater(
            config["tag_weights"]["US Politics"],
            config["tag_weights"]["Tech & Innovation"],
        )

    def test_missing_file_returns_the_same_internal_defaults(self):
        missing = Path("/tmp/loop-config-does-not-exist.yaml")
        self.assertFalse(missing.exists())
        loaded = config_loader.load_config(missing)
        self.assertEqual(loaded, config_loader.DEFAULT_CONFIG)
        loaded["pipeline"]["top_selected_stories"] = 99
        self.assertEqual(
            config_loader.load_config(missing)["pipeline"]["top_selected_stories"],
            5,
        )

    def test_load_config_uses_yaml_safe_load_not_load(self):
        source = Path(config_loader.__file__).read_text(encoding="utf-8")
        self.assertIn("yaml.safe_load", source)
        self.assertNotIn("yaml.load(", source)
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text("pipeline:\n  top_selected_stories: 3\n", encoding="utf-8")
            with patch.object(
                config_loader.yaml,
                "safe_load",
                return_value={"pipeline": {"top_selected_stories": 3}},
            ) as safe_load:
                config = config_loader.load_config(path)
            safe_load.assert_called_once()
            self.assertEqual(config["pipeline"]["top_selected_stories"], 3)
            self.assertEqual(config["pipeline"]["recency_cutoff_hours"], 48)

    def test_present_file_overrides_defaults(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            path.write_text(
                "pipeline:\n  recency_cutoff_hours: 24\nfeeds:\n  Example: https://example.com/rss\n",
                encoding="utf-8",
            )
            config = config_loader.load_config(path)
        self.assertEqual(config["pipeline"]["recency_cutoff_hours"], 24)
        self.assertEqual(config["feeds"], {"Example": "https://example.com/rss"})
        self.assertNotIn("CBS News Politics", config["feeds"])
        self.assertEqual(config["models"]["openai_fallback"], "gpt-4o-mini")


if __name__ == "__main__":
    unittest.main()
