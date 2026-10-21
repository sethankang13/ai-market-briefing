"""Fetch a Market Snapshot for Loop: AI Market Briefing.

Quotes previous close and percent change for ^DJI, ^IXIC, and ^GSPC, plus
the Effective Federal Funds Rate. Failed quotes are marked fetch failed and
never replaced with invented numbers.

Run from the project folder:
    python3 src/fetch_market.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any


USER_AGENT = "Loop-AI-Market-Briefing/0.1"
EFFR_URL = "https://markets.newyorkfed.org/api/rates/unsecured/effr/last.json"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

INDEXES = (
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"),
    ("^DJI", "Dow"),
)


def _get_bytes(url: str, timeout: int = 15) -> bytes:
    """GET one URL. Isolated so tests can mock it."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2_000_000)


def _failed(reason: str) -> dict[str, Any]:
    return {"status": "fetch failed", "error": reason}


def fetch_fed_funds() -> dict[str, Any]:
    """Return the latest Effective Federal Funds Rate, or an explicit failure."""
    try:
        data = json.loads(_get_bytes(EFFR_URL).decode("utf-8"))
        rows = data.get("refRates") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            return _failed("NY Fed response had no refRates")
        row = rows[0]
        rate = row.get("percentRate")
        if rate is None:
            return _failed("NY Fed response had no percentRate")
        return {
            "status": "ok",
            "rate": float(rate),
            "as_of": row.get("effectiveDate"),
        }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError, KeyError) as error:
        return _failed(str(error) or error.__class__.__name__)


def _closes_from_chart(result: dict[str, Any]) -> list[float]:
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    raw = quote.get("close") or []
    return [float(value) for value in raw if isinstance(value, (int, float))]


def fetch_index_quote(symbol: str, name: str) -> dict[str, Any]:
    """Return previous close and session percent change, or an explicit failure."""
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
        previous_close: float | None = None
        percent_change: float | None = None
        if len(closes) >= 2:
            previous_close = closes[-1]
            prior = closes[-2]
            if prior:
                percent_change = (previous_close - prior) / prior * 100.0
        if previous_close is None:
            last = meta.get("regularMarketPrice")
            prior = meta.get("previousClose") or meta.get("chartPreviousClose")
            if isinstance(last, (int, float)) and isinstance(prior, (int, float)) and prior:
                previous_close = float(last)
                percent_change = (float(last) - float(prior)) / float(prior) * 100.0
            elif isinstance(prior, (int, float)):
                previous_close = float(prior)
                change_pct = meta.get("regularMarketChangePercent")
                if isinstance(change_pct, (int, float)):
                    percent_change = float(change_pct)
        if previous_close is None or percent_change is None:
            return _failed("Yahoo chart did not include previous close and percent change")
        return {
            "status": "ok",
            "symbol": symbol,
            "name": name,
            "previous_close": previous_close,
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


def format_fed_funds(entry: dict[str, Any]) -> str:
    if entry.get("status") != "ok":
        return "fetch failed"
    return f"{entry['rate']:.2f}%"


def format_index(entry: dict[str, Any]) -> str:
    if entry.get("status") != "ok":
        return "fetch failed"
    close = entry["previous_close"]
    close_text = f"{close:,.2f}"
    return f"{close_text} ({format_percent(entry['percent_change'])})"


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
        lines.append(f"- {label}: {format_index(entry)}")
    return "\n".join(lines)


if __name__ == "__main__":
    snapshot = fetch_market_snapshot()
    print(render_market_block(snapshot))
    print(json.dumps(snapshot, indent=2))
