"""
harness/yfinance_tool.py — yfinance fundamentals + price context for agent enrichment.

Pulls snapshot fundamentals, analyst targets, and recent earnings for a set of
tickers.  When no tickers are specified, reads the most recent trending tickers
from trending-tickers-unified.db.

Citation format: [YF:{ticker}:{field}:{date}]

CLI:
    python -m harness.yfinance_tool AAPL TSLA NVDA
    python -m harness.yfinance_tool --trending          # top tickers from DB
    python -m harness.yfinance_tool --trending --top 10
"""

from __future__ import annotations

import re
import sqlite3
import sys
from datetime import date, datetime
from typing import Any

from harness.config import DATA_DIR

DB_PATH  = DATA_DIR / "trending-tickers-unified.db"
_TODAY   = date.today().isoformat()

# Fields pulled from yf.Ticker.info
_INFO_FIELDS = [
    "shortName", "sector", "industry",
    "currentPrice", "previousClose",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "marketCap", "beta",
    "trailingPE", "forwardPE",
    "trailingEps", "forwardEps",
    "totalRevenue", "revenueGrowth", "grossMargins", "operatingMargins",
    "recommendationMean", "numberOfAnalystOpinions",
    "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "shortRatio", "dividendYield",
]

# --------------------------------------------------------------------------- #
# DB helpers                                                                   #
# --------------------------------------------------------------------------- #

def _trending_tickers(top: int = 25) -> list[str]:
    if not DB_PATH.exists():
        return []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                """
                SELECT ticker FROM ohlcv
                GROUP BY ticker
                ORDER BY MAX(date) DESC, COUNT(*) DESC
                LIMIT ?
                """,
                (top,),
            ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []


def _extract_tickers_from_query(query: str) -> list[str]:
    """Pull explicit ticker mentions (1-5 uppercase letters) from query text."""
    candidates = re.findall(r'\b([A-Z]{1,5})\b', query)
    # filter obvious non-tickers
    _STOPWORDS = {"I", "A", "AN", "THE", "AND", "OR", "FOR", "IN", "IS",
                  "OF", "ON", "AT", "TO", "BE", "IF", "US", "GDP", "CPI",
                  "FED", "SEC", "ETF", "CEO", "IPO", "YOY", "QOQ", "TTM"}
    return [t for t in candidates if t not in _STOPWORDS]

# --------------------------------------------------------------------------- #
# Fetch                                                                        #
# --------------------------------------------------------------------------- #

def _fetch_ticker(sym: str) -> dict[str, Any]:
    import yfinance as yf
    t    = yf.Ticker(sym)
    info = t.info or {}

    result: dict[str, Any] = {"symbol": sym}
    for f in _INFO_FIELDS:
        result[f] = info.get(f)

    # upcoming / recent earnings
    try:
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            now = datetime.now()
            future = ed[ed.index > now]
            past   = ed[ed.index <= now]
            if not future.empty:
                result["next_earnings"] = future.index[-1].strftime("%Y-%m-%d")
            if not past.empty:
                result["last_earnings"] = past.index[0].strftime("%Y-%m-%d")
                eps_actual   = past.iloc[0].get("Reported EPS")
                eps_estimate = past.iloc[0].get("EPS Estimate")
                if eps_actual is not None:
                    result["last_eps_actual"]   = float(eps_actual)
                if eps_estimate is not None:
                    result["last_eps_estimate"] = float(eps_estimate)
    except Exception:
        pass

    # recent news headlines (top 3)
    try:
        news = t.news or []
        result["recent_headlines"] = [
            n.get("content", {}).get("title") or n.get("title", "")
            for n in news[:3]
        ]
    except Exception:
        result["recent_headlines"] = []

    return result

# --------------------------------------------------------------------------- #
# Formatting                                                                   #
# --------------------------------------------------------------------------- #

def _fmt_mcap(v: float | None) -> str:
    if v is None:
        return "n/a"
    if v >= 1e12:
        return f"${v/1e12:.2f}T"
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    if v >= 1e6:
        return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"


def _fmt_pct(v: float | None) -> str:
    return f"{v*100:+.1f}%" if v is not None else "n/a"


def _fmt_f(v: float | None, fmt: str = ".2f") -> str:
    return f"{v:{fmt}}" if v is not None else "n/a"


def _ticker_block(d: dict) -> list[str]:
    sym   = d["symbol"]
    name  = d.get("shortName") or sym
    price = d.get("currentPrice")
    ref   = f"[YF:{sym}:snapshot:{_TODAY}]"

    lines: list[str] = [f"### {ref} {name} ({sym})"]

    # sector / industry
    sec = d.get("sector") or ""
    ind = d.get("industry") or ""
    if sec or ind:
        lines.append(f"**Sector/Industry**: {sec} / {ind}")

    # price + range
    hi52 = d.get("fiftyTwoWeekHigh")
    lo52 = d.get("fiftyTwoWeekLow")
    rng  = f"  52w: ${_fmt_f(lo52)} – ${_fmt_f(hi52)}" if hi52 else ""
    lines.append(f"**Price**: ${_fmt_f(price)}{rng}")

    # valuation
    pe_t = _fmt_f(d.get("trailingPE"))
    pe_f = _fmt_f(d.get("forwardPE"))
    eps  = _fmt_f(d.get("trailingEps"))
    mcap = _fmt_mcap(d.get("marketCap"))
    beta = _fmt_f(d.get("beta"))
    lines.append(f"**Valuation**: P/E={pe_t} (fwd {pe_f})  EPS={eps}  MCap={mcap}  β={beta}")

    # growth / margins
    rev  = _fmt_mcap(d.get("totalRevenue"))
    revg = _fmt_pct(d.get("revenueGrowth"))
    gm   = _fmt_pct(d.get("grossMargins"))
    om   = _fmt_pct(d.get("operatingMargins"))
    lines.append(f"**Financials**: Revenue={rev} ({revg} YoY)  GrossMargin={gm}  OpMargin={om}")

    # analyst consensus
    rec  = d.get("recommendationMean")
    na   = d.get("numberOfAnalystOpinions") or 0
    tgt  = _fmt_f(d.get("targetMeanPrice"))
    thi  = _fmt_f(d.get("targetHighPrice"))
    tlo  = _fmt_f(d.get("targetLowPrice"))
    if rec is not None:
        rec_label = {1: "Strong Buy", 2: "Buy", 3: "Hold", 4: "Sell", 5: "Strong Sell"}.get(round(rec), f"{rec:.1f}")
        upside = ""
        if price and d.get("targetMeanPrice"):
            upside = f"  ({(d['targetMeanPrice']/price - 1)*100:+.1f}% upside)"
        lines.append(
            f"**Analysts** ({na}): {rec_label}  Target=${tlo}–${thi} mean=${tgt}{upside}"
        )

    # short interest
    sr = d.get("shortRatio")
    if sr is not None:
        lines.append(f"**Short ratio**: {_fmt_f(sr)} days to cover")

    # earnings
    ne = d.get("next_earnings")
    le = d.get("last_earnings")
    if ne:
        lines.append(f"**Next earnings**: {ne}")
    if le:
        act = _fmt_f(d.get("last_eps_actual"))
        est = _fmt_f(d.get("last_eps_estimate"))
        lines.append(f"**Last earnings** ({le}): actual EPS={act}  estimate={est}")

    # headlines
    headlines = [h for h in d.get("recent_headlines", []) if h]
    if headlines:
        lines.append("**Recent news**:")
        for h in headlines:
            lines.append(f"  - {h}")

    return lines


def format_tickers_context(tickers: list[str], verbose: bool = False) -> str:
    if not tickers:
        return ""
    lines: list[str] = [f"## Equity Fundamentals (yfinance, {_TODAY})\n"]
    errors: list[str] = []

    for sym in tickers:
        try:
            d = _fetch_ticker(sym)
            if d.get("currentPrice") is None and d.get("shortName") is None:
                errors.append(sym)
                continue
            lines.extend(_ticker_block(d))
            lines.append("")
        except Exception as e:
            errors.append(f"{sym}({e})")

    if errors:
        lines.append(f"*Fetch failed: {', '.join(errors)}*")

    return "\n".join(lines)

# --------------------------------------------------------------------------- #
# Agent entry point                                                            #
# --------------------------------------------------------------------------- #

def query_yfinance(query: str, tickers: list[str] | None = None, top: int = 10) -> str:
    """
    Main entry point for agent enrichment.
    If tickers is None, extracts from query text then falls back to trending DB.
    """
    resolved = tickers or _extract_tickers_from_query(query)
    if not resolved:
        resolved = _trending_tickers(top)
    if not resolved:
        return ""
    # cap at top to avoid token explosion
    resolved = resolved[:top]
    return format_tickers_context(resolved)


def _has_equity_intent(query: str) -> bool:
    explicit = bool(_extract_tickers_from_query(query))
    keywords = {"stock", "equity", "ticker", "shares", "fundamental",
                "earnings", "valuation", "analyst", "pe ratio", "eps",
                "revenue", "margin", "buy", "sell", "short", "position"}
    tokens = set(query.lower().split())
    return explicit or bool(tokens & keywords)

# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="yfinance_tool")
    parser.add_argument("tickers", nargs="*", help="Ticker symbols")
    parser.add_argument("--trending", action="store_true", help="Use tickers from trending DB")
    parser.add_argument("--top", type=int, default=10, help="Max tickers (default 10)")
    args = parser.parse_args()

    if args.trending or not args.tickers:
        syms = _trending_tickers(args.top)
        if not syms:
            print("No tickers found in DB.", file=sys.stderr)
            sys.exit(1)
        print(f"Using {len(syms)} trending tickers: {', '.join(syms)}\n")
    else:
        syms = [t.upper() for t in args.tickers][: args.top]

    print(format_tickers_context(syms))
