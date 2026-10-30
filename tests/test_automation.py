import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DailyAutomationTests(unittest.TestCase):
    def test_plist_runs_every_day_at_eight_without_weekday(self):
        plist = (PROJECT_ROOT / "scripts" / "com.loop.dailybriefing.plist").read_text(
            encoding="utf-8"
        )
        self.assertIn("<key>RunAtLoad</key>", plist)
        self.assertIn("<key>Hour</key>", plist)
        self.assertIn("<integer>8</integer>", plist)
        self.assertIn("<key>Minute</key>", plist)
        self.assertIn("<integer>0</integer>", plist)
        self.assertNotIn("<key>Weekday</key>", plist)
        self.assertIn("StartCalendarInterval", plist)
        self.assertNotIn("<array>", plist.split("StartCalendarInterval", 1)[1])

    def test_run_daily_sources_env_logs_and_skips_existing_brief(self):
        script = (PROJECT_ROOT / "scripts" / "run_daily.sh").read_text(encoding="utf-8")
        self.assertIn(
            'export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"',
            script,
        )
        self.assertIn("source .env", script)
        self.assertIn("set -a", script)
        self.assertIn("set +a", script)
        self.assertNotIn("GEMINI_API_KEY", script)
        self.assertIn('log_line "start: daily briefing"', script)
        self.assertIn('log_line "failure: daily briefing exit ${status}"', script)
        self.assertIn('log_line "complete: daily briefing"', script)
        self.assertIn('if [ -f "$BRIEF" ]; then', script)
        self.assertIn("logs/briefing.lock", script)
        self.assertIn("python3 src/run_briefing.py", script)
        self.assertIn("Python.framework/Versions/Current/bin", script)
