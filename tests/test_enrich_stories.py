import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import enrich_stories


class EnrichStoriesTests(unittest.TestCase):
    def test_latest_raw_run_uses_the_newest_date_named_file(self):
        with TemporaryDirectory() as temporary_directory:
            raw_directory = Path(temporary_directory)
            (raw_directory / "2026-09-19.json").write_text("{}", encoding="utf-8")
            newest_run = raw_directory / "2026-09-20.json"
            newest_run.write_text("{}", encoding="utf-8")

            self.assertEqual(enrich_stories.latest_raw_run(raw_directory), newest_run)

    def test_enrichment_creates_a_tagged_copy_without_changing_raw_data(self):
        raw_run = {
            "stories": [
                {
                    "headline": "Government policy bill advances",
                    "description": "Enterprise teams want a clearer law.",
                    "source": "Example News",
                    "link": "https://example.com/story",
                    "published_at": "Today",
                }
            ],
            "failed_sources": ["NPR Economy"],
        }
        original_story = raw_run["stories"][0].copy()

        with TemporaryDirectory() as temporary_directory:
            temporary_directory_path = Path(temporary_directory)
            input_path = temporary_directory_path / "2026-09-20.json"
            input_path.write_text(json.dumps(raw_run), encoding="utf-8")
            original_output_directory = enrich_stories.ENRICHED_DATA_DIRECTORY
            enrich_stories.ENRICHED_DATA_DIRECTORY = temporary_directory_path / "enriched"
            try:
                output_path = enrich_stories.save_enriched_run(raw_run, input_path)
            finally:
                enrich_stories.ENRICHED_DATA_DIRECTORY = original_output_directory

            saved_run = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(raw_run["stories"][0], original_story)
        self.assertEqual(saved_run["raw_run"], "2026-09-20.json")
        self.assertEqual(saved_run["failed_sources"], ["NPR Economy"])
        self.assertEqual(
            saved_run["stories"][0]["tags"],
            ["US Politics"],
        )
        self.assertEqual(saved_run["stories"][0]["headline"], original_story["headline"])


if __name__ == "__main__":
    unittest.main()
