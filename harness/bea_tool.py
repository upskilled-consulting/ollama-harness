"""
harness.bea_tool — Bureau of Economic Analysis (BEA) API integration.

Fetches regional income, GDP, price parities, national accounts, trade data,
and industry GDP from the BEA API. Returns markdown blocks ready for context
injection with citation IDs.

Citation format: [BEA:{dataset}:{table}:{geo}:{period}]
  e.g. [BEA:Regional:SAGDP9N:STATE:2024]
       [BEA:NIPA:T10101:US:2025Q1]

API key: BEA_API_KEY in .env

Datasets covered:
  NIPA         — national GDP components, personal income (monthly/quarterly)
  Regional     — real GDP and personal income by state/county/MSA (1929→)
  GDPbyIndustry — value added and gross output by industry
  ITA          — international trade balance (goods, services)

Usage (standalone):
    python -m harness.bea_tool "regional gdp growth"
    python -m harness.bea_tool --query "state personal income" --geo NY,CA,TX
    python -m harness.bea_tool --catalogue
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Config / HTTP
# ---------------------------------------------------------------------------

_BASE    = "https://apps.bea.gov/api/data"

def _yr(n: int) -> str:
    """Return the last N calendar years as a comma-separated string (e.g. '2021,2022,2023,2024,2025')."""
    cur = date.today().year
    return ",".join(str(y) for y in range(cur - n + 1, cur + 1))
_TIMEOUT = 20
_API_KEY: str = ""


def _key() -> str:
    global _API_KEY
    if _API_KEY:
        return _API_KEY
    try:
        from harness.config import ROOT as _ROOT
        env = _ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip() == "BEA_API_KEY":
                        _API_KEY = v.strip()
                        return _API_KEY
    except Exception:
        pass
    _API_KEY = os.environ.get("BEA_API_KEY", "")
    return _API_KEY


def _get(params: dict[str, Any]) -> dict:
    key = _key()
    if not key:
        raise RuntimeError("BEA_API_KEY not set — add it to .env as BEA_API_KEY=<your_key>")
    full = {"UserID": key, "method": "GetData", "ResultFormat": "JSON", **params}
    url = f"{_BASE}?{urllib.parse.urlencode(full)}"
    try:
        with urllib.request.urlopen(url, timeout=_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"BEA HTTP {e.code}: {body}") from e

    results = raw.get("BEAAPI", {}).get("Results", {})
    # Some datasets (e.g. GDPbyIndustry with multiple periods) wrap Results in a list
    if isinstance(results, list):
        results = results[0] if results else {}
    # Propagate API-level errors
    err = results.get("Error")
    if err:
        code = err.get("APIErrorCode", "?")
        desc = err.get("APIErrorDescription", "")
        raise RuntimeError(f"BEA API error {code}: {desc}")
    return results


def _to_float(val: str, unit_mult: str) -> float | None:
    """Convert BEA DataValue string + UNIT_MULT exponent to a Python float."""
    try:
        v = float(str(val).replace(",", ""))
        exp = int(unit_mult) if unit_mult else 0
        return v * (10 ** exp)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Curated query catalogue
# ---------------------------------------------------------------------------

# Each entry: {dataset, params, description, geo_label, value_label}
_CATALOGUE: dict[str, dict[str, Any]] = {
    # National accounts
    "gdp_components": {
        "dataset":     "NIPA",
        "params":      {"TableName": "T10101", "Frequency": "Q,A", "Year": _yr(5)},
        "description": "GDP and components — % change (quarterly/annual)",
        "geo_label":   "US",
        "value_label": "% change",
        "nipa_lines":  {1, 2, 3, 4, 5, 6, 8, 14, 15, 22},
    },
    "personal_income_monthly": {
        "dataset":     "NIPA",
        "params":      {"TableName": "T20600", "Frequency": "M", "Year": _yr(2)},
        "description": "Personal income and components (monthly, billions $)",
        "geo_label":   "US",
        "value_label": "billions $",
        "nipa_lines":  {1, 2, 3, 7, 8, 9, 10},
    },

    # Real GDP by state
    "gdp_by_state": {
        "dataset":     "Regional",
        "params":      {"TableName": "SAGDP9N", "LineCode": "1", "GeoFips": "STATE", "Year": _yr(5)},
        "description": "Real GDP by state, chained 2017$ (annual)",
        "geo_label":   "STATE",
        "value_label": "millions $",
    },
    "gdp_by_state_pct_change": {
        "dataset":     "Regional",
        "params":      {"TableName": "SAGDP11N", "LineCode": "1", "GeoFips": "STATE", "Year": _yr(5)},
        "description": "Real GDP growth rate by state, % change (annual)",
        "geo_label":   "STATE",
        "value_label": "% change",
    },
    "gdp_by_state_quarterly": {
        "dataset":     "Regional",
        "params":      {"TableName": "SQGDP9", "LineCode": "1", "GeoFips": "STATE", "Year": _yr(3)},
        "description": "Real GDP by state, quarterly (chained 2017$)",
        "geo_label":   "STATE",
        "value_label": "millions $",
    },

    # Personal income by state
    "personal_income_by_state": {
        "dataset":     "Regional",
        "params":      {"TableName": "SAINC1", "LineCode": "1", "GeoFips": "STATE", "Year": _yr(5)},
        "description": "Personal income by state (annual, thousands $)",
        "geo_label":   "STATE",
        "value_label": "thousands $",
    },
    "per_capita_income_by_state": {
        "dataset":     "Regional",
        "params":      {"TableName": "SAINC1", "LineCode": "3", "GeoFips": "STATE", "Year": _yr(5)},
        "description": "Per capita personal income by state (annual, $)",
        "geo_label":   "STATE",
        "value_label": "$",
    },
    "personal_income_by_state_quarterly": {
        "dataset":     "Regional",
        "params":      {"TableName": "SQINC1", "LineCode": "1", "GeoFips": "STATE", "Year": _yr(3)},
        "description": "Personal income by state (quarterly, thousands $)",
        "geo_label":   "STATE",
        "value_label": "thousands $",
    },

    # Regional price parities and PCE
    "regional_price_parities": {
        "dataset":     "Regional",
        "params":      {"TableName": "SARPP", "LineCode": "1", "GeoFips": "STATE", "Year": _yr(5)},
        "description": "Regional price parities by state (US=100)",
        "geo_label":   "STATE",
        "value_label": "index (US=100)",
    },
    "pce_by_state": {
        "dataset":     "Regional",
        "params":      {"TableName": "SAPCE1", "LineCode": "1", "GeoFips": "STATE", "Year": _yr(5)},
        "description": "Personal consumption expenditures by state (annual, millions $)",
        "geo_label":   "STATE",
        "value_label": "millions $",
    },

    # County data
    "county_personal_income": {
        "dataset":     "Regional",
        "params":      {"TableName": "CAINC1", "LineCode": "1", "GeoFips": "COUNTY", "Year": _yr(3)},
        "description": "Personal income by county (annual, thousands $)",
        "geo_label":   "COUNTY",
        "value_label": "thousands $",
        "_max_geo":    50,
    },
    "county_per_capita_income": {
        "dataset":     "Regional",
        "params":      {"TableName": "CAINC1", "LineCode": "3", "GeoFips": "COUNTY", "Year": _yr(3)},
        "description": "Per capita personal income by county (annual, $)",
        "geo_label":   "COUNTY",
        "value_label": "$",
        "_max_geo":    50,
    },

    # GDP by industry
    "gdp_by_industry": {
        "dataset":     "GDPbyIndustry",
        "params":      {"TableID": "1", "Frequency": "A", "Year": _yr(5), "Industry": "ALL"},
        "description": "Value added by industry — annual (millions $)",
        "geo_label":   "US",
        "value_label": "millions $",
    },
    "gdp_by_industry_quarterly": {
        "dataset":     "GDPbyIndustry",
        "params":      {"TableID": "1", "Frequency": "Q", "Year": _yr(3), "Industry": "ALL"},
        "description": "Value added by industry — quarterly (millions $)",
        "geo_label":   "US",
        "value_label": "millions $",
    },

    # International trade
    "trade_balance_goods": {
        "dataset":     "ITA",
        "params":      {"Indicator": "BalGds", "AreaOrCountry": "AllCountries",
                        "Frequency": "QSA", "Year": _yr(5)},
        "description": "Balance on goods (quarterly SA, millions $)",
        "geo_label":   "AllCountries",
        "value_label": "millions $",
    },
    "trade_balance_services": {
        "dataset":     "ITA",
        "params":      {"Indicator": "BalSrvs", "AreaOrCountry": "AllCountries",
                        "Frequency": "QSA", "Year": _yr(5)},
        "description": "Balance on services (quarterly SA, millions $)",
        "geo_label":   "AllCountries",
        "value_label": "millions $",
    },
    "trade_balance_total": {
        "dataset":     "ITA",
        "params":      {"Indicator": "BalGdsSrvs", "AreaOrCountry": "AllCountries",
                        "Frequency": "QSA", "Year": _yr(5)},
        "description": "Balance on goods and services (quarterly SA, millions $)",
        "geo_label":   "AllCountries",
        "value_label": "millions $",
    },
}

# ---------------------------------------------------------------------------
# Intent routing
# ---------------------------------------------------------------------------

_INTENT_MAP: dict[str, list[str]] = {
    "gdp":                     ["gdp_components", "gdp_by_state"],
    "gross domestic product":  ["gdp_components", "gdp_by_state"],
    "national gdp":            ["gdp_components"],
    "gdp growth":              ["gdp_components", "gdp_by_state_pct_change"],
    "state gdp":               ["gdp_by_state", "gdp_by_state_pct_change"],
    "regional gdp":            ["gdp_by_state", "gdp_by_state_pct_change"],
    "county gdp":              ["county_personal_income", "county_per_capita_income"],
    "personal income":         ["personal_income_by_state", "per_capita_income_by_state"],
    "state income":            ["personal_income_by_state", "per_capita_income_by_state"],
    "per capita income":       ["per_capita_income_by_state"],
    "county income":           ["county_personal_income", "county_per_capita_income"],
    "regional income":         ["personal_income_by_state", "per_capita_income_by_state"],
    "price parity":            ["regional_price_parities"],
    "regional price":          ["regional_price_parities"],
    "cost of living":          ["regional_price_parities"],
    "pce":                     ["pce_by_state", "personal_income_monthly"],
    "consumption":             ["pce_by_state"],
    "consumer spending":       ["pce_by_state", "personal_income_monthly"],
    "industry":                ["gdp_by_industry"],
    "value added":             ["gdp_by_industry"],
    "sector":                  ["gdp_by_industry"],
    "trade":                   ["trade_balance_goods", "trade_balance_services"],
    "trade balance":           ["trade_balance_total", "trade_balance_goods"],
    "trade deficit":           ["trade_balance_total", "trade_balance_goods"],
    "goods trade":             ["trade_balance_goods"],
    "services trade":          ["trade_balance_services"],
    "bea":                     ["gdp_components", "gdp_by_state"],
    "regional economy":        ["gdp_by_state", "personal_income_by_state", "regional_price_parities"],
    "state economy":           ["gdp_by_state", "personal_income_by_state"],
    "quarterly gdp":           ["gdp_by_state_quarterly", "gdp_components"],
}


def _themes_for_query(query: str) -> list[str]:
    q = query.lower()
    seen: set[str] = set()
    keys: list[str] = []
    for kw, ks in _INTENT_MAP.items():
        if kw in q:
            for k in ks:
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
    return keys


# ---------------------------------------------------------------------------
# Response parsers (one per dataset family)
# ---------------------------------------------------------------------------

def _parse_regional(data: list[dict], catalogue_entry: dict) -> list[dict]:
    """Parse Regional dataset rows into {geo, period, value} dicts."""
    rows = []
    for d in data:
        geo   = d.get("GeoName", "")
        fips  = d.get("GeoFips", "")
        period = d.get("TimePeriod", "")
        raw   = d.get("DataValue", "")
        mult  = d.get("UNIT_MULT", "0")
        if raw in ("", "(D)", "(NA)"):
            continue
        val = _to_float(raw, mult)
        if val is None:
            continue
        rows.append({"geo": geo, "fips": fips, "period": period, "value": val})
    return rows


def _parse_nipa(data: list[dict], catalogue_entry: dict) -> list[dict]:
    """Parse NIPA rows, optionally filtering to curated line numbers."""
    allowed = catalogue_entry.get("nipa_lines")
    rows = []
    for d in data:
        line_no = d.get("LineNumber", "")
        try:
            if allowed and int(line_no) not in allowed:
                continue
        except (ValueError, TypeError):
            pass
        line_desc  = d.get("LineDescription", d.get("SeriesCode", ""))
        period     = d.get("TimePeriod", "")
        raw        = d.get("DataValue", "")
        mult       = d.get("UNIT_MULT", "0")
        if raw in ("", "(D)", "(NA)"):
            continue
        val = _to_float(raw, mult)
        if val is None:
            continue
        rows.append({"line": line_desc, "period": period, "value": val})
    return rows


def _parse_gdp_by_industry(data: list[dict]) -> list[dict]:
    """Parse GDPbyIndustry rows."""
    rows = []
    for d in data:
        industry = d.get("IndustrYDescription", d.get("IndustryDescription", d.get("Industry", "")))
        period   = d.get("TimePeriod", "")
        raw      = d.get("DataValue", "")
        mult     = d.get("UNIT_MULT", "0")
        if raw in ("", "(D)", "(NA)"):
            continue
        val = _to_float(raw, mult)
        if val is None:
            continue
        rows.append({"industry": industry, "period": period, "value": val})
    return rows


def _parse_ita(data: list[dict]) -> list[dict]:
    """Parse ITA (international transactions) rows."""
    rows = []
    for d in data:
        period = d.get("TimePeriod", "")
        raw    = d.get("DataValue", "")
        mult   = d.get("UNIT_MULT", "0")
        if raw in ("", "(D)", "(NA)"):
            continue
        val = _to_float(raw, mult)
        if val is None:
            continue
        rows.append({"period": period, "value": val})
    return rows


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_num(v: float, label: str = "") -> str:
    """Human-readable number with optional unit suffix."""
    if "%" in label:
        return f"{v:+.2f}%"
    abs_v = abs(v)
    sign  = "-" if v < 0 else ""
    if abs_v >= 1e12:
        return f"{sign}{abs_v/1e12:.2f}T"
    if abs_v >= 1e9:
        return f"{sign}{abs_v/1e9:.2f}B"
    if abs_v >= 1e6:
        return f"{sign}{abs_v/1e6:.2f}M"
    if abs_v >= 1e3:
        return f"{sign}{abs_v/1e3:.1f}K"
    return f"{v:.2f}"


def _fmt_regional_block(rows: list[dict], entry: dict, citation_key: str) -> str:
    """Format state/county rows: show latest year, top 10 + bottom 5 + US total."""
    if not rows:
        return ""

    periods = sorted({r["period"] for r in rows}, reverse=True)
    latest  = periods[0]
    prior   = periods[1] if len(periods) > 1 else None

    latest_rows = [r for r in rows if r["period"] == latest]
    prior_dict  = {r["geo"]: r["value"] for r in rows if r["period"] == prior} if prior else {}

    # Separate US total from states/counties
    us_total = next((r for r in latest_rows if r["fips"] in ("00000", "US")), None)
    geo_rows = [r for r in latest_rows if r["fips"] not in ("00000", "US")]
    geo_rows.sort(key=lambda r: r["value"], reverse=True)

    dataset   = entry["params"].get("TableName", citation_key)
    val_label = entry["value_label"]
    citation  = f"[BEA:Regional:{dataset}:STATE:{latest}]"

    lines = [
        f"**{citation}** {entry['description']}",
        f"*{val_label} | latest: {latest}*",
        "",
    ]

    def row_str(r: dict) -> str:
        v   = r["value"]
        chg = ""
        if r["geo"] in prior_dict:
            delta = v - prior_dict[r["geo"]]
            pct   = (delta / prior_dict[r["geo"]] * 100) if prior_dict[r["geo"]] else 0
            chg   = f" ({pct:+.1f}% YoY)"
        return f"| {r['geo']:<30} | {_fmt_num(v, val_label):>12} |{chg}"

    lines.append(f"| {'Geography':<30} | {'Value':>12} |")
    lines.append(f"|{'-'*31}|{'-'*13}|")

    if us_total:
        lines.append(row_str(us_total) + "  ← US total")

    for r in geo_rows[:10]:
        lines.append(row_str(r))

    if len(geo_rows) > 15:
        lines.append(f"| ... ({len(geo_rows) - 10} more)        |              |")
        lines.append("*Bottom 5:*")
        for r in geo_rows[-5:]:
            lines.append(row_str(r))

    return "\n".join(lines)


def _fmt_nipa_block(rows: list[dict], entry: dict) -> str:
    """Format NIPA rows as a pivoted time-series table."""
    if not rows:
        return ""

    lines_seen = list(dict.fromkeys(r["line"] for r in rows))
    periods    = sorted({r["period"] for r in rows}, reverse=True)[:8]
    periods_r  = list(reversed(periods))

    dataset = entry["params"].get("TableName", "NIPA")
    citation = f"[BEA:NIPA:{dataset}:US:{periods[0]}]"
    val_label = entry["value_label"]

    header = [
        f"**{citation}** {entry['description']}",
        f"*{val_label} | periods: {periods_r[0]} → {periods_r[-1]}*",
        "",
    ]

    # Build lookup
    lookup: dict[str, dict[str, float]] = {}
    for r in rows:
        lookup.setdefault(r["line"], {})[r["period"]] = r["value"]

    col_w = max(len(p) for p in periods_r) + 2
    header_row = "| {:<45} |".format("Line") + "".join(f" {p:>{col_w}} |" for p in periods_r)
    sep_row    = "|" + "-" * 47 + "|" + (("-" * (col_w + 2) + "|") * len(periods_r))

    table = [header_row, sep_row]
    for line in lines_seen:
        row_vals = lookup.get(line, {})
        cells = ""
        for p in periods_r:
            v = row_vals.get(p)
            if v is None:
                cells += f" {'':>{col_w}} |"
            else:
                cells += f" {_fmt_num(v, val_label):>{col_w}} |"
        table.append(f"| {line[:45]:<45} |{cells}")

    return "\n".join(header + table)


def _fmt_gdp_industry_block(rows: list[dict], entry: dict) -> str:
    """Format GDP-by-industry: show latest period, top 15 industries."""
    if not rows:
        return ""

    periods    = sorted({r["period"] for r in rows}, reverse=True)
    latest     = periods[0]
    latest_rows = sorted(
        [r for r in rows if r["period"] == latest],
        key=lambda r: r["value"], reverse=True
    )

    citation = f"[BEA:GDPbyIndustry:1:US:{latest}]"
    val_label = entry["value_label"]

    lines = [
        f"**{citation}** {entry['description']}",
        f"*{val_label} | latest: {latest}*",
        "",
        f"| {'Industry':<45} | {'Value':>12} |",
        "|" + "-" * 47 + "|" + "-" * 14 + "|",
    ]
    for r in latest_rows[:15]:
        lines.append(f"| {r['industry'][:45]:<45} | {_fmt_num(r['value'], val_label):>12} |")

    return "\n".join(lines)


def _fmt_ita_block(rows: list[dict], entry: dict) -> str:
    """Format ITA trade balance as time series."""
    if not rows:
        return ""

    rows_sorted = sorted(rows, key=lambda r: r["period"])[-12:]
    indicator   = entry["params"].get("Indicator", "")
    latest      = rows_sorted[-1]["period"] if rows_sorted else "?"
    citation    = f"[BEA:ITA:{indicator}:AllCountries:{latest}]"
    val_label   = entry["value_label"]

    lines = [
        f"**{citation}** {entry['description']}",
        f"*{val_label}*",
        "",
        f"| {'Period':<10} | {'Value':>12} |",
        "|" + "-" * 12 + "|" + "-" * 14 + "|",
    ]
    for r in rows_sorted:
        lines.append(f"| {r['period']:<10} | {_fmt_num(r['value'], val_label):>12} |")

    vals = [r["value"] for r in rows_sorted]
    if len(vals) >= 2:
        chg = vals[-1] - vals[-2]
        lines.append(f"\nLatest: {_fmt_num(vals[-1], val_label)}  Δ prev qtr: {_fmt_num(chg, val_label)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def query_bea(
    query: str,
    catalogue_keys: list[str] | None = None,
    geo_filter: list[str] | None = None,
    max_queries: int = 3,
) -> str:
    """
    Fetch BEA data relevant to *query* and return a formatted markdown block.

    Args:
        query:         Natural-language query for intent routing.
        catalogue_keys: Override intent routing with specific catalogue keys.
        geo_filter:    State abbreviations or FIPS codes to filter Regional data.
        max_queries:   Cap on number of BEA queries to execute.

    Returns empty string if BEA_API_KEY is missing or all fetches fail.
    """
    if not _key():
        print("  [bea] BEA_API_KEY not configured — skipping", file=sys.stderr)
        return ""

    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    targets = catalogue_keys or _themes_for_query(query)
    if not targets:
        return ""
    targets = list(dict.fromkeys(targets))[:max_queries]

    print(f"  [bea] fetching {len(targets)} query/queries: {targets}")

    blocks: list[str] = []

    for key in targets:
        entry = _CATALOGUE.get(key)
        if not entry:
            continue

        dataset = entry["dataset"]
        params  = {**entry["params"], "DatasetName": dataset}

        try:
            results = _get(params)
        except RuntimeError as e:
            print(f"  [bea] {key}: {e}", file=sys.stderr)
            continue

        # GDPbyIndustry nests data inside results["GDPbyIndustry"][n]["Data"]
        if dataset == "GDPbyIndustry":
            gdpi_list = results.get("GDPbyIndustry", [])
            data = []
            for item in (gdpi_list if isinstance(gdpi_list, list) else []):
                if isinstance(item, dict):
                    data.extend(item.get("Data", []))
            if not data:
                data = results.get("Data", [])
        else:
            data = results.get("Data", [])
        if not data:
            continue

        # Limit county data to avoid context explosion
        max_geo = entry.get("_max_geo")
        if max_geo and len(data) > max_geo * 10:
            # Keep only the most recent period
            periods = sorted({d.get("TimePeriod", "") for d in data}, reverse=True)
            latest  = periods[0] if periods else ""
            data    = [d for d in data if d.get("TimePeriod") == latest]

        try:
            if dataset == "Regional":
                parsed = _parse_regional(data, entry)
                block  = _fmt_regional_block(parsed, entry, key)
            elif dataset == "NIPA":
                parsed = _parse_nipa(data, entry)
                block  = _fmt_nipa_block(parsed, entry)
            elif dataset == "GDPbyIndustry":
                parsed = _parse_gdp_by_industry(data)
                block  = _fmt_gdp_industry_block(parsed, entry)
            elif dataset == "ITA":
                parsed = _parse_ita(data)
                block  = _fmt_ita_block(parsed, entry)
            else:
                continue

            if block:
                blocks.append(block)
        except Exception as exc:
            print(f"  [bea] format error for {key}: {exc}", file=sys.stderr)

    if not blocks:
        return ""

    header = [
        "### BEA Economic Data",
        f"*Retrieved: {retrieved_at} | Query: \"{query}\"*",
        f"*Cite as [BEA:{{dataset}}:{{table}}:{{geo}}:{{period}}] — all data via BEA API*",
        "",
    ]
    return "\n".join(header) + "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Catalogue helpers
# ---------------------------------------------------------------------------

def catalogue_keys() -> list[str]:
    return list(_CATALOGUE.keys())


def catalogue_entry(key: str) -> dict | None:
    return _CATALOGUE.get(key)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="BEA tool smoke-test")
    ap.add_argument("query",       nargs="*",    help="Natural-language query for intent routing")
    ap.add_argument("--keys",      nargs="+",    help="Fetch specific catalogue keys directly")
    ap.add_argument("--catalogue", action="store_true", help="Print catalogue")
    ap.add_argument("--max",       type=int, default=3, help="Max queries (default: 3)")
    args = ap.parse_args()

    if args.catalogue:
        for k, v in _CATALOGUE.items():
            print(f"  {k:<35} {v['description']}")
        sys.exit(0)

    query = " ".join(args.query) if args.query else (
        " ".join(args.keys) if args.keys else "regional gdp and state income"
    )
    result = query_bea(query, catalogue_keys=args.keys, max_queries=args.max)
    print(result if result else "[no results — check BEA_API_KEY]")
