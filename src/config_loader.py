"""Load Loop settings from ``config/config.yaml``.

Missing files fall back to the same defaults the pipeline used before
the config layer existed, so mocked unit tests still run offline.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = "config/config.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "pipeline": {
        "recency_cutoff_hours": 48,
        "top_selected_stories": 5,
        "output_dir": "briefs",
        "db_path": "data/loop.db",
    },
    "feeds": {
        "FT, WSJ & Bloomberg Proxy": (
            "https://news.google.com/rss/search?q=(site:ft.com+OR+site:wsj.com+"
            "OR+site:bloomberg.com)+(AI+OR+%22artificial+intelligence%22)"
            "&hl=en-US&gl=US&ceid=US:en"
        ),
        "Reuters Business & Markets": (
            "https://news.google.com/rss/search?q=site:reuters.com+"
            "(AI+OR+%22artificial+intelligence%22)+market&hl=en-US&gl=US&ceid=US:en"
        ),
        "CNBC Tech & Markets": (
            "https://news.google.com/rss/search?q=site:cnbc.com+"
            "(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en"
        ),
        "Politico AI Policy": (
            "https://news.google.com/rss/search?q=site:politico.com+"
            "(AI+OR+%22artificial+intelligence%22)&hl=en-US&gl=US&ceid=US:en"
        ),
        "AP News Policy": (
            "https://news.google.com/rss/search?q=site:apnews.com+"
            "(AI+OR+%22artificial+intelligence%22)+(policy+OR+government+OR+law)"
            "&hl=en-US&gl=US&ceid=US:en"
        ),
        "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
        "OpenAI News": "https://openai.com/news/rss.xml",
        "Google AI Blog": "https://blog.google/technology/ai/rss/",
    },
    "models": {
        "gemini": [
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-2.5-flash",
        ],
        "openai_fallback": "gpt-4o-mini",
    },
    "taxonomy": {
        "Market-Valuations": ["earnings", "stock", "market cap", "valuation"],
        "Venture-&-M&A": ["funding", "venture", "acquisition", "seed", "valuation"],
        "Legislation-&-Policy": [
            "bill",
            "law",
            "government",
            "executive order",
            "policy",
        ],
        "Antitrust-&-Compliance": [
            "FTC",
            "regulation",
            "EU AI Act",
            "probe",
            "investigation",
        ],
        "Copyright-&-IP": [
            "copyright",
            "lawsuit",
            "licensing",
            "data scraping",
            "IP",
        ],
        "Geopolitics-&-Trade": [
            "export controls",
            "chips",
            "sanctions",
            "China",
            "national security",
        ],
        "Labor-&-Economy": ["jobs", "workforce", "productivity", "economy", "lay-offs"],
        "Enterprise-Adoption": ["enterprise", "ROI", "corporate", "B2B", "SaaS"],
        "Foundation-Models": ["LLM", "GPT", "Claude", "Gemini", "weights", "benchmark"],
    },
    "tag_weights": {
        "Market-Valuations": 90,
        "Venture-&-M&A": 80,
        "Legislation-&-Policy": 70,
        "Antitrust-&-Compliance": 60,
        "Copyright-&-IP": 50,
        "Geopolitics-&-Trade": 40,
        "Labor-&-Economy": 30,
        "Enterprise-Adoption": 20,
        "Foundation-Models": 10,
    },
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def resolve_config_path(config_path: str | Path = DEFAULT_CONFIG_PATH) -> Path:
    path = Path(config_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def project_path(relative: str | Path) -> Path:
    """Resolve a config path against the project root unless it is absolute."""
    path = Path(relative)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_config(config_path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Return pipeline settings from YAML, or internal defaults if the file is missing.

    Uses ``yaml.safe_load`` so a config file cannot construct arbitrary Python
    objects. Callers receive a copy; mutating it does not change later loads.
    """
    path = resolve_config_path(config_path)
    if not path.is_file():
        return deepcopy(DEFAULT_CONFIG)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return deepcopy(DEFAULT_CONFIG)
    return _deep_merge(DEFAULT_CONFIG, loaded)
