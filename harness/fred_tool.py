"""
harness.fred_tool — Federal Reserve Economic Data (FRED) integration.

Fetches live series, releases, and search results from the FRED API.
Returns markdown blocks ready to inject into synthesis context as cited sources.

Citation IDs follow the pattern: [FRED:{series_id}:{date}]
so downstream citation validation can resolve every claim back to a specific
observation date and series.

API key is read from FRED_API_KEY in the environment / .env file.

Usage (standalone smoke-test):
    python -m harness.fred_tool "unemployment rate"
    python -m harness.fred_tool --series UNRATE --start 2024-01-01
    python -m harness.fred_tool --release "Consumer Price Index"
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BASE = "https://api.stlouisfed.org/fred"

_API_KEY: str = ""


def _key() -> str:
    global _API_KEY
    if _API_KEY:
        return _API_KEY
    # Config loads .env into os.environ on import
    try:
        from harness.config import ROOT as _ROOT
        _env = _ROOT / ".env"
        if _env.exists():
            for line in _env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip() == "FRED_API_KEY":
                        _API_KEY = v.strip()
                        return _API_KEY
    except Exception:
        pass
    _API_KEY = os.environ.get("FRED_API_KEY", "")
    return _API_KEY


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

_TIMEOUT      = 15   # seconds per request
_MAX_RETRIES  = 4    # attempts on 429
_RETRY_BASE   = 3.0  # seconds (doubles each retry: 3, 6, 12)
_MIN_INTERVAL = 0.7  # minimum seconds between any two FRED HTTP calls (~1.4 req/s)

_last_req_t: float = 0.0  # module-level timestamp of last completed request


def _get(endpoint: str, params: dict[str, Any]) -> dict:
    global _last_req_t
    key = _key()
    if not key:
        raise RuntimeError(
            "FRED_API_KEY not set — add it to your .env file as FRED_API_KEY=<your_key>"
        )
    params = {**params, "api_key": key, "file_type": "json"}
    url = f"{_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"

    # Enforce minimum inter-request interval before every call
    elapsed = time.monotonic() - _last_req_t
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)

    for attempt in range(_MAX_RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            _last_req_t = time.monotonic()
            return result
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < _MAX_RETRIES - 1:
                wait = _RETRY_BASE * (2 ** attempt)
                print(
                    f"  [fred] 429 — retry {attempt + 1}/{_MAX_RETRIES - 1} in {wait:.0f}s",
                    file=sys.stderr,
                )
                time.sleep(wait)
                _last_req_t = time.monotonic()
                continue
            body = e.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"FRED HTTP {e.code} for {endpoint}: {body}") from e
    raise RuntimeError(f"FRED {endpoint}: exhausted retries")


# ---------------------------------------------------------------------------
# Series data
# ---------------------------------------------------------------------------

# Curated catalogue of high-value series for finance/econ/trading use cases.
# Grouped by theme so query_fred() can do intent-based routing.
_SERIES_CATALOGUE: dict[str, list[tuple[str, str]]] = {
    "inflation": [
        ("CPIAUCSL",   "CPI All Urban Consumers (SA, monthly)"),
        ("CPILFESL",   "Core CPI ex Food & Energy (SA, monthly)"),
        ("PCEPI",      "PCE Price Index (SA, monthly)"),
        ("PCEPILFE",   "Core PCE Price Index (SA, monthly)"),
        ("T10YIE",     "10-Year Breakeven Inflation Rate (daily)"),
        ("T5YIE",      "5-Year Breakeven Inflation Rate (daily)"),
    ],
    "rates": [
        ("FEDFUNDS",   "Effective Federal Funds Rate (monthly)"),
        ("DFEDTARU",   "Fed Funds Target Rate Upper Bound (daily)"),
        ("DFEDTARL",   "Fed Funds Target Rate Lower Bound (daily)"),
        ("DFF",        "Federal Funds Rate (daily)"),
        ("SOFR",       "Secured Overnight Financing Rate (daily)"),
        ("TB3MS",      "3-Month Treasury Bill Rate (monthly)"),
        ("DGS2",       "2-Year Treasury Yield (daily)"),
        ("DGS10",      "10-Year Treasury Yield (daily)"),
        ("DGS30",      "30-Year Treasury Yield (daily)"),
        ("T10Y2Y",     "10Y-2Y Treasury Spread (daily)"),
        ("T10Y3M",     "10Y-3M Treasury Spread (daily)"),
    ],
    "labor": [
        ("UNRATE",     "Unemployment Rate (SA, monthly)"),
        ("U6RATE",     "U-6 Total Unemployed + Marginally Attached (monthly)"),
        ("PAYEMS",     "Total Nonfarm Payrolls (SA, monthly, thousands)"),
        ("ICSA",       "Initial Jobless Claims (weekly, seasonally adjusted)"),
        ("LNS12300060","Employment-Population Ratio 25-54 (monthly)"),
        ("JOLTS",      "Job Openings: Total (SA, monthly, thousands)"),
        ("JTSJOL",     "Job Openings: Total Nonfarm (SA, monthly, thousands)"),
        ("AHETPI",     "Average Hourly Earnings: Total Private (SA, monthly)"),
    ],
    "growth": [
        ("GDP",        "Gross Domestic Product (SA annual rate, quarterly, billions)"),
        ("GDPC1",      "Real GDP (SA annual rate, quarterly, billions chained 2017$)"),
        ("A191RL1Q225SBEA", "Real GDP Growth Rate (quarterly, %)"),
        ("GDI",        "Gross Domestic Income (SA annual rate, quarterly)"),
        ("INDPRO",     "Industrial Production Index (SA, monthly)"),
        ("TCU",        "Capacity Utilization: Total Industry (SA, monthly, %)"),
    ],
    "credit": [
        ("DRCCLACBS",  "Credit Card Delinquency Rate (SA, quarterly, %)"),
        ("DRSFRMACBS", "Single-Family Mortgage Delinquency Rate (SA, quarterly, %)"),
        ("CONSUMER",   "Consumer Loans at Commercial Banks (SA, weekly, billions)"),
        ("TOTALSL",    "Total Consumer Credit Outstanding (SA, monthly, billions)"),
        ("BUSLOANS",   "Commercial & Industrial Loans (SA, weekly, billions)"),
        ("DPCREDIT",   "Discount Window Borrowing (weekly, millions)"),
    ],
    "housing": [
        ("HOUST",      "Housing Starts: Total (SA annual rate, monthly, thousands)"),
        ("MORTGAGE30US","30-Year Fixed Mortgage Rate (weekly, %)"),
        ("CSUSHPINSA", "Case-Shiller Home Price Index (NSA, monthly)"),
        ("MSPUS",      "Median Sales Price of Houses Sold (quarterly, $)"),
        ("EVACANTUSQ176N", "Rental Vacancy Rate (quarterly, %)"),
    ],
    "money": [
        ("M2SL",       "M2 Money Supply (SA, monthly, billions)"),
        ("WALCL",      "Fed Balance Sheet: Total Assets (weekly, millions)"),
        ("WRESBAL",    "Reserve Balances with Federal Reserve Banks (weekly)"),
        ("RRPONTSYD",  "Overnight Reverse Repo Facility (daily, billions)"),
    ],
    "sentiment": [
        ("UMCSENT",    "U. of Michigan Consumer Sentiment (monthly)"),
        ("BSCICP03USM665S", "OECD Business Confidence Index - US (monthly)"),
        ("CSCICP03USM665S", "OECD Consumer Confidence Index - US (monthly)"),
    ],
    "global": [
        ("DEXUSEU",    "USD/EUR Exchange Rate (daily)"),
        ("DEXJPUS",    "JPY/USD Exchange Rate (daily)"),
        ("DEXUSUK",    "USD/GBP Exchange Rate (daily)"),
        ("DEXCHUS",    "CNY/USD Exchange Rate (daily)"),
        ("DCOILWTICO", "WTI Crude Oil Price (daily, $/barrel)"),
        ("GOLDAMGBD228NLBM", "Gold Price: London AM Fix (daily, USD/troy oz)"),
    ],
}

# Flat reverse map: series_id → (theme, description)
_SERIES_META: dict[str, tuple[str, str]] = {
    sid: (theme, desc)
    for theme, series in _SERIES_CATALOGUE.items()
    for sid, desc in series
}

# Intent keywords → themes
_INTENT_MAP: dict[str, list[str]] = {
    "inflation":    ["inflation"],
    "cpi":          ["inflation"],
    "pce":          ["inflation"],
    "price":        ["inflation"],
    "breakeven":    ["inflation", "rates"],
    "interest rate":["rates"],
    "fed funds":    ["rates"],
    "treasury":     ["rates"],
    "yield":        ["rates"],
    "spread":       ["rates"],
    "curve":        ["rates"],
    "sofr":         ["rates"],
    "employment":   ["labor"],
    "labor":        ["labor"],
    "jobs":         ["labor"],
    "payroll":      ["labor"],
    "unemployment": ["labor"],
    "wages":        ["labor"],
    "hiring":       ["labor"],
    "gdp":          ["growth"],
    "growth":       ["growth"],
    "recession":    ["growth", "rates"],
    "industrial":   ["growth"],
    "capacity":     ["growth"],
    "credit":       ["credit"],
    "loan":         ["credit"],
    "delinquency":  ["credit"],
    "mortgage":     ["housing", "credit"],
    "housing":      ["housing"],
    "home":         ["housing"],
    "rent":         ["housing"],
    "money supply": ["money"],
    "m2":           ["money"],
    "balance sheet":["money"],
    "repo":         ["money"],
    "sentiment":    ["sentiment"],
    "confidence":   ["sentiment"],
    "consumer":     ["sentiment", "credit"],
    "dollar":       ["global"],
    "exchange":     ["global"],
    "oil":          ["global"],
    "gold":         ["global"],
    "currency":     ["global"],
}


def _themes_for_query(query: str) -> list[str]:
    q = query.lower()
    seen: set[str] = set()
    themes: list[str] = []
    for kw, ts in _INTENT_MAP.items():
        if kw in q:
            for t in ts:
                if t not in seen:
                    seen.add(t)
                    themes.append(t)
    return themes


def get_series(
    series_id: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 24,
) -> dict:
    """
    Fetch observations for a single FRED series.

    Returns:
        {
          "series_id":   "UNRATE",
          "title":       "Unemployment Rate",
          "units":       "Percent",
          "frequency":   "Monthly",
          "seasonal":    "Seasonally Adjusted",
          "last_updated":"2026-05-01",
          "observations":[{"date": "2026-03-01", "value": "4.2"}, ...]
        }
    """
    # Fetch series info
    info = _get("series", {"series_id": series_id})
    s = info.get("seriess", [{}])[0]

    # Fetch observations
    obs_params: dict[str, Any] = {
        "series_id":     series_id,
        "sort_order":    "desc",
        "limit":         limit,
    }
    if start:
        obs_params["observation_start"] = start
    if end:
        obs_params["observation_end"] = end

    obs_data = _get("series/observations", obs_params)
    obs = [
        {"date": o["date"], "value": o["value"]}
        for o in obs_data.get("observations", [])
        if o.get("value") != "."
    ]
    obs.reverse()   # chronological order

    return {
        "series_id":   series_id,
        "title":       s.get("title", ""),
        "units":       s.get("units", ""),
        "frequency":   s.get("frequency", ""),
        "seasonal":    s.get("seasonal_adjustment", ""),
        "last_updated":s.get("last_updated", "")[:10],
        "observations":obs,
    }


def search_series(query: str, limit: int = 8) -> list[dict]:
    """Search FRED series by keyword. Returns list of series metadata dicts."""
    data = _get("series/search", {
        "search_text": query,
        "limit":       limit,
        "order_by":    "popularity",
        "sort_order":  "desc",
    })
    return [
        {
            "series_id":   s.get("id", ""),
            "title":       s.get("title", ""),
            "units":       s.get("units", ""),
            "frequency":   s.get("frequency", ""),
            "seasonal":    s.get("seasonal_adjustment", ""),
            "last_updated":s.get("last_updated", "")[:10],
            "popularity":  s.get("popularity", 0),
        }
        for s in data.get("seriess", [])
    ]


def get_release(release_name: str, limit: int = 5) -> list[dict]:
    """
    Search FRED releases by name and return the most recent release dates
    for the top match.
    """
    data = _get("releases", {"limit": 100})
    releases = data.get("releases", [])
    rn = release_name.lower()
    matches = [r for r in releases if rn in r.get("name", "").lower()]
    if not matches:
        return []
    top = matches[0]
    rid = top["id"]
    dates_data = _get("release/dates", {
        "release_id":      rid,
        "limit":           limit,
        "sort_order":      "desc",
        "include_release_dates_with_no_data": "false",
    })
    return [
        {
            "release_id":   rid,
            "release_name": top.get("name", ""),
            "date":         d.get("date", ""),
        }
        for d in dates_data.get("release_dates", [])
    ]


# ---------------------------------------------------------------------------
# Context formatting — output ready to inject into synthesis prompt
# ---------------------------------------------------------------------------

_MAX_OBS_IN_CONTEXT = 12   # observations to include per series


def _fmt_series(s: dict) -> str:
    """Format a single series result as a cited markdown block."""
    sid    = s["series_id"]
    title  = s["title"]
    units  = s["units"]
    freq   = s["frequency"]
    sa     = s["seasonal"]
    upd    = s["last_updated"]
    obs    = s["observations"][-_MAX_OBS_IN_CONTEXT:]

    lines = [
        f"**[FRED:{sid}:{upd}]** {title}",
        f"*{units} | {freq} | {sa} | last updated {upd}*",
        "",
    ]

    if obs:
        # Compact table
        lines.append("| Date | Value |")
        lines.append("|------|-------|")
        for o in obs:
            lines.append(f"| {o['date']} | {o['value']} |")

    # Inline summary stats
    vals = []
    for o in obs:
        try:
            vals.append(float(o["value"]))
        except ValueError:
            pass
    if vals:
        latest = vals[-1]
        prior  = vals[-2] if len(vals) >= 2 else None
        chg    = f"{latest - prior:+.2f}" if prior is not None else "n/a"
        yoy    = None
        if len(vals) >= 12:
            yoy = f"{latest - vals[-12]:+.2f}"
        elif len(vals) >= 4:
            yoy = f"{latest - vals[0]:+.2f} ({len(vals)}-period change)"
        summary_parts = [f"Latest: {latest}"]
        if prior is not None:
            summary_parts.append(f"Δ prev: {chg}")
        if yoy:
            summary_parts.append(f"YoY/period: {yoy}")
        lines.append("")
        lines.append("  ".join(summary_parts))

    return "\n".join(lines)


def _fmt_block(series_list: list[dict], query: str, retrieved_at: str) -> str:
    header = [
        "### FRED Economic Data",
        f"*Retrieved: {retrieved_at} | Query: \"{query}\"*",
        "*Cite as [FRED:{series_id}:{last_updated}] — all data via St. Louis Fed FRED API*",
        "",
    ]
    body = []
    for s in series_list:
        body.append(_fmt_series(s))
        body.append("")
    return "\n".join(header + body).strip()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def query_fred(
    query: str,
    series_ids: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    obs_limit: int = 24,
    max_series: int = 6,
) -> str:
    """
    Fetch FRED data relevant to *query* and return a formatted markdown block
    ready to inject into synthesis context.

    If *series_ids* is given, those series are fetched directly.
    Otherwise, intent routing selects series from the curated catalogue.

    Returns empty string if FRED_API_KEY is missing or all fetches fail.
    """
    if not _key():
        print("  [fred] FRED_API_KEY not configured — skipping", file=sys.stderr)
        return ""

    retrieved_at = datetime.now(UTC).strftime("%Y-%m-%d")

    # Determine which series to fetch
    if series_ids:
        targets = series_ids[:max_series]
    else:
        themes = _themes_for_query(query)
        seen: set[str] = set()
        targets: list[str] = []
        for theme in themes:
            for sid, _ in _SERIES_CATALOGUE.get(theme, []):
                if sid not in seen:
                    seen.add(sid)
                    targets.append(sid)
                if len(targets) >= max_series:
                    break
            if len(targets) >= max_series:
                break

    if not targets:
        return ""

    print(f"  [fred] fetching {len(targets)} series: {targets}")

    results: list[dict] = []
    for sid in targets:
        try:
            data = get_series(sid, start=start, end=end, limit=obs_limit)
            if data.get("observations"):
                results.append(data)
        except Exception as exc:
            print(f"  [fred] {sid} failed: {exc}", file=sys.stderr)

    if not results:
        return ""

    return _fmt_block(results, query, retrieved_at)


# ---------------------------------------------------------------------------
# Catalogue helpers (used by API routes)
# ---------------------------------------------------------------------------

def catalogue_themes() -> list[str]:
    return list(_SERIES_CATALOGUE.keys())


def catalogue_series(theme: str | None = None) -> list[dict]:
    if theme:
        return [
            {"series_id": sid, "description": desc, "theme": theme}
            for sid, desc in _SERIES_CATALOGUE.get(theme, [])
        ]
    return [
        {"series_id": sid, "description": desc, "theme": t}
        for t, series in _SERIES_CATALOGUE.items()
        for sid, desc in series
    ]


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="FRED tool smoke-test")
    ap.add_argument("query",        nargs="*", help="Natural-language query for intent routing")
    ap.add_argument("--series",     nargs="+", help="Fetch specific series IDs directly")
    ap.add_argument("--start",      default=None, help="Observation start date (YYYY-MM-DD)")
    ap.add_argument("--end",        default=None, help="Observation end date (YYYY-MM-DD)")
    ap.add_argument("--search",     default=None, help="Search FRED series by keyword")
    ap.add_argument("--release",    default=None, help="Look up release dates by name")
    ap.add_argument("--catalogue",  action="store_true", help="Print curated series catalogue")
    ap.add_argument("--max-series", type=int, default=4)
    args = ap.parse_args()

    if args.catalogue:
        for theme, series in _SERIES_CATALOGUE.items():
            print(f"\n[{theme.upper()}]")
            for sid, desc in series:
                print(f"  {sid:<30} {desc}")
        sys.exit(0)

    if args.search:
        hits = search_series(args.search)
        for h in hits:
            print(f"  {h['series_id']:<25} {h['title']}  ({h['frequency']}, pop={h['popularity']})")
        sys.exit(0)

    if args.release:
        dates = get_release(args.release)
        for d in dates:
            print(f"  [{d['release_name']}] {d['date']}")
        sys.exit(0)

    query = " ".join(args.query) if args.query else (
        " ".join(args.series) if args.series else "inflation and interest rates"
    )
    result = query_fred(
        query,
        series_ids=args.series,
        start=args.start,
        end=args.end,
        max_series=args.max_series,
    )
    print(result if result else "[no results — check FRED_API_KEY]")
