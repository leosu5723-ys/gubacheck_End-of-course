"""
GubaCheck - FORWARD-WATCH BACKTEST (RULES.md section 2)
=========================================================================
    python3 -m pipeline.backtest [text|rag]

Strategies, on the same prices, costs and calendar:
    S0 naive chase      every spike -> buy at the next trading-day open
    S1 GubaCheck        spike -> watch D..D+10 trading days -> buy after the
                        FIRST announcement judged bullish
    S2 announcements    every announcement judged bullish (whole year,
                        all ten stocks), no spike needed
    S3 no trade         return 0

Entry: the first open strictly after the trigger time. A filing published
at 20:42 on day t enters at the open of t+1; one published before 09:30
on a trading day enters that day's open. Entry days that are suspended or
open at limit-up are skipped and counted ("not tradeable").
Exit: close of trading day +h after entry, for every h in EXIT_HORIZONS.
Returns are net of commission (min 5 CNY), transfer fee and sell-side
stamp duty, on one position of 10% of capital (or one lot if dearer).
Excess return = stock net return - CSI 300 return over the same span.

All seven horizons are reported. Nothing is tuned on these results.
Output: results/backtest_<mode>.json and results/backtest_trades_<mode>.csv
=========================================================================
"""
import csv
import json
import math
import os
import random
import statistics
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config, market, paper_broker  # noqa: E402
from pipeline import judge  # noqa: E402


def load_prices():
    bars = {}
    for l in open(os.path.join(ROOT, "data", "raw", "prices.jsonl"), encoding="utf-8"):
        b = json.loads(l)
        bars.setdefault(b["stock"], {})[b["date"]] = b
    idx = {r["date"]: r for r in json.load(open(os.path.join(ROOT, "data", "raw", "csi300.json")))}
    calendar = sorted(idx)
    return bars, idx, calendar


def entry_day(trigger_time, calendar):
    """First trading day whose 09:30 open is strictly after trigger_time."""
    day, hhmm = trigger_time[:10], trigger_time[11:16]
    for d in calendar:
        if d > day or (d == day and hhmm < "09:30"):
            return d
    return None


def trade(code, trigger_time, bars, idx, calendar, meta):
    d = entry_day(trigger_time, calendar)
    if d is None:
        return {"status": "no_entry_day"}
    bar = bars.get(code, {}).get(d)
    if bar is None:
        return {"status": "suspended", "entry_date": d}
    lim = market.limit_up_price(bar["prev_close"], market.board_of(code), meta.get("is_st", False))
    if bar["open"] >= lim - 1e-6:
        return {"status": "opens_limit_up", "entry_date": d}
    i = calendar.index(d)
    shares = max(config.LOT_SIZE, math.floor(config.CAPITAL_CNY * config.POSITION_PCT / bar["open"]
                                               / config.LOT_SIZE) * config.LOT_SIZE)
    cost = shares * bar["open"]
    buy_fee = paper_broker._fees(cost, "buy")
    out = {"status": "filled", "entry_date": d, "entry_price": bar["open"], "returns": {}, "excess": {}}
    for h in config.EXIT_HORIZONS:
        if i + h >= len(calendar):
            continue
        xd = calendar[i + h]
        xb = bars.get(code, {}).get(xd)
        if xb is None:                      # suspended on the exit day: use the last close before it
            prior = [bars[code][c] for c in calendar[i:i + h + 1] if c in bars.get(code, {})]
            xb = prior[-1]
        proceeds = shares * xb["close"]
        net = (proceeds - paper_broker._fees(proceeds, "sell") - cost - buy_fee) / cost
        bench = idx[xd]["close"] / idx[d]["open"] - 1
        out["returns"][h] = round(100 * net, 3)
        out["excess"][h] = round(100 * (net - bench), 3)
    return out


def summarise(trades):
    filled = [t for t in trades if t["status"] == "filled"]
    res = {"signals": len(trades), "filled": len(filled),
           "not_tradeable": {s: sum(t["status"] == s for t in trades)
                             for s in ("opens_limit_up", "suspended", "no_entry_day")},
           "horizons": {}}
    rng = random.Random(6201)
    for h in config.EXIT_HORIZONS:
        r = [t["returns"][h] for t in filled if h in t["returns"]]
        x = [t["excess"][h] for t in filled if h in t["excess"]]
        if not r:
            continue
        boots = sorted(statistics.mean(rng.choice(x) for _ in x) for _ in range(2000))
        res["horizons"]["+%d" % h] = {
            "n": len(r), "mean_net_pct": round(statistics.mean(r), 3),
            "median_net_pct": round(statistics.median(r), 3),
            "win_rate": round(sum(v > 0 for v in r) / len(r), 3),
            "mean_excess_pct": round(statistics.mean(x), 3),
            "excess_ci95": [round(boots[50], 3), round(boots[1949], 3)],
            "excess_win_rate": round(sum(v > 0 for v in x) / len(x), 3)}
    return res


def main(mode="rag"):
    bars, idx, calendar = load_prices()
    meta = json.load(open(os.path.join(ROOT, "data", "snapshot", "stocks.json"), encoding="utf-8"))
    spikes = json.load(open(os.path.join(ROOT, "data", "snapshot", "spikes.json"), encoding="utf-8"))
    anns = judge.load_announcements()
    labels = judge.all_judgements(mode)
    bullish = sorted([a for a in anns if labels.get(a["ann_id"]) == "bullish"], key=lambda a: a["time"])

    rows, strategies = [], {"S0_naive_chase": [], "S1_gubacheck": [], "S2_announcements_only": []}
    for s in spikes:
        code, d = s["stock"], s["date"]
        t0 = trade(code, d + " 15:00:00", bars, idx, calendar, meta.get(code, {}))
        strategies["S0_naive_chase"].append(t0)
        rows.append(dict(strategy="S0", spike=s["spike_id"], trigger=d, **_flat(t0)))
        start = next((i for i, c in enumerate(calendar) if c >= d), None)
        end_day = calendar[min(start + config.WATCH_TRADING_DAYS, len(calendar) - 1)] if start is not None else d
        first = next((a for a in bullish if a["stock"] == code and d + " 00:00:00" <= a["time"] <= end_day + " 15:00:00"), None)
        if first is None:
            rows.append(dict(strategy="S1", spike=s["spike_id"], trigger="no bullish filing in window", status="no_signal"))
            continue
        t1 = trade(code, first["time"], bars, idx, calendar, meta.get(code, {}))
        t1["ann_id"] = first["ann_id"]
        strategies["S1_gubacheck"].append(t1)
        rows.append(dict(strategy="S1", spike=s["spike_id"], trigger=first["time"], ann_id=first["ann_id"],
                         title=first["title"], **_flat(t1)))
    for a in bullish:
        t2 = trade(a["stock"], a["time"], bars, idx, calendar, meta.get(a["stock"], {}))
        strategies["S2_announcements_only"].append(t2)
        rows.append(dict(strategy="S2", trigger=a["time"], ann_id=a["ann_id"], title=a["title"], **_flat(t2)))

    report = {"judge_mode": mode, "spikes": len(spikes), "bullish_filings_in_year": len(bullish),
              "s1_spikes_without_bullish_filing": sum(1 for r in rows if r.get("status") == "no_signal"),
              "strategies": {k: summarise(v) for k, v in strategies.items()},
              "S3_no_trade": "0 by definition"}
    json.dump(report, open(os.path.join(ROOT, "results", "backtest_%s.json" % mode), "w"), indent=2, ensure_ascii=False)
    keys = sorted({k for r in rows for k in r})
    with open(os.path.join(ROOT, "results", "backtest_trades_%s.csv" % mode), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    for name, s in report["strategies"].items():
        print("\n%s  signals %d  filled %d  not tradeable %s" % (name, s["signals"], s["filled"], s["not_tradeable"]))
        for h, v in s["horizons"].items():
            print("   %4s n=%3d  net %6.2f%%  win %.0f%%  excess %6.2f%% CI %s"
                  % (h, v["n"], v["mean_net_pct"], 100 * v["win_rate"], v["mean_excess_pct"], v["excess_ci95"]))


def _flat(t):
    f = {"status": t["status"], "entry_date": t.get("entry_date"), "entry_price": t.get("entry_price")}
    for h in config.EXIT_HORIZONS:
        f["net_%d" % h] = t.get("returns", {}).get(h)
        f["excess_%d" % h] = t.get("excess", {}).get(h)
    return f


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "rag")
