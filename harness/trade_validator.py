"""
harness/trade_validator.py -Deterministic TA validation for trading thesis outputs.

Parses [THESIS:...] citations and structured fields from a thesis file,
loads the latest signal row per ticker from the signals DB, and applies
rule-based checks to produce a per-thesis PASS/WARN/FLAG report.

No LLM involved -all checks are pure Python.

CLI:
    python -m harness.trade_validator path/to/thesis.md
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.config import DATA_DIR

_DB_PATH = DATA_DIR / "trending-tickers-unified.db"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Thesis:
    n:            int
    direction:    str          # "long" | "short"
    ticker:       str          # uppercase symbol
    conviction:   str          # "high" | "medium" | "low"
    entry:        float | None
    target:       float | None
    stop:         float | None
    position_pct: float | None  # % of portfolio, e.g. 8.0
    stated_price: float | None = None  # "Current Price" the model wrote into the thesis


@dataclass
class Check:
    name:   str
    status: str    # "PASS" | "WARN" | "FLAG" | "N/A"
    detail: str


@dataclass
class ThesisValidation:
    thesis: Thesis
    checks: list[Check] = field(default_factory=list)

    @property
    def overall(self) -> str:
        if any(c.status == "FLAG" for c in self.checks):
            return "FLAG"
        if any(c.status == "WARN" for c in self.checks):
            return "WARN"
        return "PASS"

    @property
    def flag_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "FLAG")

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "WARN")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_THESIS_CITATION = re.compile(
    r"\[THESIS:(?P<direction>long|short):(?P<ticker>[A-Z]{1,6}):[^\]]+\]",
    re.IGNORECASE,
)
_HEADER_RE = re.compile(r"^##\s+Thesis\s+(\d+):", re.MULTILINE)

_FIELD = {
    "direction":    re.compile(r"\*\*Direction\*\*:\s*(Long|Short)", re.IGNORECASE),
    "ticker":       re.compile(r"\*\*Ticker\*\*:\s*([A-Z]{1,6})\b"),
    "conviction":   re.compile(r"\*\*Conviction\*\*:\s*(High|Medium|Low)", re.IGNORECASE),
    "entry":        re.compile(r"\*\*Entry\*\*[^$]*\$([0-9]+(?:\.[0-9]+)?)"),
    "target":       re.compile(r"\*\*Target\*\*[^$]*\$([0-9]+(?:\.[0-9]+)?)"),
    "stop":         re.compile(r"\*\*Stop\*\*[^$]*\$([0-9]+(?:\.[0-9]+)?)"),
    "position_pct": re.compile(r"\*\*Suggested position size\*\*:\s*([0-9]+(?:\.[0-9]+)?)\s*%", re.IGNORECASE),
    "stated_price": re.compile(
        r"(?:\*\*(?:Current\s+)?Price\*\*|Current Price)\s*[:\-]\s*\$\s*([0-9,]+(?:\.[0-9]+)?)",
        re.IGNORECASE,
    ),
}


def parse_theses(text: str) -> list[Thesis]:
    headers = list(_HEADER_RE.finditer(text))
    if not headers:
        return []

    blocks: list[tuple[int, str]] = []
    for i, m in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        blocks.append((int(m.group(1)), text[m.start():end]))

    theses: list[Thesis] = []
    for n, block in blocks:
        def _str(key: str) -> str | None:
            m = _FIELD[key].search(block)
            return m.group(1) if m else None

        def _flt(key: str) -> float | None:
            v = _str(key)
            try:
                return float(v) if v is not None else None
            except ValueError:
                return None

        cite = _THESIS_CITATION.search(block)
        direction = (cite.group("direction") if cite else _str("direction") or "").lower()
        ticker    = (cite.group("ticker")    if cite else _str("ticker")    or "").upper()

        if not ticker or direction not in ("long", "short"):
            continue

        # stated_price: strip commas before parsing (e.g. "1,234.56")
        _sp_raw = _str("stated_price")
        _sp = None
        if _sp_raw:
            try:
                _sp = float(_sp_raw.replace(",", ""))
            except ValueError:
                pass

        theses.append(Thesis(
            n            = n,
            direction    = direction,
            ticker       = ticker,
            conviction   = (_str("conviction") or "").lower(),
            entry        = _flt("entry"),
            target       = _flt("target"),
            stop         = _flt("stop"),
            position_pct = _flt("position_pct"),
            stated_price = _sp,
        ))

    return theses


# ---------------------------------------------------------------------------
# Signal loader
# ---------------------------------------------------------------------------

def load_signals(tickers: list[str]) -> dict[str, dict[str, Any]]:
    if not _DB_PATH.exists():
        return {}
    try:
        con = sqlite3.connect(str(_DB_PATH))
        con.row_factory = sqlite3.Row
        result: dict[str, dict[str, Any]] = {}
        for ticker in tickers:
            row = con.execute(
                "SELECT * FROM signals WHERE ticker=? ORDER BY date DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if row:
                result[ticker] = dict(row)
        con.close()
    except Exception:
        result = {}
    return result


# ---------------------------------------------------------------------------
# Portfolio loader
# ---------------------------------------------------------------------------

_EXCHANGE_TO_YF_SUFFIX: dict[str, str] = {
    "SHSE": "SS",   # Shanghai Stock Exchange  SHSE.XXXXXX -> XXXXXX.SS
    "SZSE": "SZ",   # Shenzhen Stock Exchange  SZSE.XXXXXX -> XXXXXX.SZ
    "HKEx": "HK",   # Hong Kong Exchange       HKEx:XXXX   -> XXXX.HK
    "HKEX": "HK",
    "LSE":  "L",    # London Stock Exchange    LSE:XXXX    -> XXXX.L
    "TSX":  "TO",   # Toronto Stock Exchange   TSX:XXXX    -> XXXX.TO
    "ASX":  "AX",   # Australian Securities    ASX:XXXX    -> XXXX.AX
    "BSE":  "BO",   # Bombay Stock Exchange    BSE:XXXX    -> XXXX.BO
    "NSE":  "NS",   # National Stock Exchange  NSE:XXXX    -> XXXX.NS
}


def _normalize_yf_ticker(ticker: str) -> str:
    """Convert exchange-prefixed tickers (SHSE.000300, LSE:HSBA) to Yahoo Finance format."""
    for prefix, suffix in _EXCHANGE_TO_YF_SUFFIX.items():
        if ticker.upper().startswith(prefix.upper() + "."):
            symbol = ticker[len(prefix) + 1:]
            return f"{symbol}.{suffix}"
        if ticker.upper().startswith(prefix.upper() + ":"):
            symbol = ticker[len(prefix) + 1:]
            return f"{symbol}.{suffix}"
    return ticker


def _load_current_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch last price per ticker via yfinance. Best-effort; missing tickers are omitted."""
    prices: dict[str, float] = {}
    for ticker in tickers:
        yf_ticker = _normalize_yf_ticker(ticker)
        try:
            import yfinance as yf
            info = yf.Ticker(yf_ticker).fast_info
            price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
            if price and float(price) > 0:
                prices[ticker] = float(price)
        except Exception:
            pass
    return prices


def _load_portfolio() -> dict[str, Any] | None:
    try:
        from harness.alpaca_tool import get_account
        return get_account()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Validation rules -each returns a single Check
# ---------------------------------------------------------------------------

def _check_momentum(t: Thesis, sig: dict) -> Check:
    rank = sig.get("momentum_rank")
    if rank is None:
        return Check("Momentum rank", "N/A", "no signal data")
    if t.direction == "long":
        if rank >= 0.6:
            return Check("Momentum rank", "PASS",
                         f"rank={rank:.2f} (top {100*(1-rank):.0f}% of universe, supports Long)")
        if rank >= 0.4:
            return Check("Momentum rank", "WARN",
                         f"rank={rank:.2f} (near median, weak momentum for Long)")
        return Check("Momentum rank", "FLAG",
                     f"rank={rank:.2f} (bottom {100*rank:.0f}% of universe, contradicts Long)")
    else:
        if rank <= 0.4:
            return Check("Momentum rank", "PASS",
                         f"rank={rank:.2f} (bottom {100*rank:.0f}% of universe, supports Short)")
        if rank <= 0.6:
            return Check("Momentum rank", "WARN",
                         f"rank={rank:.2f} (near median, weak momentum for Short)")
        return Check("Momentum rank", "FLAG",
                     f"rank={rank:.2f} (top {100*(1-rank):.0f}% of universe, contradicts Short)")


def _check_hurst(t: Thesis, sig: dict) -> Check:
    h = sig.get("hurst_exp")
    if h is None:
        return Check("Hurst exponent", "N/A", "insufficient price history")
    if h > 0.65:
        return Check("Hurst exponent", "PASS",
                     f"H={h:.3f} (strong trend regime, momentum strategy appropriate)")
    if h > 0.5:
        return Check("Hurst exponent", "PASS",
                     f"H={h:.3f} (mild trend, directional bias supported)")
    if h > 0.45:
        return Check("Hurst exponent", "WARN",
                     f"H={h:.3f} (near random walk, trend signal weak)")
    return Check("Hurst exponent", "WARN",
                 f"H={h:.3f} (mean-reverting regime, directional trade faces headwind)")


def _check_bb(t: Thesis, sig: dict) -> Check:
    z = sig.get("bb_zscore")
    if z is None:
        return Check("BB z-score", "N/A", "no signal data")
    if t.direction == "long":
        if z > 1.5:
            return Check("BB z-score", "WARN",
                         f"z={z:.2f} (overbought, risk of pullback before entry)")
        if z < -1.5:
            return Check("BB z-score", "WARN",
                         f"z={z:.2f} (oversold, contrarian long -watch for further downside)")
        return Check("BB z-score", "PASS",
                     f"z={z:.2f} (within bands, neutral entry zone)")
    else:
        if z < -1.5:
            return Check("BB z-score", "WARN",
                         f"z={z:.2f} (oversold, bounce risk -chasing the Short)")
        if z > 1.5:
            return Check("BB z-score", "PASS",
                         f"z={z:.2f} (overbought, supports Short entry)")
        return Check("BB z-score", "PASS",
                     f"z={z:.2f} (within bands, neutral zone)")


def _check_sma(t: Thesis, sig: dict) -> Check:
    cross = sig.get("sma_cross")
    sma20 = sig.get("sma_20")
    sma50 = sig.get("sma_50")
    if cross is None or cross == "insufficient":
        return Check("SMA cross", "N/A", "insufficient data for SMA-50")

    if sma20 is not None and sma50 is not None:
        suffix = f" (SMA20=${sma20:.2f}, SMA50=${sma50:.2f})"
    else:
        suffix = ""

    if t.direction == "long":
        if cross == "golden":
            return Check("SMA cross", "PASS", f"golden cross{suffix} - bullish confirmation")
        if cross == "above":
            return Check("SMA cross", "PASS", f"SMA20 above SMA50{suffix} - uptrend intact")
        if cross == "death":
            return Check("SMA cross", "FLAG", f"death cross{suffix} - contradicts Long thesis")
        return Check("SMA cross", "WARN", f"SMA20 below SMA50{suffix} - downtrend, weak for Long")
    else:
        if cross == "death":
            return Check("SMA cross", "PASS", f"death cross{suffix} - bearish confirmation")
        if cross == "below":
            return Check("SMA cross", "PASS", f"SMA20 below SMA50{suffix} - downtrend intact")
        if cross == "golden":
            return Check("SMA cross", "FLAG", f"golden cross{suffix} - contradicts Short thesis")
        return Check("SMA cross", "WARN", f"SMA20 above SMA50{suffix} - uptrend, weak for Short")


def _check_vol(sig: dict) -> Check:
    vol = sig.get("vol_30d")
    if vol is None:
        return Check("Volatility", "N/A", "no signal data")
    pct = vol * 100
    if vol > 1.2:
        return Check("Volatility", "FLAG",
                     f"vol={pct:.0f}% ann. (extreme -reduce size, high slippage risk)")
    if vol > 0.8:
        return Check("Volatility", "WARN",
                     f"vol={pct:.0f}% ann. (elevated -consider reducing position size)")
    if vol > 0.5:
        return Check("Volatility", "WARN",
                     f"vol={pct:.0f}% ann. (above average -widen stop buffer accordingly)")
    return Check("Volatility", "PASS", f"vol={pct:.0f}% ann. (within normal range)")


def _check_rr(t: Thesis) -> Check:
    if t.entry is None or t.target is None or t.stop is None:
        return Check("Risk/Reward", "N/A", "could not parse entry/target/stop prices from thesis")

    if t.direction == "long":
        risk   = t.entry - t.stop
        reward = t.target - t.entry
    else:
        risk   = t.stop - t.entry
        reward = t.entry - t.target

    if risk <= 0:
        return Check("Risk/Reward", "FLAG",
                     f"stop on wrong side of entry (entry=${t.entry}, stop=${t.stop})")
    if reward <= 0:
        return Check("Risk/Reward", "FLAG",
                     f"target on wrong side of entry (entry=${t.entry}, target=${t.target})")

    rr       = reward / risk
    stop_pct = abs(risk / t.entry) * 100
    detail   = f"R/R={rr:.2f} | entry=${t.entry}, target=${t.target}, stop=${t.stop} ({stop_pct:.1f}% stop width)"

    # Low conviction requires stricter minimums: uncertain theses need stronger payoff to justify risk
    flag_at = 1.5 if t.conviction == "low" else 1.0
    warn_at = 2.0 if t.conviction == "low" else 1.5

    if rr < flag_at:
        note = " (low conviction requires R/R >= 1.5)" if t.conviction == "low" else ""
        return Check("Risk/Reward", "FLAG", f"{detail} - below {flag_at:.1f}:1{note}")
    if rr < warn_at:
        return Check("Risk/Reward", "WARN", f"{detail} - below {warn_at:.1f}:1 minimum")
    if stop_pct > 15:
        return Check("Risk/Reward", "WARN", f"{detail} - stop >15% from entry (very wide)")
    if stop_pct < 2:
        return Check("Risk/Reward", "WARN", f"{detail} - stop <2% from entry (noise-exposed)")
    return Check("Risk/Reward", "PASS", detail)


def _check_price_integrity(t: Thesis, live_price: float) -> Check:
    """Compare the price the model stated in the thesis against the live yfinance price."""
    if t.stated_price is None:
        return Check("Price integrity", "N/A", "no stated current price found in thesis text")
    diff_pct = abs(live_price - t.stated_price) / live_price * 100
    detail = f"stated=${t.stated_price:.2f} vs live=${live_price:.2f} ({diff_pct:.0f}% divergence)"
    if diff_pct > 30:
        return Check("Price integrity", "FLAG",
                     f"{detail} - model used hallucinated/stale price; entry/target/stop levels are unreliable")
    if diff_pct > 10:
        return Check("Price integrity", "WARN",
                     f"{detail} - verify price source before trading")
    return Check("Price integrity", "PASS", f"{detail} - price confirmed")


def _check_market_vs_levels(t: Thesis, current_price: float) -> Check:
    if t.entry is None or t.target is None or t.stop is None:
        return Check("Market vs. levels", "N/A", "missing entry/target/stop")

    if t.direction == "long":
        if current_price >= t.target:
            return Check("Market vs. levels", "FLAG",
                         f"current=${current_price:.2f} >= target=${t.target} - thesis already invalidated")
        if current_price <= t.stop:
            return Check("Market vs. levels", "FLAG",
                         f"current=${current_price:.2f} <= stop=${t.stop} - would stop out immediately")
        if t.entry < current_price * 0.85:
            return Check("Market vs. levels", "WARN",
                         f"current=${current_price:.2f}, limit entry=${t.entry} is >15% below - requires significant pullback to fill")
        return Check("Market vs. levels", "PASS",
                     f"current=${current_price:.2f} within range (stop=${t.stop}, target=${t.target})")
    else:
        if current_price <= t.target:
            return Check("Market vs. levels", "FLAG",
                         f"current=${current_price:.2f} <= target=${t.target} - thesis already invalidated")
        if current_price >= t.stop:
            return Check("Market vs. levels", "FLAG",
                         f"current=${current_price:.2f} >= stop=${t.stop} - would stop out immediately")
        if t.entry > current_price * 1.15:
            return Check("Market vs. levels", "WARN",
                         f"current=${current_price:.2f}, limit entry=${t.entry} is >15% above - requires significant rally to fill")
        return Check("Market vs. levels", "PASS",
                     f"current=${current_price:.2f} within range (target=${t.target}, stop=${t.stop})")


def _check_position_size(t: Thesis, portfolio: dict | None) -> Check:
    if t.position_pct is None:
        return Check("Position size", "WARN", "thesis missing position size - execution will be blocked")
    if portfolio is None:
        return Check("Position size", "N/A", "Alpaca portfolio unavailable")
    try:
        port_val     = float(portfolio.get("portfolio_value", 0))
        buying_power = float(portfolio.get("buying_power", 0))
        notional     = (t.position_pct / 100) * port_val
        detail = (f"{t.position_pct:.0f}% of portfolio = ${notional:,.0f} notional "
                  f"vs ${buying_power:,.0f} buying power")
        if notional > buying_power:
            return Check("Position size", "FLAG", f"{detail} - exceeds buying power")
        if notional > buying_power * 0.5:
            return Check("Position size", "WARN", f"{detail} - consumes >50% of buying power")
        return Check("Position size", "PASS", detail)
    except Exception:
        return Check("Position size", "N/A", "could not compute notional")


# ---------------------------------------------------------------------------
# Per-thesis validator
# ---------------------------------------------------------------------------

def validate_thesis(
    t: Thesis,
    sig: dict | None,
    portfolio: dict | None,
    current_price: float | None = None,
) -> ThesisValidation:
    v = ThesisValidation(thesis=t)
    if current_price is not None:
        v.checks.append(_check_price_integrity(t, current_price))
        v.checks.append(_check_market_vs_levels(t, current_price))
    if sig:
        v.checks.append(_check_momentum(t, sig))
        v.checks.append(_check_hurst(t, sig))
        v.checks.append(_check_bb(t, sig))
        v.checks.append(_check_sma(t, sig))
        v.checks.append(_check_vol(sig))
    else:
        v.checks.append(Check("Signal data", "N/A",
                              f"no signals found for {t.ticker} in DB -run market_signals_skill"))
    v.checks.append(_check_rr(t))
    v.checks.append(_check_position_size(t, portfolio))
    return v


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------

def _render_report(validations: list[ThesisValidation], computed_at: str) -> str:
    lines = [
        "## Trade Validation",
        f"*Computed {computed_at}. Deterministic rule-based checks -no LLM involved.*",
        "",
    ]

    for v in validations:
        t = v.thesis
        lines.append(f"### Thesis {t.n}: {t.direction.capitalize()} {t.ticker}")
        lines.append("")
        lines.append("| Check | Status | Detail |")
        lines.append("|-------|--------|--------|")
        for c in v.checks:
            lines.append(f"| {c.name} | **{c.status}** | {c.detail} |")
        lines.append("")

        parts = []
        if v.warn_count:
            parts.append(f"{v.warn_count} warning{'s' if v.warn_count != 1 else ''}")
        if v.flag_count:
            parts.append(f"{v.flag_count} flag{'s' if v.flag_count != 1 else ''}")
        suffix = f" ({', '.join(parts)})" if parts else ""
        lines.append(f"**Overall: {v.overall}{suffix}**")
        lines.append("")

    lines += [
        "### Validation Summary",
        "",
        "| # | Ticker | Dir | Conviction | Result | Warns | Flags |",
        "|---|--------|-----|------------|--------|-------|-------|",
    ]
    for v in validations:
        t = v.thesis
        lines.append(
            f"| {t.n} | {t.ticker} | {t.direction.capitalize()} "
            f"| {t.conviction.capitalize()} | **{v.overall}** "
            f"| {v.warn_count} | {v.flag_count} |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Dict-based entry point (for lit-review synthesis output)
# ---------------------------------------------------------------------------

def validate_thesis_dict(thesis: dict) -> dict:
    """
    Validate a thesis dict produced by the lit-review finance synthesis step.
    Returns a serializable dict with overall status and per-check results.
    """
    ticker    = (thesis.get("ticker") or "").upper()
    direction = (thesis.get("direction") or "long").lower()

    if not ticker or direction not in ("long", "short"):
        return {"overall": "N/A", "checks": [], "error": "missing ticker or direction"}

    t = Thesis(
        n            = 1,
        direction    = direction,
        ticker       = ticker,
        conviction   = (thesis.get("conviction") or "medium").lower(),
        entry        = thesis.get("entry"),
        target       = thesis.get("target"),
        stop         = thesis.get("stop"),
        position_pct = thesis.get("position_pct"),
    )

    signals   = load_signals([ticker])
    sig       = signals.get(ticker)
    portfolio = _load_portfolio()
    prices    = _load_current_prices([ticker]) if t.entry else {}
    current_price = prices.get(ticker)

    v = validate_thesis(t, sig, portfolio, current_price)
    return {
        "overall": v.overall,
        "flag_count": v.flag_count,
        "warn_count": v.warn_count,
        "checks": [
            {"name": c.name, "status": c.status, "detail": c.detail}
            for c in v.checks
        ],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def validate_thesis_file(path: str) -> str | None:
    """
    Parse theses in path, validate against signals DB + Alpaca, append
    a ## Trade Validation section. Returns the report string or None.
    """
    p = Path(path)
    if not p.exists():
        print(f"  [validate-trades] file not found: {path}")
        return None

    text    = p.read_text(encoding="utf-8")
    theses  = parse_theses(text)

    if not theses:
        print("  [validate-trades] no [THESIS:...] citations found - skipping")
        return None

    tickers = [t.ticker for t in theses]
    print(f"  [validate-trades] validating {len(theses)} thesis/theses: {', '.join(tickers)}")

    signals   = load_signals(tickers)
    portfolio = _load_portfolio()
    prices    = _load_current_prices(tickers)

    if prices:
        print(f"  [validate-trades] prices: {', '.join(f'{k}=${v:.2f}' for k, v in prices.items())}")

    validations = [
        validate_thesis(t, signals.get(t.ticker), portfolio, prices.get(t.ticker))
        for t in theses
    ]

    for v in validations:
        print(f"    Thesis {v.thesis.n} {v.thesis.direction.upper()} {v.thesis.ticker}: "
              f"{v.overall} ({v.warn_count}W/{v.flag_count}F)")

    computed_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    report      = _render_report(validations, computed_at)

    # Replace any existing validation section
    if "## Trade Validation" in text:
        text = text[:text.index("## Trade Validation")].rstrip()

    p.write_text(text.rstrip() + "\n\n---\n\n" + report + "\n", encoding="utf-8")
    print(f"  [validate-trades] appended to {path}")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m harness.trade_validator <thesis_file.md>")
        sys.exit(1)
    result = validate_thesis_file(sys.argv[1])
    if result:
        print("\n" + result)
