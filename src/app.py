"""Local Streamlit UI for LOOP: AI Market Briefing.

Reads existing ``briefs/YYYY-MM-DD.md`` files and ``data/loop.db``.
Does not call Gemini, OpenAI, or any other model.

Run from the project folder:
    streamlit run src/app.py
"""

from __future__ import annotations

LOOP_VERSION = "4.1.2"

import html
import json
import os
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"
LOCK_PATH = PROJECT_ROOT / "logs" / "briefing.lock"
BRIEF_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_MD_HTTP_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_GLANCE_SLUG_LINK = re.compile(r"^(\s*-\s*)\[([^\]]+)\]\(#([^)]+)\)\s*$", re.M)
_BARE_URL_LINE = re.compile(r"^[ \t]*(?:[-*]\s*)?(https?://\S+)\s*$", re.M)
_ANCHOR_STORY = re.compile(
    r'<a id="([^"]+)"></a>\s*\n-\s*\[([^\]]+)\]\((https?://[^)]+)\)'
)
_LOOPING_TITLE = re.compile(r"^# Looping\.\.\. \(([^)]+)\)\s*$", re.M)
_BRIEF_INTRO = re.compile(
    r"^(?:Loop: AI Market Briefing\. )?"
    r"Selected public reporting, organized by topic\. "
    r"Links lead to the original source\.\s*\n+",
    re.M,
)
_ASK_GEMINI_HEADING = re.compile(
    r"^(?:Research topics to look into more|\*\*Ask Gemini:\*\*|Ask Gemini:)\s*$"
)
_PLAIN_NUMBERED_TOPIC = re.compile(r"^(\d+)\.\s+(?!<a )(?!\[)(.+)$")
_NUMBERED_TOPIC_HTML = re.compile(
    r'^(\d+)\.\s+<a href="([^"]+)"[^>]*>(.*?)</a>\s*$'
)
_GLANCE_CLUSTER = re.compile(
    r'^(<a\b[^>]*>.*?</a>):\s*(.+)$'
)
_GLANCE_MD_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)")
_PERCENT_UP_SPAN = re.compile(
    r'<span style="color:\s*#2F7D4F">([^<]*)</span>', re.I
)
_PERCENT_DOWN_SPAN = re.compile(
    r'<span style="color:\s*#C04545">([^<]*)</span>', re.I
)
TAB_DAILY = "Daily Loop"
TAB_LOOP = "The Loop"
LOOP_HEADER_HTML = """
<div class="loop-header">
  <div class="loop-mark" aria-label="LOOP glasses">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 48" class="loop-glasses" role="img">
      <g fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="28.5" cy="24" r="16.5" stroke-width="2.2"/>
        <circle cx="67.5" cy="24" r="16.5" stroke-width="2.2"/>
        <path d="M45 24h6" stroke-width="1.6"/>
      </g>
    </svg>
  </div>
  <div class="loop-wordmark">
    <div class="loop-wordmark-name">LOOP</div>
    <div class="loop-wordmark-desc">AI Market Briefing</div>
  </div>
</div>
"""

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import streamlit as st
from config_loader import flatten_feed_urls, load_config, nested_feed_tree, project_path
from write_brief import (
    TAG_ARCHIVE_BASE,
    TAG_COLORS,
    TAG_LABELS,
    ask_gemini_topic_html,
    humanize_tag,
    tag_archive_url,
    tag_hashtag_html,
)


def _loop_prefixed(prefix: str) -> str:
    """Prefix every canvas selector so comma lists stay under the html theme."""
    parts = [
        prefix,
        f"{prefix} body",
        f"{prefix} .stApp",
        f"{prefix} [data-testid='stAppViewContainer']",
        f"{prefix} [data-testid='stMain']",
        f"{prefix} [data-testid='stSidebar']",
        f"{prefix} [data-testid='stHeader']",
        f"{prefix} [data-testid='stBottomBlockContainer']",
    ]
    return ",\n".join(parts)


def brand_css() -> str:
    """Ivory/ink from data-loop-theme; Light/Dark beat OS, System follows it."""
    chip_colors = "\n".join(
        f'a.loop-tag[href*="{urlencode({"tag": tag})}"] .loop-tag-swatch '
        f"{{ background-color: {color}; }}\n"
        f'a.loop-tag[href*="{urlencode({"tag": tag})}"] '
        f"{{ text-decoration-color: {color}; }}"
        for tag, color in TAG_COLORS.items()
    )
    light_sel = _loop_prefixed('html[data-loop-theme="light"]')
    dark_sel = _loop_prefixed('html[data-loop-theme="dark"]')
    unset_sel = _loop_prefixed("html:not([data-loop-theme])")
    return f"""
<style data-loop-brand="1">
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap");
:root {{
  --loop-ink: #171C25;
  --loop-navy: #263B60;
  --loop-slate: #64748B;
  --loop-ice: #A7C7E7;
  --loop-ivory: #F7F6F2;
  --loop-mist: #E5EAF0;
  --loop-radius: 10px;
  --loop-fg: #171C25;
  --loop-muted: #4A5568;
  --loop-page: #F7F6F2;
  --loop-surface: #E5EAF0;
  --loop-border: #E5EAF0;
  --loop-accent: #263B60;
  --loop-input: #E5EAF0;
}}
html {{ color-scheme: light dark; overscroll-behavior: none; }}
body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"],
[data-testid="stSidebar"], [data-testid="stHeader"],
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li, [data-testid="stMarkdownContainer"] span,
[data-testid="stMarkdownContainer"] h1, [data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3, [data-testid="stCaptionContainer"],
[data-testid="stWidgetLabel"], h1, h2, h3, button, input, label, a {{
  font-family: Inter, "Helvetica Neue", Helvetica, Arial, sans-serif !important;
}}
.stApp, [data-testid="stAppViewContainer"] {{
  overscroll-behavior: none;
}}
[data-testid="stMainBlockContainer"],
[data-testid="stMain"] .block-container {{
  max-width: none !important;
  width: 100%;
}}
{light_sel} {{
  --loop-fg: #171C25;
  --loop-muted: #4A5568;
  --loop-page: #F7F6F2;
  --loop-surface: #E5EAF0;
  --loop-border: #E5EAF0;
  --loop-accent: #263B60;
  --loop-input: #E5EAF0;
  background-color: #F7F6F2 !important;
  color: #171C25 !important;
  color-scheme: light;
}}
{dark_sel} {{
  --loop-fg: #F7F6F2;
  --loop-muted: #94A3B8;
  --loop-page: #171C25;
  --loop-surface: #263B60;
  --loop-border: #263B60;
  --loop-accent: #A7C7E7;
  --loop-input: #171C25;
  background-color: #171C25 !important;
  color: #F7F6F2 !important;
  color-scheme: dark;
}}
html[data-loop-theme="light"] .loop-wordmark-name,
html[data-loop-theme="light"] .loop-wordmark-desc,
html[data-loop-theme="light"] .loop-glasses {{
  color: #171C25 !important;
}}
html[data-loop-theme="dark"] .loop-wordmark-name,
html[data-loop-theme="dark"] .loop-wordmark-desc,
html[data-loop-theme="dark"] .loop-glasses {{
  color: #F7F6F2 !important;
}}
@media (prefers-color-scheme: light) {{
  {unset_sel} {{
    --loop-fg: #171C25;
    --loop-muted: #4A5568;
    --loop-page: #F7F6F2;
    --loop-surface: #E5EAF0;
    --loop-border: #E5EAF0;
    --loop-accent: #263B60;
    --loop-input: #E5EAF0;
    background-color: #F7F6F2 !important;
    color: #171C25 !important;
    color-scheme: light;
  }}
}}
@media (prefers-color-scheme: dark) {{
  {unset_sel} {{
    --loop-fg: #F7F6F2;
    --loop-muted: #94A3B8;
    --loop-page: #171C25;
    --loop-surface: #263B60;
    --loop-border: #263B60;
    --loop-accent: #A7C7E7;
    --loop-input: #171C25;
    background-color: #171C25 !important;
    color: #F7F6F2 !important;
    color-scheme: dark;
  }}
}}
html[data-loop-theme="light"] [data-testid="stSelectbox"] .react-aria-ComboBox,
html[data-loop-theme="light"] [data-testid="stSelectbox"] [role="group"],
html[data-loop-theme="light"] [data-testid="stSelectbox"] input,
html[data-loop-theme="light"] [data-testid="stSelectbox"] button {{
  background-color: #E5EAF0 !important;
  color: #171C25 !important;
  border-color: #E5EAF0 !important;
}}
html[data-loop-theme="dark"] [data-testid="stSelectbox"] .react-aria-ComboBox,
html[data-loop-theme="dark"] [data-testid="stSelectbox"] [role="group"],
html[data-loop-theme="dark"] [data-testid="stSelectbox"] input,
html[data-loop-theme="dark"] [data-testid="stSelectbox"] button {{
  background-color: #171C25 !important;
  color: #F7F6F2 !important;
  border-color: #263B60 !important;
}}
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stMarkdownContainer"] span,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3,
[data-testid="stCaptionContainer"],
[data-testid="stWidgetLabel"],
[data-testid="stMetricValue"],
[data-testid="stMetricLabel"],
[data-testid="stAlert"],
h1, h2, h3 {{
  color: var(--loop-fg);
  font-weight: 500;
}}
h1 {{
  font-size: 1.75rem;
  font-weight: 600;
  letter-spacing: 0.01em;
}}
h2 {{
  font-size: 1.55rem;
  font-weight: 600;
  letter-spacing: 0.01em;
}}
h3 {{
  font-weight: 600;
  letter-spacing: 0.01em;
}}
a[id], h1, h2, h3, [id] {{ scroll-margin-top: 90px; }}
.stApp a.loop-glance,
.stApp [data-testid="stMarkdownContainer"] a.loop-glance {{
  color: var(--loop-fg);
  font-style: italic;
  font-weight: 400;
  font-size: 0.92rem !important;
  line-height: 1.45;
  text-decoration: none;
}}
.loop-glance-body,
.loop-glance-line,
.loop-glance-body p,
.loop-glance-body a {{
  font-size: 0.92rem !important;
  font-style: normal;
  font-weight: 400 !important;
  line-height: 1.45 !important;
  color: var(--loop-fg);
}}
.loop-glance-body a.loop-glance,
.loop-glance-body a[href^="#"] {{
  font-style: italic !important;
}}
.loop-glance-body h2 {{
  font-size: 1.55rem !important;
  font-style: normal !important;
  font-weight: 600 !important;
}}
.loop-glance-body ul,
.loop-glance-body ol {{
  list-style: none !important;
  padding-left: 0 !important;
  margin: 0.15rem 0 0.55rem;
}}
.loop-glance-body li {{
  list-style: none !important;
}}
.loop-glance-body li::marker {{
  content: none !important;
}}
.loop-glance-body a svg,
.loop-glance-line a svg,
.loop-glance-body [data-testid="stIconMaterial"],
.loop-glance-body [data-testid="stIcon"] {{
  display: none !important;
}}
.loop-glance-line {{
  margin: 0 0 0.35rem;
}}
.loop-delta-up {{ color: #2F7D4F !important; }}
.loop-delta-down {{ color: #C04545 !important; }}
span[style*="#2F7D4F"], span[style*="#2f7d4f"] {{ color: #2F7D4F !important; }}
span[style*="#C04545"], span[style*="#c04545"] {{ color: #C04545 !important; }}
.stCaption, small, [data-testid="stCaptionContainer"] p {{
  color: var(--loop-muted);
}}
hr {{ border: none; border-top: 1px solid var(--loop-border); }}
[data-testid="stHeader"], [data-testid="stToolbar"] {{
  background: color-mix(in srgb, var(--loop-page) 88%, transparent);
  color: var(--loop-fg);
  backdrop-filter: saturate(1.1) blur(10px);
  -webkit-backdrop-filter: saturate(1.1) blur(10px);
}}
[data-testid="stAppDeployButton"],
.stAppDeployButton,
.stDeployButton,
div[class*="stDeployButton"] {{
  display: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
  width: 0 !important;
  min-width: 0 !important;
  overflow: hidden !important;
}}
[data-testid="stSidebar"] {{
  background-color: var(--loop-page);
  color: var(--loop-fg);
  border-color: var(--loop-border);
}}
[data-testid="stTabs"] button,
button[role="tab"] {{
  color: var(--loop-muted) !important;
  background: transparent;
  font-weight: 500;
}}
[data-testid="stTabs"] button[aria-selected="true"],
button[role="tab"][aria-selected="true"] {{
  color: var(--loop-fg) !important;
  font-weight: 600;
}}
[data-testid="stSelectbox"] {{
  max-width: 17.5rem;
  width: fit-content;
}}
[data-testid="stForm"] [data-testid="stSelectbox"] {{
  max-width: none;
  width: 100%;
}}
[data-testid="stSelectbox"] > div,
[data-testid="stSelectbox"] .react-aria-ComboBox,
[data-testid="stSelectbox"] [role="group"],
[data-testid="stSelectbox"] input,
[data-testid="stSelectbox"] button,
[data-testid="stTextInput"] input,
[data-baseweb="select"] > div,
[data-baseweb="input"] {{
  background-color: var(--loop-input) !important;
  color: var(--loop-fg) !important;
  border-color: var(--loop-border) !important;
  border-radius: 10px !important;
  font-family: Inter, "Helvetica Neue", Helvetica, Arial, sans-serif !important;
}}
[data-testid="stForm"] [data-testid="stTextInput"] {{
  max-width: none;
  width: 100%;
}}
[data-testid="stFormSubmitButton"] button,
[data-testid="stFormSubmitButton"] button p,
[data-testid="stFormSubmitButton"] button span,
[data-testid="stFormSubmitButton"] [data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondary"] p,
[data-testid="stBaseButton-secondary"] span {{
  border: none !important;
  border-radius: 10px !important;
  font-weight: 600 !important;
}}
html[data-loop-theme="light"] [data-testid="stFormSubmitButton"] button,
html[data-loop-theme="light"] [data-testid="stFormSubmitButton"] button p,
html[data-loop-theme="light"] [data-testid="stFormSubmitButton"] button span,
html[data-loop-theme="light"] [data-testid="stBaseButton-secondary"],
html[data-loop-theme="light"] [data-testid="stBaseButton-secondary"] p,
html[data-loop-theme="light"] [data-testid="stBaseButton-secondary"] span {{
  background-color: #263B60 !important;
  color: #F7F6F2 !important;
}}
html[data-loop-theme="dark"] [data-testid="stFormSubmitButton"] button,
html[data-loop-theme="dark"] [data-testid="stFormSubmitButton"] button p,
html[data-loop-theme="dark"] [data-testid="stFormSubmitButton"] button span,
html[data-loop-theme="dark"] [data-testid="stBaseButton-secondary"],
html[data-loop-theme="dark"] [data-testid="stBaseButton-secondary"] p,
html[data-loop-theme="dark"] [data-testid="stBaseButton-secondary"] span {{
  background-color: #A7C7E7 !important;
  color: #171C25 !important;
}}
@media (prefers-color-scheme: light) {{
  html:not([data-loop-theme]) [data-testid="stFormSubmitButton"] button,
  html:not([data-loop-theme]) [data-testid="stFormSubmitButton"] button p,
  html:not([data-loop-theme]) [data-testid="stFormSubmitButton"] button span,
  html:not([data-loop-theme]) [data-testid="stBaseButton-secondary"] {{
    background-color: #263B60 !important;
    color: #F7F6F2 !important;
  }}
}}
@media (prefers-color-scheme: dark) {{
  html:not([data-loop-theme]) [data-testid="stFormSubmitButton"] button,
  html:not([data-loop-theme]) [data-testid="stFormSubmitButton"] button p,
  html:not([data-loop-theme]) [data-testid="stFormSubmitButton"] button span,
  html:not([data-loop-theme]) [data-testid="stBaseButton-secondary"] {{
    background-color: #A7C7E7 !important;
    color: #171C25 !important;
  }}
}}
button:active,
a:active,
[role="tab"]:active,
[data-testid="stBaseButton-primary"]:active,
[data-testid="stFormSubmitButton"] button:active {{
  transform: scale(0.97);
}}
[data-testid="stSelectbox"] span,
[data-testid="stSelectbox"] p,
[data-baseweb="select"] span {{
  color: var(--loop-fg) !important;
  font-family: Inter, "Helvetica Neue", Helvetica, Arial, sans-serif !important;
}}
[data-testid="stSelectbox"] svg,
[data-baseweb="select"] svg {{
  fill: var(--loop-fg) !important;
  color: var(--loop-fg) !important;
}}
[data-testid="stForm"] {{
  background-color: var(--loop-page);
  border-color: var(--loop-border);
  color: var(--loop-fg);
  border-radius: 10px;
}}
[data-testid="stExpander"],
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stPopover"] {{
  background-color: var(--loop-page) !important;
  border-color: var(--loop-border);
  color: var(--loop-fg);
  border-radius: 10px;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}}
[data-testid="stBaseButton-secondaryFormSubmit"],
[data-testid="stFormSubmitButton"] button,
button[kind="secondaryFormSubmit"] {{
  border-radius: 10px;
}}
.loop-header {{
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  text-align: left;
  gap: 1rem;
  color: var(--loop-fg);
  padding: 0.4rem 0 0.8rem;
  width: 100%;
}}
.loop-mark, .loop-glasses, .loop-wordmark {{
  color: inherit;
}}
.loop-mark {{
  width: 88px;
  flex: 0 0 auto;
}}
.loop-glasses {{
  width: 88px;
  height: 44px;
  display: block;
  margin: 0;
}}
.loop-wordmark-name {{
  font-family: Inter, "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 2.35rem;
  font-weight: 400;
  letter-spacing: 0.18em;
  color: var(--loop-fg);
  line-height: 1.05;
  text-transform: uppercase;
}}
.loop-wordmark-desc {{
  font-family: Inter, "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 0.92rem;
  font-weight: 400;
  letter-spacing: 0.08em;
  color: var(--loop-fg);
  margin-top: 0.25rem;
}}
a.loop-tag {{
  color: var(--loop-fg) !important;
  font-weight: 500;
  background: none;
  border: none;
  border-radius: 4px;
  padding: 0.08rem 0.28rem;
  margin: 0 0.35rem 0 0;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  text-decoration: underline;
  text-decoration-thickness: 2px;
  text-underline-offset: 0.18em;
  font-size: 0.92rem;
}}
a.loop-tag:hover {{
  background-color: rgba(0, 0, 0, 0.06);
}}
.loop-in-focus {{
  font-size: 1.55rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--loop-fg);
  text-decoration: none;
  margin: 0 0 0.45rem;
}}
.loop-in-focus-tag {{
  text-decoration: underline;
  text-decoration-thickness: 2px;
  text-underline-offset: 0.18em;
  font-weight: 600;
}}
.loop-in-focus-wrap [data-testid="stHeaderActionElements"],
[data-testid="stHeaderActionElements"] {{
  display: none !important;
  pointer-events: none !important;
  width: 0 !important;
  min-width: 0 !important;
  overflow: hidden !important;
}}
a.loop-feed-parent {{
  color: var(--loop-fg) !important;
  font-weight: 600;
  text-decoration: none;
  display: inline-block;
  border-radius: 4px;
  padding: 0.05rem 0.15rem;
}}
a.loop-feed-parent:hover {{
  background-color: rgba(0, 0, 0, 0.06);
}}
h3.loop-story-title {{
  font-size: 1.15rem;
  font-weight: 600;
  margin: 0 0 0.35rem;
}}
h3.loop-story-title a {{
  color: var(--loop-fg);
  text-decoration: none;
}}
.loop-tag-swatch {{
  display: inline-block;
  width: 6px;
  height: 0.85em;
  border-radius: 2px;
  flex: 0 0 6px;
}}
{chip_colors}
div[data-testid="stHtml"] {{
  height: 0;
  min-height: 0;
  overflow: hidden;
}}
@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto; }}
  *, *::before, *::after {{
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }}
  button:active, a:active, [role="tab"]:active {{
    transform: none;
  }}
}}
@media (prefers-reduced-transparency: reduce) {{
  [data-testid="stHeader"], [data-testid="stToolbar"] {{
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    background: var(--loop-page);
  }}
}}
@media (prefers-contrast: more) {{
  :root, html[data-loop-theme="light"] {{
    --loop-muted: #334155;
    --loop-border: #171C25;
  }}
  html[data-loop-theme="dark"] {{
    --loop-muted: #B0BCCB;
    --loop-border: #F7F6F2;
  }}
  a, button, [role="tab"] {{
    text-decoration-thickness: 2px;
  }}
}}
</style>
"""


def brand_theme_script() -> str:
    """Follow Streamlit ⋮ Light/Dark/System; paint LOOP ivory/ink from that choice."""
    return """
<script>
(function () {
  var doc = document;
  try {
    if (window.parent && window.parent.document) doc = window.parent.document;
  } catch (err) {}
  var win = doc.defaultView || window;
  var KEY = "loop-theme";
  var local = document.querySelector("style[data-loop-brand]");
  if (local && doc.head) {
    var style = doc.getElementById("loop-brand-css") || doc.createElement("style");
    style.id = "loop-brand-css";
    style.setAttribute("data-loop-brand", "1");
    style.textContent = local.textContent;
    if (!style.parentNode) doc.head.appendChild(style);
  }
  function osScheme() {
    return win.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function stThemeKey() {
    return "stActiveTheme-" + ((win.location && win.location.pathname) || "/") + "-v2";
  }
  function parseChoice(raw) {
    if (raw == null) return null;
    var value = raw;
    try { value = JSON.parse(raw); } catch (err) {}
    if (typeof value !== "string") return null;
    var mode = value.replace(/^"+|"+$/g, "").toLowerCase();
    if (mode === "light" || mode === "dark" || mode === "system") return mode;
    return null;
  }
  function readSt() {
    try { return parseChoice(win.localStorage.getItem(stThemeKey())); } catch (err) {}
    try { return parseChoice(win.localStorage.getItem("stActiveTheme")); } catch (err) {}
    return null;
  }
  function choice() {
    try {
      var loop = parseChoice(win.localStorage.getItem(KEY));
      if (loop) return loop;
    } catch (err) {}
    return readSt() || "system";
  }
  function resolved() {
    var mode = choice();
    return (mode === "light" || mode === "dark") ? mode : osScheme();
  }
  function persist(mode) {
    var label = mode === "light" ? "Light" : mode === "dark" ? "Dark" : "System";
    win.__loopWriting = true;
    try {
      win.localStorage.setItem(KEY, mode);
      win.localStorage.setItem(stThemeKey(), JSON.stringify(label));
      win.localStorage.setItem("stActiveTheme", JSON.stringify(label));
    } catch (err) {}
    win.__loopWriting = false;
  }
  function paint() {
    var html = doc.documentElement;
    if (!html) return;
    if (html.style && html.style.removeProperty) html.style.removeProperty("color-scheme");
    var theme = resolved();
    html.setAttribute("data-loop-theme", theme);
    html.setAttribute("data-theme", theme);
    if (typeof paintSearch === "function") paintSearch();
  }
  if (!win.__loopStorageHooked) {
    win.__loopStorageHooked = true;
    var origSet = win.localStorage.setItem.bind(win.localStorage);
    win.localStorage.setItem = function (key, value) {
      origSet(key, value);
      if (win.__loopWriting) return;
      if (String(key).indexOf("stActiveTheme") === 0 || key === KEY) {
        var parsed = key === KEY ? parseChoice(value) : parseChoice(value);
        if (parsed) {
          win.__loopWriting = true;
          try {
            origSet(KEY, parsed);
            var label = parsed === "light" ? "Light" : parsed === "dark" ? "Dark" : "System";
            origSet(stThemeKey(), JSON.stringify(label));
          } catch (err) {}
          win.__loopWriting = false;
          paint();
        }
      }
    };
    win.addEventListener("storage", function (event) {
      if (!event || !event.key) return;
      if (event.key === KEY || String(event.key).indexOf("stActiveTheme") === 0) paint();
    });
  }
  if (!doc.__loopThemeBound) {
    doc.__loopThemeBound = true;
    doc.addEventListener("click", function (event) {
      var target = event.target;
      var item = target.closest ? target.closest("[data-testid^='stMainMenuItem-theme-']") : null;
      if (!item) return;
      var id = item.getAttribute("data-testid") || "";
      var fromMenu = id.indexOf("theme-Dark") >= 0 ? "dark" : id.indexOf("theme-Light") >= 0 ? "light" : id.indexOf("theme-System") >= 0 ? "system" : null;
      if (!fromMenu) return;
      persist(fromMenu);
      paint();
    }, true);
  }
  persist(choice());
  paint();
  var media = win.matchMedia("(prefers-color-scheme: dark)");
  if (media.addEventListener) media.addEventListener("change", paint);
  else if (media.addListener) media.addListener(paint);
  function labelSidebar() {
    var nodes = doc.querySelectorAll(
      '[data-testid="stExpandSidebarButton"], [data-testid="stCollapseSidebarButton"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"], [data-testid="stSidebarCollapseButton"]'
    );
    nodes.forEach(function (el) {
      var btn = el.tagName === "BUTTON" ? el : el.querySelector("button") || el;
      var expanded = btn.getAttribute("aria-expanded");
      var label = expanded === "true" ? "Close LOOP sidebar" : "Open LOOP sidebar";
      btn.setAttribute("aria-label", label);
      btn.setAttribute("title", label);
    });
  }
  function searchColors() {
    var theme = doc.documentElement.getAttribute("data-loop-theme") || resolved();
    if (theme === "dark") return { color: "#171C25", bg: "#A7C7E7" };
    return { color: "#F7F6F2", bg: "#263B60" };
  }
  function paintSearch() {
    var colors = searchColors();
    var roots = doc.querySelectorAll('[data-testid="stFormSubmitButton"], [data-testid="stBaseButton-secondary"]');
    roots.forEach(function (root) {
      var nodes = root.querySelectorAll("button, button p, button span, [data-testid='stBaseButton-secondary']");
      if (root.matches && root.matches("[data-testid='stBaseButton-secondary']")) {
        nodes = [root].concat(Array.prototype.slice.call(nodes));
      }
      nodes.forEach(function (el) {
        el.style.setProperty("color", colors.color, "important");
        var testid = el.getAttribute && el.getAttribute("data-testid");
        if (el.tagName === "BUTTON" || (testid && testid.indexOf("stBaseButton") === 0)) {
          el.style.setProperty("background-color", colors.bg, "important");
        }
      });
    });
  }
  var TAB_DAILY = "Daily Loop";
  var TAB_LOOP = "The Loop";
  function tabLabel(btn) {
    return String((btn && (btn.innerText || btn.textContent)) || "").replace(new RegExp("\\s+", "g"), " ").trim();
  }
  function tabButtons() {
    return Array.prototype.slice.call(doc.querySelectorAll('[role="tab"]'));
  }
  function desiredTab() {
    var forced = doc.querySelector("[data-loop-select-tab]");
    if (forced) {
      var name = forced.getAttribute("data-loop-select-tab");
      forced.removeAttribute("data-loop-select-tab");
      if (name === TAB_DAILY || name === TAB_LOOP) {
        try { win.sessionStorage.setItem("loopActiveTab", name); } catch (err) {}
        return name;
      }
    }
    try {
      var stored = win.sessionStorage.getItem("loopActiveTab");
      if (stored === TAB_DAILY || stored === TAB_LOOP) return stored;
    } catch (err) {}
    try {
      var params = new URLSearchParams((win.location && win.location.search) || "");
      if (params.get("tag") || params.get("source")) return TAB_LOOP;
    } catch (err) {}
    return null;
  }
  function clickTab(name) {
    if (!name) return;
    var match = tabButtons().find(function (btn) { return tabLabel(btn) === name; });
    if (!match) return;
    if (match.getAttribute("aria-selected") === "true") return;
    match.click();
  }
  function applyTab() {
    clickTab(desiredTab());
  }
  function retargetLoopLinks() {
    doc.querySelectorAll("a.loop-tag, a.loop-feed-parent").forEach(function (a) {
      a.setAttribute("target", "_self");
      a.removeAttribute("rel");
    });
  }
  function bindTabsAndSameTab(root) {
    if (!root || root.__loopNavBound) return;
    root.__loopNavBound = true;
    root.addEventListener("click", function (event) {
      var a = event.target && event.target.closest
        ? event.target.closest("a.loop-tag, a.loop-feed-parent")
        : null;
      if (a) {
        var href = a.getAttribute("href");
        if (href && href.charAt(0) !== "#") {
          event.preventDefault();
          event.stopPropagation();
          try { win.sessionStorage.setItem("loopActiveTab", TAB_LOOP); } catch (err) {}
          (win.location || window.location).assign(href);
          return;
        }
      }
      var tab = event.target && event.target.closest
        ? event.target.closest('[role="tab"]')
        : null;
      if (!tab) return;
      var label = tabLabel(tab);
      if (label === TAB_DAILY || label === TAB_LOOP) {
        try { win.sessionStorage.setItem("loopActiveTab", label); } catch (err) {}
      }
    }, true);
  }
  bindTabsAndSameTab(doc);
  bindTabsAndSameTab(document);
  labelSidebar();
  paintSearch();
  retargetLoopLinks();
  applyTab();
  if (!doc.__loopSidebarLabeled) {
    doc.__loopSidebarLabeled = true;
    var observer = new MutationObserver(function () {
      labelSidebar();
      paintSearch();
      retargetLoopLinks();
      applyTab();
    });
    observer.observe(doc.documentElement, { childList: true, subtree: true });
  }
})();
</script>
"""


def inject_brand_chrome() -> None:
    """Put LOOP CSS in the page markdown and a small st.html appearance script."""
    st.markdown(brand_css(), unsafe_allow_html=True)
    html_fn = getattr(st, "html", None)
    script = brand_theme_script()
    if callable(html_fn):
        try:
            html_fn(script, unsafe_allow_javascript=True)
            return
        except TypeError:
            html_fn(script)
            return
    st.markdown(script, unsafe_allow_html=True)


def ensure_project_root() -> Path:
    """Make ``config/``, ``briefs/``, and ``data/`` resolvable from this file."""
    os.chdir(PROJECT_ROOT)
    return PROJECT_ROOT


def briefs_directory() -> Path:
    return project_path(load_config()["pipeline"]["output_dir"])


def db_path() -> Path:
    return project_path(load_config()["pipeline"]["db_path"])


def list_briefing_dates(briefs_dir: Path | None = None) -> list[str]:
    """Return YYYY-MM-DD dates for briefing files, newest first."""
    directory = briefs_dir if briefs_dir is not None else briefs_directory()
    if not directory.is_dir():
        return []
    dates = []
    for path in directory.iterdir():
        match = BRIEF_NAME.fullmatch(path.name)
        if match and path.is_file() and path.stat().st_size > 0:
            dates.append(match.group(1))
    dates.sort(reverse=True)
    return dates


def latest_briefing_date(briefs_dir: Path | None = None) -> str | None:
    dates = list_briefing_dates(briefs_dir)
    return dates[0] if dates else None


def default_briefing_date(
    dates: list[str],
    today: str | None = None,
    generating: bool = False,
) -> str | None:
    """Today if that file exists (and is not still generating), else the latest."""
    if not dates:
        return None
    current = today if today is not None else today_iso()
    if current in dates and not generating:
        return current
    if generating:
        older = [item for item in dates if item != current]
        if older:
            return older[0]
    return dates[0]


def load_briefing_markdown(date: str, briefs_dir: Path | None = None) -> str | None:
    directory = briefs_dir if briefs_dir is not None else briefs_directory()
    path = directory / f"{date}.md"
    if not path.is_file() or path.stat().st_size == 0:
        return None
    return path.read_text(encoding="utf-8")


def taxonomy_tags(config: dict | None = None) -> list[str]:
    settings = config if config is not None else load_config()
    taxonomy = settings.get("taxonomy") or {}
    return list(taxonomy.keys())


SEARCH_PAGE_SIZE = 20


def active_feed_names(config: dict | None = None) -> list[str]:
    settings = config if config is not None else load_config()
    return list(flatten_feed_urls(settings))


def active_feed_tree(config: dict | None = None) -> list[tuple[str, list[str]]]:
    settings = config if config is not None else load_config()
    return nested_feed_tree(settings)


def active_feed_count(config: dict | None = None) -> int:
    return len(active_feed_names(config))


def parse_tags(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [tag for tag in raw if isinstance(tag, str) and tag]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(parsed, list):
        return [tag for tag in parsed if isinstance(tag, str) and tag]
    return [raw]


def normalize_headline(headline: object) -> str:
    """Collapse whitespace and lowercase so exact headlines group together."""
    return " ".join(str(headline or "").lower().split())


def headline_markdown(headline: object, url: object = None) -> str:
    """Render a heading as a Markdown link, never a bare URL."""
    text = str(headline or "").strip() or "(untitled)"
    href = str(url or "").strip()
    if href:
        return f"### [{text}]({href})"
    return f"### **{text}**"


def headline_html(headline: object, url: object = None) -> str:
    """Same heading with ``target=_blank`` when Streamlit allows HTML."""
    text = html.escape(str(headline or "").strip() or "(untitled)")
    href = str(url or "").strip()
    if href:
        safe = html.escape(href, quote=True)
        return (
            f'<h3 class="loop-story-title">'
            f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{text}</a>'
            f"</h3>"
        )
    return f'<h3 class="loop-story-title">{text}</h3>'


def source_bullet_markdown(source: object, title: object, url: object = None) -> str:
    label = f"{source or 'Unknown source'}: {title or '(untitled)'}"
    href = str(url or "").strip()
    if href:
        return f"- [{label}]({href})"
    return f"- **{label}**"


def humanize_brief_markdown(markdown: str) -> str:
    """User-facing labels and Daily Loop title; internal keys in URLs stay."""
    rewritten = _LOOPING_TITLE.sub("", markdown, count=1)
    rewritten = _BRIEF_INTRO.sub("", rewritten, count=1)
    rewritten = re.sub(
        r"^## Daily Summary(?: & Research Topics)?\s*$",
        "## Daily Summary & Research Topics",
        rewritten,
        flags=re.M,
    )
    for tag in list(TAG_LABELS) + ["Other"]:
        human = humanize_tag(tag)
        rewritten = rewritten.replace(f"## {tag}", f"## {human}")
        escaped = html.escape(tag)
        human_escaped = html.escape(human)
        if escaped != human_escaped:
            rewritten = rewritten.replace(f">{escaped}</a>", f">{human_escaped}</a>")
            rewritten = rewritten.replace(f"#{escaped}", human_escaped)

    def _humanize_heading(match: re.Match[str]) -> str:
        return f"## {humanize_tag(match.group(1))}"

    rewritten = re.sub(r"^## (.+)$", _humanize_heading, rewritten, flags=re.M)
    return rewritten


def rewrite_snapshot_deltas(markdown: str) -> str:
    """Keep snapshot percents on loop-delta classes (green up, red down)."""
    rewritten = _PERCENT_UP_SPAN.sub(
        r'<span class="loop-delta loop-delta-up">\1</span>', markdown
    )
    return _PERCENT_DOWN_SPAN.sub(
        r'<span class="loop-delta loop-delta-down">\1</span>', rewritten
    )


_STACKED_GLANCE = re.compile(
    r"^- (<a\b[^>]*>.*?</a>)\s+(\[[^\]]+\]\([^)]+\))\s*$"
)
_GLANCE_MD_PHRASE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_GLANCE_HTML_LINE = re.compile(r'^<p class="loop-glance-line">.*</p>$')


def _glance_phrase_html(label: str, phrases: list[str]) -> str:
    """One tag as HTML so Streamlit cannot turn it into list markers."""
    links = []
    for phrase in phrases:
        html_link = _GLANCE_MD_PHRASE.sub(
            lambda match: (
                f'<a href="{html.escape(match.group(2), quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">'
                f"{html.escape(match.group(1))}</a>"
            ),
            phrase,
        )
        links.append(html_link)
    return f'<p class="loop-glance-line">{label}: {", ".join(links)}</p>'


def rewrite_glance_rows(markdown: str) -> str:
    """Restore pre-v4.1.2 glance: one wrapping line per italic tag label."""
    lines = markdown.splitlines()
    out: list[str] = []
    in_glance = False
    grouped: list[tuple[str, list[str]]] = []

    def flush() -> None:
        for label, phrases in grouped:
            out.append(_glance_phrase_html(label, phrases))
        grouped.clear()

    def add_phrase(label: str, phrase: str) -> None:
        if grouped and grouped[-1][0] == label:
            grouped[-1][1].append(phrase)
        else:
            grouped.append((label, [phrase]))

    for line in lines:
        stripped = line.strip()
        if stripped == "## At a Glance":
            flush()
            in_glance = True
            out.append(line)
            continue
        if in_glance and (stripped.startswith("## ") or stripped == "---"):
            flush()
            in_glance = False
            out.append(line)
            continue
        if in_glance:
            if _GLANCE_HTML_LINE.match(stripped):
                flush()
                out.append(stripped)
                continue
            stacked = _STACKED_GLANCE.match(stripped)
            if stacked:
                add_phrase(stacked.group(1), stacked.group(2))
                continue
            clustered = _GLANCE_CLUSTER.match(stripped)
            if clustered:
                label, rest = clustered.group(1), clustered.group(2)
                phrases = _GLANCE_MD_PHRASE.findall(rest)
                if phrases:
                    for text, href in phrases:
                        add_phrase(label, f"[{text}]({href})")
                else:
                    add_phrase(label, rest)
                continue
            if not stripped:
                continue
            flush()
            out.append(line)
            continue
        out.append(line)
    flush()
    return "\n".join(out)


def split_daily_brief_sections(markdown: str) -> tuple[str, str, str]:
    """Pull Market Snapshot and At a Glance blocks out of the daily brief."""

    def pull(heading: str, text: str) -> tuple[str, str]:
        lines = text.splitlines()
        start = next(
            (index for index, line in enumerate(lines) if line.strip() == heading),
            None,
        )
        if start is None:
            return "", text
        end = len(lines)
        for index in range(start + 1, len(lines)):
            stripped = lines[index].strip()
            if stripped.startswith("## ") and stripped != heading:
                end = index
                break
            if heading == "## At a Glance" and stripped == "---":
                end = index
                break
        block = "\n".join(lines[start:end]).strip()
        remainder = "\n".join(lines[:start] + lines[end:]).strip()
        return block, remainder

    snapshot, remainder = pull("## Market Snapshot", markdown)
    glance, remainder = pull("## At a Glance", remainder)
    return snapshot, glance, remainder


def rewrite_ask_gemini_topics(markdown: str) -> str:
    """Turn numbered research topics into **Ask Gemini:** labels with Gemini URLs."""
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not _ASK_GEMINI_HEADING.match(lines[i].strip()):
            out.append(lines[i])
            i += 1
            continue
        context_chunks: list[str] = []
        for prior in reversed(out):
            stripped = prior.strip()
            if not stripped:
                if context_chunks:
                    break
                continue
            if stripped.startswith("#") or stripped == "---":
                break
            context_chunks.append(stripped)
        context = " ".join(reversed(context_chunks))
        out.append("**Ask Gemini:**")
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        out.append("")
        while i < len(lines) and not lines[i].startswith("#"):
            stripped = lines[i].strip()
            if not stripped:
                i += 1
                continue
            plain = _PLAIN_NUMBERED_TOPIC.match(stripped)
            if plain:
                out.append(
                    ask_gemini_topic_html(
                        plain.group(2).strip(), context, int(plain.group(1))
                    )
                )
                i += 1
                continue
            html_topic = _NUMBERED_TOPIC_HTML.match(stripped)
            if html_topic:
                href = html.unescape(html_topic.group(2))
                if "google.com/search" in href and "udm=50" in href:
                    out.append(lines[i])
                else:
                    out.append(
                        ask_gemini_topic_html(
                            html.unescape(html_topic.group(3)),
                            context,
                            int(html_topic.group(1)),
                        )
                    )
                i += 1
                continue
            break
    return "\n".join(out)


def display_brief_markdown(markdown: str) -> str:
    """Hyperlink At a Glance / titles to RSS URLs; drop standalone URL lines."""
    markdown = markdown.replace("?loop=1&tag=", "?tag=")
    markdown = markdown.replace("?tag=", "?loop=1&tag=")
    markdown = rewrite_snapshot_deltas(markdown)
    markdown = rewrite_glance_rows(markdown)
    markdown = humanize_brief_markdown(markdown)
    slug_to_url: dict[str, str] = {}
    for match in _ANCHOR_STORY.finditer(markdown):
        slug_to_url[match.group(1)] = match.group(3)
    headline_to_url: dict[str, str] = {}
    for title, url in _MD_HTTP_LINK.findall(markdown):
        headline_to_url[title] = url
        headline_to_url[normalize_headline(title)] = url

    def replace_glance(match: re.Match[str]) -> str:
        prefix, title, slug = match.group(1), match.group(2), match.group(3)
        url = (
            slug_to_url.get(slug)
            or headline_to_url.get(title)
            or headline_to_url.get(normalize_headline(title))
        )
        if url:
            return f"{prefix}[{title}]({url})"
        return match.group(0)

    rewritten = _GLANCE_SLUG_LINK.sub(replace_glance, markdown)
    rewritten = _BARE_URL_LINE.sub("", rewritten)
    return rewrite_ask_gemini_topics(rewritten)


def source_popover_items(rows: list[dict]) -> list[dict]:
    """Unique publisher/title/url rows for an explorer popover."""
    items: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        source = str(row.get("source") or "Unknown source").strip() or "Unknown source"
        title = str(row.get("headline") or "(untitled)").strip() or "(untitled)"
        url = str(row.get("url") or "").strip()
        key = (source, title, url)
        if key in seen:
            continue
        seen.add(key)
        items.append({"source": source, "headline": title, "url": url})
    return items


def group_stories_by_headline(rows: list[dict]) -> list[dict]:
    """Collapse exact RSS headlines (one URL per SQLite row) like write_brief."""
    groups: list[dict] = []
    index: dict[str, int] = {}
    for row_number, row in enumerate(rows):
        key = normalize_headline(row.get("headline"))
        if not key:
            key = f"__row_{row_number}"
        if key in index:
            groups[index[key]]["coverage"].append(row)
            continue
        index[key] = len(groups)
        groups.append(
            {
                "headline": row.get("headline") or "(untitled)",
                "url": str(row.get("url") or "").strip(),
                "published_date": row.get("published_date") or "",
                "source": row.get("source") or "Unknown source",
                "sub_feed": row.get("sub_feed") or "",
                "tags": row.get("tags") or [],
                "ai_summary": row.get("ai_summary") or "",
                "coverage": [row],
            }
        )
    for group in groups:
        group["sources"] = source_popover_items(group["coverage"])
        if not group["url"]:
            for item in group["sources"]:
                if item["url"]:
                    group["url"] = item["url"]
                    break
    return groups


def pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_briefing_generating(lock_path: Path | None = None) -> bool:
    """True when run_daily.sh holds a live lock (or a live run_briefing pid)."""
    path = lock_path if lock_path is not None else LOCK_PATH
    if path.is_file():
        raw = path.read_text(encoding="utf-8").strip()
        if raw.isdigit() and pid_is_running(int(raw)):
            return True
        if raw.isdigit() and not pid_is_running(int(raw)):
            return False
        return True
    return False


def today_iso() -> str:
    return date.today().isoformat()


def generating_banner(today: str) -> str:
    return f"Briefing in progress… Today's briefing ({today}) is generating in the background."


def ready_banner(today: str) -> str:
    return f"Today's briefing ({today}) is ready. Refresh to load it."


def arm_generation_poll(generating: bool) -> None:
    """Reload when a background briefing finishes, without blocking this run."""
    if not generating:
        return
    fragment = getattr(st, "fragment", None)
    if not callable(fragment):
        return

    def _tick() -> None:
        if not is_briefing_generating():
            rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()

    try:
        fragment(run_every=timedelta(seconds=5))(_tick)()
    except TypeError:
        return


@st.cache_resource
def get_connection(db_path_str: str) -> sqlite3.Connection:
    """Reuse one SQLite connection (not pickleable; not ``st.cache_data``)."""
    connection = sqlite3.connect(db_path_str, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


@st.cache_data
def count_stored_articles(db_path_str: str) -> int:
    path = Path(db_path_str)
    if not path.is_file():
        return 0
    connection = get_connection(db_path_str)
    try:
        row = connection.execute("SELECT COUNT(*) AS n FROM stories").fetchone()
    except sqlite3.Error:
        return 0
    return int(row["n"] if row is not None else 0)


@st.cache_data
def unique_sources(db_path_str: str) -> list[str]:
    path = Path(db_path_str)
    if not path.is_file():
        return []
    connection = get_connection(db_path_str)
    try:
        cursor = connection.execute(
            "SELECT DISTINCT source FROM stories "
            "WHERE source IS NOT NULL AND source != '' "
            "ORDER BY source"
        )
    except sqlite3.Error:
        return []
    return [row["source"] for row in cursor.fetchall()]


@st.cache_data
def unique_sub_feeds(db_path_str: str) -> list[str]:
    path = Path(db_path_str)
    if not path.is_file():
        return []
    connection = get_connection(db_path_str)
    try:
        cursor = connection.execute(
            "SELECT DISTINCT sub_feed FROM stories "
            "WHERE sub_feed IS NOT NULL AND sub_feed != '' "
            "ORDER BY sub_feed"
        )
    except sqlite3.Error:
        return []
    return [row["sub_feed"] for row in cursor.fetchall()]


def unique_source_filters(db_path_str: str) -> list[str]:
    """Publishers and sub-feeds so The Loop can filter by parent or child."""
    names: list[str] = []
    seen: set[str] = set()
    for name in unique_sources(db_path_str) + unique_sub_feeds(db_path_str):
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


@st.cache_data
def unique_published_dates(db_path_str: str) -> list[str]:
    path = Path(db_path_str)
    if not path.is_file():
        return []
    connection = get_connection(db_path_str)
    try:
        cursor = connection.execute(
            "SELECT DISTINCT published_date FROM stories "
            "WHERE published_date IS NOT NULL AND published_date != '' "
            "ORDER BY published_date DESC"
        )
    except sqlite3.Error:
        return []
    return [row["published_date"] for row in cursor.fetchall()]


def _query_params(query_params=None):
    params = query_params
    if params is None:
        params = getattr(st, "query_params", None)
        if params is None:
            getter = getattr(st, "experimental_get_query_params", None)
            params = getter() if callable(getter) else {}
    return params


def _query_value(key: str, query_params=None) -> str | None:
    params = _query_params(query_params)
    if params is None:
        return None
    value = None
    if hasattr(params, "get"):
        value = params.get(key)
    elif isinstance(params, dict):
        value = params.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def read_query_tag(query_params=None) -> str | None:
    """Read ``?tag=`` from Streamlit query params, or from an injected mapping."""
    return _query_value("tag", query_params)


def read_query_source(query_params=None) -> str | None:
    """Read ``?source=`` from Streamlit query params for sidebar publishers."""
    return _query_value("source", query_params)


def clear_loop_query_params() -> None:
    """Drop tag/source In Focus params so Back to Search can show the form."""
    params = getattr(st, "query_params", None)
    if params is not None:
        for key in ("tag", "source", "loop"):
            try:
                if hasattr(params, "pop"):
                    params.pop(key, None)
                else:
                    del params[key]
            except Exception:
                continue
        return
    setter = getattr(st, "experimental_set_query_params", None)
    if callable(setter):
        setter()


def stories_for_tag(db_path_str: str, tag: str) -> list[dict]:
    """All loop.db rows whose tags contain ``tag``. Uses bound ``tags LIKE ?``."""
    return search_stories(db_path_str, tag, "", "")


def group_stories_by_date(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """Newest date first; preserve row order within each date."""
    grouped: list[tuple[str, list[dict]]] = []
    index: dict[str, int] = {}
    for row in rows:
        date_value = str(row.get("published_date") or "").strip() or "(unknown date)"
        if date_value in index:
            grouped[index[date_value]][1].append(row)
            continue
        index[date_value] = len(grouped)
        grouped.append((date_value, [row]))
    return grouped


def tag_chips_html(tags: list[str]) -> str:
    """Same colored local chips used in the daily brief (humanized labels)."""
    chips = [tag_hashtag_html(tag) for tag in tags if tag]
    return " ".join(chips)


def _search_filters(
    tag: str,
    source: str,
    query: str,
    year: str = "",
    month: str = "",
    day: str = "",
    include_sub_feed: bool = True,
) -> tuple[str, list[object]]:
    sql = " FROM stories WHERE 1=1"
    params: list[object] = []
    if tag:
        sql += " AND tags LIKE ?"
        params.append(f"%{tag}%")
    if source:
        if include_sub_feed:
            sql += " AND (source = ? OR sub_feed = ?)"
            params.extend([source, source])
        else:
            sql += " AND source = ?"
            params.append(source)
    if query:
        sql += " AND (headline LIKE ? OR ai_summary LIKE ?)"
        like = f"%{query}%"
        params.extend([like, like])
    year = str(year or "").strip()
    month = str(month or "").strip().zfill(2) if str(month or "").strip() else ""
    day = str(day or "").strip().zfill(2) if str(day or "").strip() else ""
    if year and month and day:
        sql += " AND published_date = ?"
        params.append(f"{year}-{month}-{day}")
    elif year and month:
        sql += " AND published_date LIKE ?"
        params.append(f"{year}-{month}-%")
    elif year:
        sql += " AND published_date LIKE ?"
        params.append(f"{year}-%")
    else:
        if month:
            sql += " AND substr(published_date, 6, 2) = ?"
            params.append(month)
        if day:
            sql += " AND substr(published_date, 9, 2) = ?"
            params.append(day)
    return sql, params


def search_stories(
    db_path_str: str,
    tag: str,
    source: str,
    query: str,
    year: str = "",
    month: str = "",
    day: str = "",
) -> list[dict]:
    """Filter stored stories with bound parameters only (no SQL interpolation)."""
    return search_stories_page(
        db_path_str, tag, source, query, year, month, day, page=1, page_size=0
    )["rows"]


def search_stories_page(
    db_path_str: str,
    tag: str,
    source: str,
    query: str,
    year: str = "",
    month: str = "",
    day: str = "",
    page: int = 1,
    page_size: int = SEARCH_PAGE_SIZE,
) -> dict[str, object]:
    """Paginated Loop search: 20 rows plus page / totalPages / totalCount."""
    empty = {"rows": [], "page": 1, "totalPages": 0, "totalCount": 0}
    path = Path(db_path_str)
    if not path.is_file():
        return empty
    connection = get_connection(db_path_str)
    where_sql, params = _search_filters(tag, source, query, year, month, day)
    try:
        count_row = connection.execute(
            "SELECT COUNT(*) AS n" + where_sql, params
        ).fetchone()
    except sqlite3.Error:
        where_sql, params = _search_filters(
            tag, source, query, year, month, day, include_sub_feed=False
        )
        try:
            count_row = connection.execute(
                "SELECT COUNT(*) AS n" + where_sql, params
            ).fetchone()
        except sqlite3.Error:
            return empty
    total_count = int(count_row["n"] if count_row is not None else 0)
    size = int(page_size)
    if size <= 0:
        size = total_count or 1
        total_pages = 1 if total_count else 0
        page_number = 1
        offset = 0
    else:
        total_pages = (total_count + size - 1) // size if total_count else 0
        page_number = max(1, int(page or 1))
        if total_pages:
            page_number = min(page_number, total_pages)
        offset = (page_number - 1) * size
    select_sql = (
        "SELECT published_date, headline, url, source, sub_feed, tags, ai_summary"
        + where_sql
        + " ORDER BY published_date DESC, id DESC LIMIT ? OFFSET ?"
    )
    try:
        cursor = connection.execute(select_sql, [*params, size, offset])
    except sqlite3.Error:
        select_sql = (
            "SELECT published_date, headline, url, source, tags, ai_summary"
            + where_sql
            + " ORDER BY published_date DESC, id DESC LIMIT ? OFFSET ?"
        )
        try:
            cursor = connection.execute(select_sql, [*params, size, offset])
        except sqlite3.Error:
            return empty
    rows = []
    for row in cursor.fetchall():
        source_name = row["source"] or "Unknown source"
        sub_feed = ""
        try:
            sub_feed = row["sub_feed"] or ""
        except (KeyError, IndexError):
            sub_feed = ""
        rows.append(
            {
                "published_date": row["published_date"] or "",
                "headline": row["headline"] or "(untitled)",
                "url": row["url"] or "",
                "source": source_name,
                "sub_feed": sub_feed,
                "tags": parse_tags(row["tags"]),
                "ai_summary": row["ai_summary"] or "",
            }
        )
    return {
        "rows": rows,
        "page": page_number,
        "totalPages": total_pages,
        "totalCount": total_count,
    }


def in_focus_title(tag: str, source: str, query: str, year: str, month: str, day: str) -> str:
    parts: list[str] = []
    if tag:
        parts.append(humanize_tag(tag))
    if source:
        parts.append(source)
    date_parts = [part for part in (year, month, day) if part]
    if date_parts:
        parts.append("-".join(date_parts))
    if query:
        parts.append(f"“{query}”")
    return "In Focus: " + (" · ".join(parts) if parts else "All stories")


def in_focus_heading_html(
    tag: str, source: str, query: str, year: str, month: str, day: str
) -> str:
    """``In Focus: <Tag>`` with only the tag name underlined in its theme color."""
    extras: list[str] = []
    if source:
        extras.append(html.escape(source))
    date_parts = [part for part in (year, month, day) if part]
    if date_parts:
        extras.append(html.escape("-".join(date_parts)))
    if query:
        extras.append(html.escape(f"“{query}”"))
    extra = (" · " + " · ".join(extras)) if extras else ""
    if tag:
        color = html.escape(TAG_COLORS.get(tag, "#334155"), quote=True)
        name = html.escape(humanize_tag(tag))
        return (
            f'<h2 class="loop-in-focus">In Focus: '
            f'<span class="loop-in-focus-tag" style="text-decoration-color:{color}">{name}</span>'
            f"{extra}</h2>"
        )
    label = extra.lstrip(" · ") or "All stories"
    return f'<h2 class="loop-in-focus">In Focus: {label}</h2>'


def static_asset_is_utf8(path: Path) -> bool:
    """Streamlit reads SVG as UTF-8; latin-1 bytes such as 0xb7 crash st.image."""
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def show_static_image(path: Path, **kwargs) -> bool:
    """Show a local image; skip it if the file is missing or not UTF-8 SVG."""
    if not path.is_file():
        return False
    if path.suffix.lower() == ".svg" and not static_asset_is_utf8(path):
        return False
    try:
        st.image(str(path), **kwargs)
    except (UnicodeDecodeError, OSError, ValueError, TypeError):
        return False
    return True


def page_icon_value() -> str:
    for name in (
        "loop-glasses-light.svg",
        "loop-glasses.svg",
        "loop-logo.svg",
    ):
        path = STATIC_DIR / name
        if not path.is_file():
            continue
        if path.suffix.lower() == ".svg" and not static_asset_is_utf8(path):
            continue
        return str(path)
    return "🔁"


def render_brand_header() -> None:
    st.markdown(LOOP_HEADER_HTML, unsafe_allow_html=True)


def render_sidebar(
    path: Path,
    latest: str | None,
    feed_tree: list[tuple[str, list[str]]],
    brief_count: int,
) -> None:
    with st.sidebar:
        st.header("LOOP: AI Market Briefing")
        st.metric("Stored briefings", brief_count)
        st.metric("Latest briefing", latest or "None")
        st.subheader("Active feeds")
        if feed_tree:
            for publisher, children in feed_tree:
                href = html.escape(
                    "/?" + urlencode({"loop": "1", "source": publisher}),
                    quote=True,
                )
                st.markdown(
                    f'<a class="loop-feed-parent" href="{href}" target="_self">'
                    f"{html.escape(publisher)}</a>",
                    unsafe_allow_html=True,
                )
                for child in children:
                    if child != publisher:
                        st.caption(child)
        else:
            st.caption("None configured")
        del path


def render_story_cards(groups: list[dict]) -> None:
    st.caption(f"{len(groups)} matching stor{'y' if len(groups) == 1 else 'ies'}")
    if not groups:
        st.info("No stored articles match those filters.")
        return
    for group in groups:
        with st.container(border=True):
            st.markdown(headline_html(group["headline"], group["url"]), unsafe_allow_html=True)
            source_line = group["source"]
            sub_feed = str(group.get("sub_feed") or "").strip()
            if sub_feed and sub_feed != source_line:
                source_line = f"{source_line} / {sub_feed}"
            st.write(f"**Source:** {source_line}")
            st.write(f"**Date:** {group['published_date']}")
            chips = tag_chips_html(group["tags"])
            if chips:
                st.markdown(chips, unsafe_allow_html=True)
            if group["ai_summary"]:
                st.write(group["ai_summary"])
            coverage = group["sources"]
            if len(coverage) > 1:
                with st.popover(f"🔗 Sources ({len(coverage)})"):
                    for item in coverage:
                        st.markdown(
                            source_bullet_markdown(
                                item["source"], item["headline"], item["url"]
                            )
                        )


def render_daily_loop() -> None:
    today = today_iso()
    generating = is_briefing_generating()
    dates = list_briefing_dates()
    today_exists = today in dates
    if generating:
        st.session_state["was_generating"] = True
        st.info(generating_banner(today))
    elif st.session_state.get("was_generating") and today_exists:
        st.session_state["was_generating"] = False
        st.session_state["awaiting_refresh"] = True
    if st.session_state.get("awaiting_refresh") and today_exists:
        st.success(ready_banner(today))
        if st.button("Refresh", key="loop_refresh_briefing"):
            st.session_state["awaiting_refresh"] = False
            st.session_state["daily_loop_date"] = today
            rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()
    elif st.session_state.get("briefing_just_ready") == today:
        st.session_state.pop("briefing_just_ready", None)
        st.success(ready_banner(today))

    if not dates:
        st.info("No daily briefings found in briefs/. Generate one with the pipeline first.")
        arm_generation_poll(generating)
        return

    hold_latest = generating or bool(st.session_state.get("awaiting_refresh"))
    default = default_briefing_date(dates, today, hold_latest)
    index = dates.index(default) if default in dates else 0
    selected = st.selectbox("Briefing date", dates, index=index, key="daily_loop_date")

    st.header(selected)
    markdown = load_briefing_markdown(selected)
    if markdown is None:
        st.warning(f"Could not read briefs/{selected}.md.")
        arm_generation_poll(generating)
        return
    displayed = display_brief_markdown(markdown)
    snapshot, glance, rest = split_daily_brief_sections(displayed)
    if glance or snapshot:
        left, right = st.columns((2, 1), gap="large")
        with left:
            if glance:
                st.markdown(
                    f'<div class="loop-glance-body">\n\n{glance}\n\n</div>',
                    unsafe_allow_html=True,
                )
        with right:
            if snapshot:
                st.markdown(snapshot, unsafe_allow_html=True)
    if rest.strip():
        st.markdown(rest, unsafe_allow_html=True)
    arm_generation_poll(generating)


def _enter_loop_focus() -> None:
    st.session_state["loop_focus"] = True
    st.session_state["loop_select_tab"] = True


def apply_tag_in_focus(tag: str) -> None:
    """Open The Loop In Focus for one Daily Loop tag: all sources, all dates, empty query."""
    st.session_state["loop_focus"] = True
    st.session_state["loop_select_tab"] = True
    st.session_state["loop_tag"] = tag
    st.session_state["loop_source"] = ""
    st.session_state["loop_year"] = ""
    st.session_state["loop_month"] = ""
    st.session_state["loop_day"] = ""
    st.session_state["loop_query"] = ""
    st.session_state["loop_page"] = 1


def apply_source_in_focus(source: str) -> None:
    """Open The Loop In Focus for one sidebar publisher: all tags, all dates, empty query."""
    st.session_state["loop_focus"] = True
    st.session_state["loop_select_tab"] = True
    st.session_state["loop_tag"] = ""
    st.session_state["loop_source"] = source
    st.session_state["loop_year"] = ""
    st.session_state["loop_month"] = ""
    st.session_state["loop_day"] = ""
    st.session_state["loop_query"] = ""
    st.session_state["loop_page"] = 1


def render_search_page_controls(result: dict[str, object]) -> None:
    page = int(result.get("page") or 1)
    total_pages = int(result.get("totalPages") or 0)
    total_count = int(result.get("totalCount") or 0)
    st.caption(
        f"Page {page} of {total_pages} · {total_count} "
        f"stor{'y' if total_count == 1 else 'ies'}"
    )
    if total_pages <= 1:
        return
    previous, nxt = st.columns(2)
    with previous:
        if page > 1 and st.button("Previous", key=f"loop_prev_{page}"):
            st.session_state["loop_page"] = page - 1
            rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()
    with nxt:
        if page < total_pages and st.button("Next", key=f"loop_next_{page}"):
            st.session_state["loop_page"] = page + 1
            rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()


def render_loop_explorer(path: Path) -> None:
    if not path.is_file():
        st.info(
            "No Loop history database yet. data/loop.db is created when a briefing run appends stories."
        )
        return

    internal_tags = taxonomy_tags()
    tag_options = [""] + internal_tags
    sources = [""] + unique_source_filters(str(path))
    published = unique_published_dates(str(path))
    years = sorted({item[:4] for item in published if len(item) >= 4}, reverse=True)
    months = [f"{index:02d}" for index in range(1, 13)]
    days = [f"{index:02d}" for index in range(1, 32)]

    def tag_label(value: str) -> str:
        return "All tags" if value == "" else humanize_tag(value)

    def source_label(value: str) -> str:
        return "All sources" if value == "" else value

    def blank_label(value: str, empty: str) -> str:
        return empty if value == "" else value

    if st.session_state.get("loop_focus"):
        if st.button("← Back to Search"):
            st.session_state["loop_focus"] = False
            st.session_state["loop_restore_tab"] = True
            clear_loop_query_params()
            rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()
            return
        tag = st.session_state.get("loop_tag") or ""
        source = st.session_state.get("loop_source") or ""
        year = st.session_state.get("loop_year") or ""
        month = st.session_state.get("loop_month") or ""
        day = st.session_state.get("loop_day") or ""
        query = (st.session_state.get("loop_query") or "").strip()
        st.markdown(
            '<div class="loop-in-focus-wrap">'
            + in_focus_heading_html(tag, source, query, year, month, day)
            + "</div>",
            unsafe_allow_html=True,
        )
        page = int(st.session_state.get("loop_page") or 1)
        result = search_stories_page(
            str(path), tag, source, query, year, month, day, page=page
        )
        render_search_page_controls(result)
        render_story_cards(group_stories_by_headline(result["rows"]))
        return

    st.header("The Loop")
    st.caption("Search saved stories")
    with st.form("loop_search_form"):
        st.markdown("**Filters**")
        tag_col, source_col = st.columns(2)
        with tag_col:
            st.selectbox(
                "Tag",
                tag_options,
                format_func=tag_label,
                key="loop_tag",
            )
        with source_col:
            st.selectbox(
                "Source",
                sources,
                format_func=source_label,
                key="loop_source",
            )
        year_options = [""] + years
        month_options = [""] + months
        day_options = [""] + days
        c1, c2, c3 = st.columns(3)
        with c1:
            st.selectbox(
                "Year",
                year_options,
                format_func=lambda value: blank_label(value, "Any year"),
                key="loop_year",
            )
        with c2:
            st.selectbox(
                "Month",
                month_options,
                format_func=lambda value: blank_label(value, "Any month"),
                key="loop_month",
            )
        with c3:
            st.selectbox(
                "Day",
                day_options,
                format_func=lambda value: blank_label(value, "Any day"),
                key="loop_day",
            )
        st.text_input(
            "Keyword",
            key="loop_query",
            placeholder="Search headlines and summaries",
        )
        submitted = st.form_submit_button("Search", type="primary")
    if submitted:
        st.session_state["loop_page"] = 1
        _enter_loop_focus()
        rerun = getattr(st, "rerun", None) or getattr(st, "experimental_rerun", None)
        if callable(rerun):
            rerun()


def render_tag_archive(path: Path, tag: str) -> None:
    """Archive of every stored story with this tag, grouped by date (newest first)."""
    st.markdown(f"## {tag_hashtag_html(tag)}", unsafe_allow_html=True)
    st.caption("Local Loop archive from data/loop.db. Not a public website.")
    st.markdown(f"[Back to Daily Loop]({TAG_ARCHIVE_BASE})")
    if not path.is_file():
        st.info(
            "No Loop history database yet. data/loop.db is created when a briefing run appends stories."
        )
        return
    rows = stories_for_tag(str(path), tag)
    if not rows:
        st.info(f"No stored articles tagged {humanize_tag(tag)}.")
        return
    for date_value, date_rows in group_stories_by_date(rows):
        st.subheader(date_value)
        groups = group_stories_by_headline(date_rows)
        for group in groups:
            st.markdown(headline_html(group["headline"], group["url"]), unsafe_allow_html=True)
            extras = [
                item["source"]
                for item in group["sources"]
                if item["source"] and item["source"] != group["source"]
            ]
            if extras:
                st.caption(f"also covered by [{', '.join(extras)}]")
            chips = tag_chips_html(group["tags"])
            if chips:
                st.markdown(chips, unsafe_allow_html=True)


def main() -> None:
    ensure_project_root()
    st.set_page_config(
        page_title="LOOP: AI Market Briefing",
        page_icon=page_icon_value(),
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inject_brand_chrome()
    render_brand_header()
    path = db_path()
    dates = list_briefing_dates()
    render_sidebar(path, dates[0] if dates else None, active_feed_tree(), len(dates))
    requested = read_query_tag()
    requested_source = read_query_source()
    if requested and not st.session_state.get("loop_focus"):
        apply_tag_in_focus(requested)
    elif requested_source and not st.session_state.get("loop_focus"):
        apply_source_in_focus(requested_source)
    restore_loop_tab = bool(
        st.session_state.pop("loop_restore_tab", False)
        or st.session_state.pop("loop_select_tab", False)
    )
    if restore_loop_tab:
        st.markdown(
            '<div data-loop-select-tab="The Loop" hidden></div>',
            unsafe_allow_html=True,
        )
    daily_tab, explorer_tab = st.tabs([TAB_DAILY, TAB_LOOP])
    with daily_tab:
        render_daily_loop()
    with explorer_tab:
        render_loop_explorer(path)


if __name__ == "__main__":
    main()
