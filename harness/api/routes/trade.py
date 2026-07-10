"""POST /api/trade/execute, POST /api/trade/feedback"""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from harness.config import DATA_DIR

router = APIRouter(tags=["trade"])

TRADE_FEEDBACK_FILE = DATA_DIR / "trade_feedback.jsonl"


class TradeExecuteBody(BaseModel):
    ticker:       str
    direction:    str          # "long" | "short"
    conviction:   str = "medium"
    entry:        float | None = None
    target:       float | None = None
    stop:         float | None = None
    position_pct: float | None = None
    notional:     float | None = None
    qty:          float | None = None
    rationale:    str = ""
    run_id:       str = ""


class TradeFeedbackBody(BaseModel):
    run_id:    str
    ticker:    str
    direction: str
    reason:    str             # free-text rejection reason
    rating:    int = -1        # -1 = reject, 1 = approve (unused execute path)
    tags:      list[str] = []  # structured tags: ["overfit", "macro_risk", "data_quality", ...]


@router.post("/trade/execute")
async def trade_execute(body: TradeExecuteBody):
    """Execute the recommended trade via Alpaca."""
    try:
        from harness.alpaca_tool import get_account, place_order
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"alpaca_tool unavailable: {e}")

    ticker = body.ticker.upper()
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker is required")

    side = "buy" if body.direction.lower() == "long" else "sell"

    # Resolve position size: prefer explicit notional, fall back to position_pct of portfolio
    notional = body.notional
    qty      = body.qty

    if notional is None and qty is None and body.position_pct:
        try:
            acct     = get_account()
            equity   = float(acct.get("equity") or acct.get("portfolio_value") or 0)
            notional = round(equity * (body.position_pct / 100.0), 2)
        except Exception:
            pass

    if notional is None and qty is None:
        raise HTTPException(
            status_code=400,
            detail="Specify notional, qty, or position_pct to size the trade.",
        )

    try:
        order = place_order(
            symbol=ticker,
            qty=qty,
            notional=notional,
            side=side,
            order_type="market",
            time_in_force="day",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca order failed: {e}")

    record = {
        "event":      "execute",
        "trade_id":   uuid.uuid4().hex[:12],
        "run_id":     body.run_id,
        "ticker":     ticker,
        "direction":  body.direction,
        "side":       side,
        "notional":   notional,
        "qty":        qty,
        "conviction": body.conviction,
        "rationale":  body.rationale,
        "order":      order,
        "created_at": datetime.now(UTC).isoformat(),
    }
    TRADE_FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRADE_FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return {
        "status":   "submitted",
        "order_id": order.get("id"),
        "symbol":   order.get("symbol"),
        "side":     order.get("side"),
        "qty":      order.get("qty"),
        "notional": order.get("notional"),
        "trade_id": record["trade_id"],
    }


@router.post("/trade/feedback")
async def trade_feedback(body: TradeFeedbackBody):
    """Record a trade rejection with reason for downstream RL."""
    record = {
        "event":      "reject",
        "feedback_id": uuid.uuid4().hex[:12],
        "run_id":     body.run_id,
        "ticker":     body.ticker.upper(),
        "direction":  body.direction,
        "reason":     body.reason,
        "rating":     body.rating,
        "tags":       body.tags,
        "created_at": datetime.now(UTC).isoformat(),
    }
    TRADE_FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TRADE_FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


@router.get("/trade/feedback")
async def get_trade_feedback(run_id: str | None = None, limit: int = 100):
    """Retrieve trade feedback records, optionally filtered by run_id."""
    if not TRADE_FEEDBACK_FILE.exists():
        return []
    records = []
    for line in TRADE_FEEDBACK_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if run_id is None or r.get("run_id") == run_id:
            records.append(r)
    return records[-limit:]
