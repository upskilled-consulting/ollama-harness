"""
harness/alpaca_tool.py — Alpaca paper/live trading integration.

Provides portfolio context for agent enrichment and order execution.
Paper trading is the default; set IS_PAPER_TRADING=false in .env for live.

CLI:
    python -m harness.alpaca_tool account
    python -m harness.alpaca_tool positions
    python -m harness.alpaca_tool orders [--status open|closed|all]
    python -m harness.alpaca_tool buy AAPL 10
    python -m harness.alpaca_tool buy AAPL --notional 1000
    python -m harness.alpaca_tool sell AAPL 5 --limit 150.00 [--gtc]
    python -m harness.alpaca_tool cancel-all
    python -m harness.alpaca_tool context
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_PAPER_BASE = "https://paper-api.alpaca.markets"
_LIVE_BASE  = "https://api.alpaca.markets"
_TIMEOUT    = 15

# --------------------------------------------------------------------------- #
# Credentials                                                                  #
# --------------------------------------------------------------------------- #

def _base_url() -> str:
    val = os.environ.get("IS_PAPER_TRADING", "true").lower().strip('"').strip("'")
    return _PAPER_BASE if val in ("1", "true", "yes") else _LIVE_BASE


def _creds() -> tuple[str, str]:
    try:
        from harness.config import ROOT as _ROOT
        env = _ROOT / ".env"
        key = secret = ""
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k == "TRADING_API_KEY":
                        key = v
                    elif k == "TRADING_API_SECRET":
                        secret = v
        if key and secret:
            return key, secret
    except Exception:
        pass
    return (
        os.environ.get("TRADING_API_KEY", "").strip('"').strip("'"),
        os.environ.get("TRADING_API_SECRET", "").strip('"').strip("'"),
    )


def _headers() -> dict[str, str]:
    key, secret = _creds()
    if not key or not secret:
        raise RuntimeError("TRADING_API_KEY / TRADING_API_SECRET not set in .env")
    return {
        "APCA-API-KEY-ID":     key,
        "APCA-API-SECRET-KEY": secret,
        "Content-Type":        "application/json",
        "Accept":              "application/json",
    }

# --------------------------------------------------------------------------- #
# HTTP helpers                                                                 #
# --------------------------------------------------------------------------- #

def _get(path: str, params: dict | None = None) -> Any:
    url = _base_url() + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Alpaca HTTP {e.code}: {body}") from e


def _post(path: str, body: dict) -> Any:
    data = json.dumps(body).encode("utf-8")
    req  = urllib.request.Request(
        _base_url() + path, data=data, headers=_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Alpaca HTTP {e.code}: {body}") from e


def _delete(path: str) -> int:
    req = urllib.request.Request(
        _base_url() + path, headers=_headers(), method="DELETE"
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        if e.code == 207:
            return 207
        body = e.read().decode("utf-8", errors="replace")[:200]
        raise RuntimeError(f"Alpaca HTTP {e.code}: {body}") from e

# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def get_account() -> dict:
    return _get("/v2/account")


def get_positions() -> list[dict]:
    return _get("/v2/positions")


def get_orders(status: str = "open", limit: int = 50) -> list[dict]:
    return _get("/v2/orders", {"status": status, "limit": limit})


def check_asset(symbol: str) -> dict:
    return _get(f"/v2/assets/{symbol.upper()}")


def place_order(
    symbol: str,
    qty: float | None = None,
    notional: float | None = None,
    side: str = "buy",
    order_type: str = "market",
    limit_price: float | None = None,
    time_in_force: str = "day",
) -> dict:
    """Place an order. Specify qty (shares) or notional (dollar amount)."""
    body: dict[str, Any] = {
        "symbol":        symbol.upper(),
        "side":          side.lower(),
        "type":          order_type,
        "time_in_force": time_in_force,
    }
    if notional is not None:
        body["notional"] = str(round(notional, 2))
    elif qty is not None:
        body["qty"] = str(qty)
    else:
        raise ValueError("Either qty or notional must be specified")
    if order_type == "limit" and limit_price is not None:
        body["limit_price"] = str(round(limit_price, 2))
    return _post("/v2/orders", body)


def cancel_all_orders() -> int:
    return _delete("/v2/orders")

# --------------------------------------------------------------------------- #
# Context formatting (agent injection)                                         #
# --------------------------------------------------------------------------- #

def format_portfolio_context() -> str:
    env_label = "PAPER" if _base_url() == _PAPER_BASE else "LIVE"
    lines: list[str] = [f"## Portfolio State (Alpaca {env_label})\n"]

    try:
        acct = get_account()
        lines.append("**Account**")
        lines.append(f"- Portfolio value: ${float(acct.get('portfolio_value', 0)):,.2f}")
        lines.append(f"- Cash: ${float(acct.get('cash', 0)):,.2f}")
        lines.append(f"- Buying power: ${float(acct.get('buying_power', 0)):,.2f}")
        lines.append(f"- Day trades today: {acct.get('daytrade_count', 0)}")
        lines.append("")
    except Exception as e:
        lines.append(f"[account unavailable: {e}]\n")

    try:
        positions = get_positions()
        if positions:
            lines.append(f"**Open Positions** ({len(positions)})")
            for p in sorted(positions, key=lambda x: abs(float(x.get("market_value", 0))), reverse=True):
                sym   = p["symbol"]
                qty   = float(p["qty"])
                side  = p.get("side", "long")
                mv    = float(p.get("market_value", 0))
                pl    = float(p.get("unrealized_pl", 0))
                plpct = float(p.get("unrealized_plpc", 0)) * 100
                ep    = float(p.get("avg_entry_price", 0))
                cp    = float(p.get("current_price", 0))
                lines.append(
                    f"- [PORTFOLIO:{sym}] **{sym}** {side} {qty:.0f}sh"
                    f" entry=${ep:.2f} current=${cp:.2f}"
                    f" MV=${mv:,.0f} P&L=${pl:+,.0f} ({plpct:+.1f}%)"
                )
        else:
            lines.append("**Open Positions**: none")
        lines.append("")
    except Exception as e:
        lines.append(f"[positions unavailable: {e}]\n")

    try:
        orders = get_orders(status="open")
        if orders:
            lines.append(f"**Pending Orders** ({len(orders)})")
            for o in orders[:10]:
                qty_str = o.get("qty") or f"${o.get('notional', '?')}"
                lp = f" @ ${float(o['limit_price']):.2f}" if o.get("limit_price") else ""
                lines.append(f"- {o['side'].upper()} {qty_str} {o['symbol']} ({o['type']}{lp})")
            lines.append("")
    except Exception:
        pass

    return "\n".join(lines)

# --------------------------------------------------------------------------- #
# Intent detection                                                             #
# --------------------------------------------------------------------------- #

# Phrase-level matching only — avoids false positives on common words like
# "signal", "long", "short", "position" that appear in macro/research tasks.
_TRADING_PHRASES = frozenset({
    "paper trade", "paper trading",
    "alpaca",
    "buy signal", "sell signal",
    "long thesis", "short thesis",
    "trading thesis", "trade thesis",
    "entry point", "exit point",
    "position size", "portfolio allocation",
    "place order", "limit order", "market order",
    "trade idea", "trade setup", "trade recommendation",
    "actionable trade",
    "open position", "long position", "short position",
})

def _has_trading_intent(query: str) -> bool:
    q = query.lower()
    return any(phrase in q for phrase in _TRADING_PHRASES)

# --------------------------------------------------------------------------- #
# CLI helpers                                                                  #
# --------------------------------------------------------------------------- #

def _print_account() -> None:
    acct = get_account()
    env_label = "PAPER" if _base_url() == _PAPER_BASE else "LIVE"
    print(f"=== Alpaca Account ({env_label}) ===")
    for k in ["portfolio_value", "cash", "buying_power", "equity",
              "long_market_value", "short_market_value", "daytrade_count",
              "pattern_day_trader", "trading_blocked", "account_blocked"]:
        print(f"  {k}: {acct.get(k, 'n/a')}")


def _print_positions() -> None:
    positions = get_positions()
    if not positions:
        print("No open positions.")
        return
    hdr = f"{'Symbol':<8} {'Side':<6} {'Qty':>8} {'Entry':>10} {'Current':>10} {'MV':>12} {'P&L':>12} {'%':>8}"
    print(hdr)
    print("-" * len(hdr))
    for p in sorted(positions, key=lambda x: abs(float(x.get("market_value", 0))), reverse=True):
        sym   = p["symbol"]
        side  = p.get("side", "long")
        qty   = float(p["qty"])
        ep    = float(p.get("avg_entry_price", 0))
        cp    = float(p.get("current_price", 0))
        mv    = float(p.get("market_value", 0))
        pl    = float(p.get("unrealized_pl", 0))
        plpct = float(p.get("unrealized_plpc", 0)) * 100
        print(f"{sym:<8} {side:<6} {qty:>8.0f} {ep:>10.2f} {cp:>10.2f} {mv:>12,.0f} {pl:>+12,.0f} {plpct:>+7.1f}%")


def _print_orders(status: str) -> None:
    orders = get_orders(status=status)
    if not orders:
        print(f"No {status} orders.")
        return
    for o in orders:
        qty_str = o.get("qty") or f"${o.get('notional', '?')}"
        lp = f" @ ${float(o['limit_price']):.2f}" if o.get("limit_price") else ""
        print(f"  [{o['id'][:8]}] {o['side'].upper()} {qty_str} {o['symbol']} "
              f"({o['type']}{lp}) status={o['status']}")


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="alpaca_tool", description="Alpaca trading tool")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("account",   help="Show account summary")
    sub.add_parser("positions", help="Show open positions")
    sub.add_parser("context",   help="Print portfolio context block for agent injection")

    p_ord = sub.add_parser("orders", help="List orders")
    p_ord.add_argument("--status", default="open", choices=["open", "closed", "all"])

    for cmd in ("buy", "sell"):
        p = sub.add_parser(cmd, help=f"Place a {cmd} order")
        p.add_argument("symbol")
        p.add_argument("qty",        type=float, nargs="?", help="Number of shares")
        p.add_argument("--notional", type=float, help="Dollar amount instead of shares")
        p.add_argument("--limit",    type=float, help="Limit price (default: market)")
        p.add_argument("--gtc",      action="store_true", help="Good-till-cancelled")

    sub.add_parser("cancel-all", help="Cancel all open orders")

    args = parser.parse_args()

    try:
        if args.cmd == "account":
            _print_account()
        elif args.cmd == "positions":
            _print_positions()
        elif args.cmd == "orders":
            _print_orders(args.status)
        elif args.cmd == "context":
            print(format_portfolio_context())
        elif args.cmd in ("buy", "sell"):
            tif   = "gtc" if args.gtc else "day"
            otype = "limit" if args.limit else "market"
            result = place_order(
                symbol=args.symbol,
                qty=args.qty,
                notional=args.notional,
                side=args.cmd,
                order_type=otype,
                limit_price=args.limit,
                time_in_force=tif,
            )
            print(json.dumps(result, indent=2))
        elif args.cmd == "cancel-all":
            print(f"Cancel all: HTTP {cancel_all_orders()}")
        else:
            parser.print_help()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
