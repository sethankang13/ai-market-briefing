import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import run_briefing


class RunBriefingTests(unittest.TestCase):
    def test_steps_run_in_order_and_pass_the_previous_file(self):
        order = []

        def collect_step():
            order.append("collect")
            return Path("data/raw/2026-09-20.json")

        def enrich_step(raw_path):
            order.append(("enrich", raw_path))
            return Path("data/enriched/2026-09-20.json")

        def select_step(enriched_path):
            order.append(("select", enriched_path))
            return Path("data/selected/2026-09-20.json")

        def summarize_step(selected_path):
            order.append(("summarize", selected_path))
            return Path("data/summarized/2026-09-20.json")

        def write_brief_step(summarized_path):
            order.append(("write_brief", summarized_path))
            return Path("briefs/2026-09-20.md")

        with (
            patch.object(run_briefing, "collect_step", collect_step),
            patch.object(run_briefing, "enrich_step", enrich_step),
            patch.object(run_briefing, "select_step", select_step),
            patch.object(run_briefing, "summarize_step", summarize_step),
            patch.object(run_briefing, "write_brief_step", write_brief_step),
        ):
            brief = run_briefing.run_briefing()

        self.assertEqual(brief, Path("briefs/2026-09-20.md"))
        self.assertEqual(
            order,
            [
                "collect",
                ("enrich", Path("data/raw/2026-09-20.json")),
                ("select", Path("data/enriched/2026-09-20.json")),
                ("summarize", Path("data/selected/2026-09-20.json")),
                ("write_brief", Path("data/summarized/2026-09-20.json")),
            ],
        )

    def test_a_failed_step_stops_the_pipeline_and_names_the_step(self):
        called = []

        def collect_step():
            called.append("collect")
            return Path("data/raw/2026-09-20.json")

        def enrich_step(raw_path):
            called.append("enrich")
            raise RuntimeError("disk full")

        def select_step(enriched_path):
            called.append("select")
            return Path("data/selected/2026-09-20.json")

        with (
            patch.object(run_briefing, "collect_step", collect_step),
            patch.object(run_briefing, "enrich_step", enrich_step),
            patch.object(run_briefing, "select_step", select_step),
        ):
            with self.assertRaises(run_briefing.StepFailed) as caught:
                run_briefing.run_briefing()

        self.assertEqual(caught.exception.step, "enrich")
        self.assertIn("enrich failed", str(caught.exception))
        self.assertEqual(called, ["collect", "enrich"])


if __name__ == "__main__":
    unittest.main()
