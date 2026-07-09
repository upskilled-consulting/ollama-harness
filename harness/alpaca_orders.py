"""
harness/alpaca_orders.py -- Deterministic bracket order construction for validated theses.

Rules encoded from alpaca-docs/us_docs_orders-at-alpaca.md:
  - Bracket order_class: entry triggers take_profit (limit) + stop_loss (stop/stop-limit)
  - time_in_force: "gtc" -- persists until filled or 90-day expiry (whole shares only with GTC)
  - Qty: whole shares (floor) -- fractional shares only supported with DAY tif, not GTC+bracket
  - Price precision: 2 decimals for prices >= $1; 4 decimals for prices < $1
  - Buy bracket invariant: take_profit.limit_price > stop_loss.stop_price
  - Sell bracket invariant: take_profit.limit_price < stop_loss.stop_price
  - Stop-loss stop_price must differ from base price (entry limit) by >= $0.01
  - extended_hours must be omitted/false for bracket orders
  - Notional field cannot be used with bracket -- must use qty
  - Short sell: side="sell" with no existing long position opens a short

CLI:
    python -m harness.alpaca_orders path/to/thesis.md
    python -m harness.alpaca_orders path/to/thesis.md --live
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.trade_validator import (
    Thesis,
    ThesisValidation,
    load_signals,
    parse_theses,
    validate_thesis,
)

# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def _round_price(price: float) -> str:
    """Round price per Alpaca sub-penny rules and return as string."""
    if price >= 1.0:
        return f"{price:.2f}"
    return f"{price:.4f}"


def _stop_limit_price(stop_price: float, direction: str) -> str:
    """
    Add a $1.00 buffer beyond stop to avoid gap executions at catastrophic prices.
    For a long stop-loss (sell stop): stop_limit = stop - 1.00
    For a short stop-loss (buy  stop): stop_limit = stop + 1.00
    """
    buffer = -1.00 if direction == "long" else 1.00
    return _round_price(max(0.01, stop_price + buffer))


# ---------------------------------------------------------------------------
# Current price fetcher
# ---------------------------------------------------------------------------

def _get_current_price(ticker: str) -> float | None:
    """Get current price via yfinance (reliable enough for position sizing)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).fast_info
        price = getattr(info, "last_price", None) or getattr(info, "regular_market_price", None)
        if price and price > 0:
            return float(price)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Order data class
# ---------------------------------------------------------------------------

@dataclass
class OrderSpec:
    ticker:      str
    direction:   str           # "long" | "short"
    side:        str           # "buy" | "sell"
    qty:         int           # whole shares
    entry_price: float | None  # None = market order
    take_profit: float
    stop_loss:   float
    notional:    float         # dollar value
    current_price: float
    body:        dict = field(default_factory=dict)


@dataclass
class OrderResult:
    ticker:    str
    direction: str
    status:    str             # "submitted" | "dry_run" | "skipped" | "error"
    reason:    str
    order_id:  str | None = None
    body:      dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Order construction
# ---------------------------------------------------------------------------

def _validate_bracket_invariants(spec: OrderSpec) -> list[str]:
    """
    Return a list of error strings if the bracket order would be rejected.
    Empty list = valid.
    """
    errors = []
    if spec.direction == "long":
        # take_profit > stop_loss for buy bracket
        if spec.take_profit <= spec.stop_loss:
            errors.append(
                f"take_profit ({spec.take_profit}) must be > stop_loss ({spec.stop_loss}) for buy bracket"
            )
        # stop_price must be < entry limit by >= $0.01
        if spec.entry_price is not None and spec.stop_loss >= spec.entry_price - 0.01:
            errors.append(
                f"stop_loss ({spec.stop_loss}) must be at least $0.01 below entry ({spec.entry_price})"
            )
        # take_profit must be > entry
        if spec.entry_price is not None and spec.take_profit <= spec.entry_price:
            errors.append(
                f"take_profit ({spec.take_profit}) must be above entry ({spec.entry_price}) for Long"
            )
    else:
        # Short sell bracket: take_profit < stop_loss
        if spec.take_profit >= spec.stop_loss:
            errors.append(
                f"take_profit ({spec.take_profit}) must be < stop_loss ({spec.stop_loss}) for sell bracket"
            )
        if spec.entry_price is not None and spec.stop_loss <= spec.entry_price + 0.01:
            errors.append(
                f"stop_loss ({spec.stop_loss}) must be at least $0.01 above entry ({spec.entry_price}) for Short"
            )
        if spec.entry_price is not None and spec.take_profit >= spec.entry_price:
            errors.append(
                f"take_profit ({spec.take_profit}) must be below entry ({spec.entry_price}) for Short"
            )
    if spec.qty < 1:
        errors.append(f"qty={spec.qty} -- must be at least 1 whole share")
    return errors


def build_order_spec(
    thesis: Thesis,
    portfolio_value: float,
    buying_power: float,
    current_price: float,
) -> tuple[OrderSpec | None, list[str]]:
    """
    Build an OrderSpec from a validated thesis. Returns (spec, errors).
    errors is empty on success.
    """
    if thesis.entry is None or thesis.target is None or thesis.stop is None:
        return None, ["thesis missing entry/target/stop prices"]
    if thesis.position_pct is None:
        return None, ["thesis missing suggested position size"]

    notional = (thesis.position_pct / 100) * portfolio_value
    if notional > buying_power:
        return None, [f"notional ${notional:,.0f} exceeds buying power ${buying_power:,.0f}"]

    qty = max(1, math.floor(notional / current_price))
    actual_notional = qty * current_price

    side = "buy" if thesis.direction == "long" else "sell"

    spec = OrderSpec(
        ticker       = thesis.ticker,
        direction    = thesis.direction,
        side         = side,
        qty          = qty,
        entry_price  = thesis.entry,
        take_profit  = thesis.target,
        stop_loss    = thesis.stop,
        notional     = actual_notional,
        current_price = current_price,
    )

    errors = _validate_bracket_invariants(spec)
    if errors:
        return spec, errors

    # Build the REST body
    body: dict[str, Any] = {
        "symbol":        thesis.ticker.upper(),
        "qty":           str(qty),
        "side":          side,
        "time_in_force": "gtc",
        "order_class":   "bracket",
        "take_profit": {
            "limit_price": _round_price(thesis.target),
        },
        "stop_loss": {
            "stop_price":  _round_price(thesis.stop),
            "limit_price": _stop_limit_price(thesis.stop, thesis.direction),
        },
    }

    if thesis.entry is not None:
        body["type"]        = "limit"
        body["limit_price"] = _round_price(thesis.entry)
    else:
        body["type"] = "market"

    spec.body = body
    return spec, []


# ---------------------------------------------------------------------------
# Pre-execution checks
# ---------------------------------------------------------------------------

def _get_existing_positions() -> dict[str, str]:
    """Return {ticker: side} for currently open positions."""
    try:
        from harness.alpaca_tool import get_positions
        return {p["symbol"]: p.get("side", "long") for p in get_positions()}
    except Exception:
        return {}


def _get_account_state() -> tuple[float, float]:
    """Return (portfolio_value, buying_power). Raises on failure."""
    from harness.alpaca_tool import get_account
    acct = get_account()
    return float(acct["portfolio_value"]), float(acct["buying_power"])


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------

def _submit_order(body: dict) -> dict:
    from harness.alpaca_tool import _post
    return _post("/v2/orders", body)


def _format_spec_preview(spec: OrderSpec) -> str:
    lines = [
        f"  Ticker:        {spec.ticker}",
        f"  Direction:     {spec.direction.capitalize()}",
        f"  Side:          {spec.side}",
        f"  Qty:           {spec.qty} shares",
        f"  Entry:         ${spec.entry_price} ({'limit' if spec.entry_price else 'market'})",
        f"  Take profit:   ${spec.take_profit}",
        f"  Stop loss:     ${spec.stop_loss}",
        f"  Notional:      ~${spec.notional:,.0f} ({spec.qty} x ${spec.current_price:.2f})",
        "  TIF:           GTC (bracket)",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main execution entry point
# ---------------------------------------------------------------------------

def execute_from_thesis_file(
    path: str,
    live: bool = False,
    skip_flagged: bool = True,
) -> list[OrderResult]:
    """
    Parse a validated thesis file, build bracket orders for passing theses,
    and submit (or dry-run) them. Appends an ## Orders section to the file.

    Args:
        path:         Path to the thesis markdown file.
        live:         False = dry-run (print only). True = submit to Alpaca.
        skip_flagged: Skip theses with FLAG validation status (default True).

    Returns:
        List of OrderResult objects.
    """
    p = Path(path)
    if not p.exists():
        print(f"  [execute-trades] file not found: {path}")
        return []

    text   = p.read_text(encoding="utf-8")
    theses = parse_theses(text)
    if not theses:
        print("  [execute-trades] no theses found in file")
        return []

    mode = "DRY RUN" if not live else "LIVE"
    print(f"\n[execute-trades] {mode} mode -- {len(theses)} thesis/theses in {p.name}")

    # Load signals for validation (needed to check FLAGS)
    tickers    = [t.ticker for t in theses]
    signals    = load_signals(tickers)
    validations: dict[str, ThesisValidation] = {}
    for t in theses:
        portfolio = None  # portfolio checked separately below
        v = validate_thesis(t, signals.get(t.ticker), None)
        validations[t.ticker] = v

    # Account state
    try:
        portfolio_value, buying_power = _get_account_state()
        print(f"  Portfolio: ${portfolio_value:,.2f}  Buying power: ${buying_power:,.2f}")
    except Exception as e:
        print(f"  [execute-trades] cannot fetch account state: {e}")
        return []

    existing_positions = _get_existing_positions()
    results: list[OrderResult] = []
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    for t in theses:
        v = validations.get(t.ticker)
        print(f"\n  Thesis {t.n}: {t.direction.upper()} {t.ticker} (validation: {v.overall if v else 'unknown'})")

        # Gate 1: validation must PASS or WARN (no FLAGS unless overridden)
        if skip_flagged and v and v.overall == "FLAG":
            reason = f"skipped -- validation FLAG ({v.flag_count} flag(s))"
            print(f"    {reason}")
            results.append(OrderResult(ticker=t.ticker, direction=t.direction, status="skipped", reason=reason))
            continue

        # Gate 2: no conflicting existing position
        existing = existing_positions.get(t.ticker)
        if existing:
            if (t.direction == "long" and existing == "short") or (t.direction == "short" and existing == "long"):
                reason = f"skipped -- existing {existing} position in {t.ticker} conflicts with {t.direction} thesis"
                print(f"    {reason}")
                results.append(OrderResult(ticker=t.ticker, direction=t.direction, status="skipped", reason=reason))
                continue
            elif existing:
                reason = f"skipped -- already have {existing} position in {t.ticker}"
                print(f"    {reason}")
                results.append(OrderResult(ticker=t.ticker, direction=t.direction, status="skipped", reason=reason))
                continue

        # Gate 3: current price
        current_price = _get_current_price(t.ticker)
        if not current_price:
            reason = f"skipped -- could not fetch current price for {t.ticker}"
            print(f"    {reason}")
            results.append(OrderResult(ticker=t.ticker, direction=t.direction, status="skipped", reason=reason))
            continue

        print(f"    Current price: ${current_price:.2f}")

        # Build order
        spec, errors = build_order_spec(t, portfolio_value, buying_power, current_price)
        if errors:
            reason = "skipped -- " + "; ".join(errors)
            print(f"    {reason}")
            results.append(OrderResult(ticker=t.ticker, direction=t.direction, status="skipped", reason=reason, body=spec.body if spec else {}))
            continue

        print(_format_spec_preview(spec))
        print(f"    Order body: {json.dumps(spec.body, indent=6)}")

        if not live:
            results.append(OrderResult(
                ticker    = t.ticker,
                direction = t.direction,
                status    = "dry_run",
                reason    = "dry_run mode -- use --live to submit",
                body      = spec.body,
            ))
            continue

        # Submit
        try:
            resp = _submit_order(spec.body)
            order_id = resp.get("id", "?")
            print(f"    Submitted -- order_id={order_id} status={resp.get('status', '?')}")
            results.append(OrderResult(
                ticker    = t.ticker,
                direction = t.direction,
                status    = "submitted",
                reason    = f"order_id={order_id}",
                order_id  = order_id,
                body      = spec.body,
            ))
            # Subtract committed notional from available buying power for subsequent orders
            buying_power -= spec.notional
        except Exception as e:
            reason = f"error: {e}"
            print(f"    Submit failed: {reason}")
            results.append(OrderResult(ticker=t.ticker, direction=t.direction, status="error", reason=reason, body=spec.body))

    # Append results to thesis file
    _append_order_section(p, results, timestamp, mode)
    return results


def _append_order_section(p: Path, results: list[OrderResult], timestamp: str, mode: str) -> None:
    text = p.read_text(encoding="utf-8")

    # Strip existing orders section
    marker = "## Orders"
    if marker in text:
        text = text[:text.index(marker)].rstrip()

    lines = [
        "",
        "---",
        "",
        "## Orders",
        f"*{mode} run at {timestamp}*",
        "",
        "| # | Ticker | Dir | Status | Detail |",
        "|---|--------|-----|--------|--------|",
    ]
    for i, r in enumerate(results, 1):
        detail = r.reason[:80]
        lines.append(f"| {i} | {r.ticker} | {r.direction.capitalize()} | {r.status} | {detail} |")

    submitted = [r for r in results if r.status == "submitted"]
    dry_run   = [r for r in results if r.status == "dry_run"]
    if submitted:
        lines += ["", f"**{len(submitted)} order(s) submitted to Alpaca.**"]
    elif dry_run:
        lines += ["", f"**{len(dry_run)} order(s) staged (dry run -- re-run with --live to submit).**"]

    p.write_text(text.rstrip() + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n  [execute-trades] order section written to {p.name}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args:
        print("Usage: python -m harness.alpaca_orders <thesis.md> [--live]")
        sys.exit(1)
    thesis_path = next((a for a in args if not a.startswith("--")), None)
    live_mode   = "--live" in args
    if not thesis_path:
        print("Error: no thesis file specified")
        sys.exit(1)
    execute_from_thesis_file(thesis_path, live=live_mode)
