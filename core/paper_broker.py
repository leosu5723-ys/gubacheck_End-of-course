"""
GubaCheck - PAPER BROKER (local order simulation)
=========================================================================
Answers one question: "if I had placed this order, what would really have
happened?" It uses real daily bars from the snapshot and A-share trading
rules. No money, no brokerage account, no network.

Rules applied, in order:
    1. Entry is the NEXT trading day's open after the decision date.
       CNINFO timestamps carry a date but no time, so an announcement is
       always assumed to arrive after the close.
    2. No bar on the entry day      -> rejected: suspended / no data
    3. Open at or above limit-up    -> rejected: limit-up, cannot buy
    4. Size = 10% of capital, rounded DOWN to a 100-share lot
    5. Fees: commission (min 5 CNY) both sides, transfer fee both sides,
       stamp duty on the sell side only
    6. Exit at the close HOLD_DAYS trading days after entry (T+1 is
       automatically respected because HOLD_DAYS >= 1)

`simulate()` is a pure function: it returns a fill and writes nothing.
The caller decides whether to append it to results/ledger.csv. That keeps
every evaluation case isolated from every other one.
=========================================================================
"""
import math

from core import config, market, store


def _fees(notional, side):
    commission = max(notional * config.COMMISSION_RATE, config.COMMISSION_MIN_CNY)
    transfer = notional * config.TRANSFER_FEE
    stamp = notional * config.STAMP_DUTY_SELL if side == "sell" else 0.0
    return round(commission + transfer + stamp, 2)


def simulate(code, decision_date):
    """Simulate a buy decided after the close of `decision_date`.

    RETURNS     {"status": "filled", entry/exit prices, shares, fees, pnl}
                or {"status": "rejected", "reason": ...}
    WATCH OUT   a missing exit bar (not enough future data yet) still
                returns "filled" with exit fields set to None. That is an
                open position, not an error.
    """
    bars = store.bars(code)
    after = [b for b in bars if b["date"] > decision_date]
    if not after:
        return {"status": "rejected", "reason": "no_bar_after_decision_date"}
    entry = after[0]
    if entry.get("suspended") or not entry.get("open"):
        return {"status": "rejected", "reason": "suspended", "date": entry["date"]}

    meta = store.stock(code) or {}
    limit = market.limit_up_price(entry["prev_close"], market.board_of(code),
                                  meta.get("is_st", False))
    if entry["open"] >= limit - 1e-6:
        return {"status": "rejected", "reason": "opens_limit_up",
                "date": entry["date"], "open": entry["open"], "limit_up": limit}

    budget = config.CAPITAL_CNY * config.POSITION_PCT
    shares = math.floor(budget / entry["open"] / config.LOT_SIZE) * config.LOT_SIZE
    if shares == 0:
        return {"status": "rejected", "reason": "one_lot_exceeds_position_limit",
                "date": entry["date"], "open": entry["open"]}

    buy_notional = shares * entry["open"]
    fill = {"status": "filled", "code": code, "entry_date": entry["date"],
            "entry_price": entry["open"], "shares": shares,
            "buy_fees": _fees(buy_notional, "buy"),
            "exit_date": None, "exit_price": None, "sell_fees": None,
            "pnl_cny": None, "return_pct": None}

    if len(after) > config.HOLD_DAYS:
        exit_bar = after[config.HOLD_DAYS]
        sell_notional = shares * exit_bar["close"]
        fill.update(exit_date=exit_bar["date"], exit_price=exit_bar["close"],
                    sell_fees=_fees(sell_notional, "sell"))
        pnl = sell_notional - buy_notional - fill["buy_fees"] - fill["sell_fees"]
        fill.update(pnl_cny=round(pnl, 2),
                    return_pct=round(100 * pnl / buy_notional, 3))
    return fill


def simulate_at(code, trigger_time):
    """Buy at the first open strictly after trigger_time ("YYYY-MM-DD HH:MM:SS").
    A filing before 09:30 on a trading day enters that day's open; anything
    later enters the next trading day's open."""
    day, hhmm = trigger_time[:10], trigger_time[11:16]
    bars = store.bars(code)
    nxt = next((b for b in bars if b["date"] > day or (b["date"] == day and hhmm < "09:30")), None)
    if nxt is None:
        return {"status": "rejected", "reason": "no_bar_after_trigger"}
    prev = [b for b in bars if b["date"] < nxt["date"]]
    return simulate(code, prev[-1]["date"] if prev else day)
