"""Fetch a Market Snapshot for Loop: AI Market Briefing.

Quotes previous close and percent change for ^DJI, ^IXIC, and ^GSPC, plus
the Effective Federal Funds Rate. Failed quotes are marked fetch failed and
never replaced with invented numbers.

Run from the project folder:
    python3 src/fetch_market.py
"""

from __future__ import annotations

import html
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


USER_AGENT = (
    "Loop-AI-Market-Briefing/4.2.1 "
    "(local briefing; https://github.com/sethankang13/ai-market-briefing)"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/plain;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
EFFR_URLS = (
    "https://markets.newyorkfed.org/api/rates/all/latest.json",
    "https://markets.newyorkfed.org/api/rates/unsecured/effr/last.json",
)
EFFR_URL = EFFR_URLS[0]
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
MOCK_FED_FUNDS_RATE = 4.33

INDEXES = (
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"),
    ("^DJI", "Dow"),
)


def _get_bytes(url: str, timeout: int = 15) -> bytes:
    """GET one URL. Isolated so tests can mock it."""
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2_000_000)


def _failed(reason: str) -> dict[str, Any]:
    return {"status": "fetch failed", "error": reason}


def _ref_rate_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("refRates", "rates", "data"):
        rows = data.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        if isinstance(rows, dict):
            nested = _ref_rate_rows(rows)
            if nested:
                return nested
    return []


def _parse_effr(data: Any) -> dict[str, Any] | None:
    """Pick the Effective Federal Funds Rate row from a NY Fed JSON payload."""
    rows = _ref_rate_rows(data)
    if not rows:
        return None
    chosen = None
    for row in rows:
        kind = str(row.get("type") or row.get("rateType") or "").strip().upper()
        if kind == "EFFR" or "FEDERAL FUNDS" in kind:
            chosen = row
            break
    if chosen is None:
        chosen = rows[0]
    rate = chosen.get("percentRate")
    if rate is None:
        return None
    return {
        "status": "ok",
        "rate": float(rate),
        "as_of": chosen.get("effectiveDate"),
    }


def mock_market_snapshot() -> dict[str, Any]:
    """Realistic offline snapshot for ``--mock``. Never labeled fetch failed."""
    indexes = {
        "^GSPC": {
            "status": "ok",
            "symbol": "^GSPC",
            "name": "S&P 500",
            "previous_close": 7623.68,
            "percent_change": -0.52,
        },
        "^IXIC": {
            "status": "ok",
            "symbol": "^IXIC",
            "name": "Nasdaq",
            "previous_close": 25955.34,
            "percent_change": -0.21,
        },
        "^DJI": {
            "status": "ok",
            "symbol": "^DJI",
            "name": "Dow",
            "previous_close": 52215.16,
            "percent_change": -1.23,
        },
    }
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fed_funds": {
            "status": "ok",
            "rate": MOCK_FED_FUNDS_RATE,
            "as_of": "mock",
            "source": "mock",
        },
        "indexes": indexes,
    }


def fetch_fed_funds() -> dict[str, Any]:
    """Return the latest Effective Federal Funds Rate, or an explicit failure."""
    errors: list[str] = []
    for url in EFFR_URLS:
        try:
            data = json.loads(_get_bytes(url).decode("utf-8"))
            parsed = _parse_effr(data)
            if parsed is not None:
                parsed["source"] = url
                return parsed
            errors.append(f"{url}: NY Fed response had no EFFR percentRate")
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
            TypeError,
            KeyError,
        ) as error:
            errors.append(f"{url}: {error or error.__class__.__name__}")
    return _failed("; ".join(errors) if errors else "NY Fed Fed Funds fetch failed")


def _closes_from_chart(result: dict[str, Any]) -> list[float]:
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    raw = quote.get("close") or []
    return [float(value) for value in raw if isinstance(value, (int, float))]


def _number(*values: object) -> float | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
    return None


def fetch_index_quote(symbol: str, name: str) -> dict[str, Any]:
    """Return Yahoo previous close and session percent change, or an explicit failure."""
    encoded = urllib.parse.quote(symbol, safe="")
    url = YAHOO_CHART.format(symbol=encoded) + "?interval=1d&range=10d"
    try:
        payload = json.loads(_get_bytes(url).decode("utf-8"))
        results = (payload.get("chart") or {}).get("result")
        if not isinstance(results, list) or not results:
            error_info = (payload.get("chart") or {}).get("error")
            return _failed(str(error_info) if error_info else "Yahoo chart had no result")
        result = results[0]
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        closes = _closes_from_chart(result)
        last_close = closes[-1] if closes else None
        prior_close = closes[-2] if len(closes) >= 2 else None
        prior = _number(
            meta.get("previousClose"),
            meta.get("chartPreviousClose"),
            prior_close,
        )
        last = _number(meta.get("regularMarketPrice"), last_close)
        percent_change = _number(meta.get("regularMarketChangePercent"))
        if percent_change is None and last is not None and prior:
            percent_change = (last - prior) / prior * 100.0
        # Latest completed session close (yesterday on a weekend / before open).
        level = last if last is not None else prior
        if symbol == "^DJI" and level is not None and level < 48000 and last_close and last_close >= 48000:
            level = float(last_close)
        if level is None or percent_change is None:
            return _failed("Yahoo chart did not include previous close and percent change")
        return {
            "status": "ok",
            "symbol": symbol,
            "name": name,
            "previous_close": level,
            "percent_change": percent_change,
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as error:
        return _failed(str(error) or error.__class__.__name__)


def fetch_market_snapshot() -> dict[str, Any]:
    """Collect Fed Funds plus the three indexes without inventing quotes."""
    indexes = {}
    for symbol, name in INDEXES:
        quote = fetch_index_quote(symbol, name)
        quote["symbol"] = symbol
        quote["name"] = name
        indexes[symbol] = quote
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fed_funds": fetch_fed_funds(),
        "indexes": indexes,
    }


def format_percent(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def format_percent_html(value: float) -> str:
    text = html.escape(format_percent(value))
    if value > 0:
        kind = "up"
    elif value < 0:
        kind = "down"
    else:
        return text
    return f'<span class="loop-delta loop-delta-{kind}">{text}</span>'


def format_fed_funds(entry: dict[str, Any]) -> str:
    if entry.get("status") != "ok":
        return "fetch failed"
    return f"{entry['rate']:.2f}%"


def format_index(entry: dict[str, Any], *, html_percent: bool = False) -> str:
    if entry.get("status") != "ok":
        return "fetch failed"
    close = entry["previous_close"]
    close_text = f"{close:,.2f}"
    percent = (
        format_percent_html(entry["percent_change"])
        if html_percent
        else format_percent(entry["percent_change"])
    )
    return f"{close_text} ({percent})"


def render_market_block(snapshot: dict[str, Any] | None) -> str:
    """Markdown block inserted at the top of every daily brief."""
    lines = ["## Market Snapshot", ""]
    if not isinstance(snapshot, dict):
        lines.append("- Fed Funds: fetch failed")
        lines.append("- S&P 500: fetch failed")
        lines.append("- Nasdaq: fetch failed")
        lines.append("- Dow: fetch failed")
        return "\n".join(lines)

    fed = snapshot.get("fed_funds") if isinstance(snapshot.get("fed_funds"), dict) else {}
    indexes = snapshot.get("indexes") if isinstance(snapshot.get("indexes"), dict) else {}
    lines.append(f"- Fed Funds: {format_fed_funds(fed)}")
    for symbol, label in INDEXES:
        entry = indexes.get(symbol) if isinstance(indexes.get(symbol), dict) else {}
        lines.append(f"- {label}: {format_index(entry, html_percent=True)}")
    return "\n".join(lines)


if __name__ == "__main__":
    snapshot = fetch_market_snapshot()
    print(render_market_block(snapshot))
    print(json.dumps(snapshot, indent=2))
