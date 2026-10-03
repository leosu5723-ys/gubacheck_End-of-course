"""
GubaCheck - WHAT HAPPENED AFTER SPIKES OF EACH CAUSE (RULES.md 0.4)
=========================================================================
    python3 -m pipeline.cause_backtest [gold|keyword|exhaustive|agent|routing]

For every spike: enter at the open of the first trading day after the
spike day, exit at the close of trading day +1, +2, +3, +5, +10, +15, +20.
Net of commission, transfer fee and sell-side stamp duty; excess = stock
minus CSI 300 over the same span. Entries opening at limit-up are counted
as not tradeable.

Spikes are grouped by cause. The cause comes from:
  gold        my hand labels (evals/cause_labels.csv)    <- the report uses this
  <arm>       the primary cause concluded by that arm (results/results_<arm>*.json)

Two periods are reported separately: OBSERVE (spikes before 2026-04-01)
and CHECK (from 2026-04-01). A pattern seen in OBSERVE counts only if it
also appears in CHECK. Spike direction (bullish-share z above / below 0)
is reported as a second split.
=========================================================================
"""
import glob
import json
import os
import statistics
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config, store  # noqa: E402
from pipeline import backtest  # noqa: E402


def causes_from(source):
    if source == "gold":
        from pipeline.v4_scripts import hand_labels
        return {k: v["primary"] for k, v in hand_labels().items()}
    files = sorted(glob.glob(os.path.join(ROOT, "results", "results_%s*.json" % source)))
    if not files:
        raise SystemExit("no results for arm %s" % source)
    res = json.load(open(files[-1], encoding="utf-8"))["results"]
    return {r["case_id"]: r["record"].get("primary") for r in res}


def stats(trades):
    out = {}
    for h in config.EXIT_HORIZONS:
        x = [t["excess"][h] for t in trades if h in t.get("excess", {})]
        r = [t["returns"][h] for t in trades if h in t.get("returns", {})]
        if x:
            out["+%d" % h] = {"n": len(x), "mean_net_pct": round(statistics.mean(r), 2),
                              "mean_excess_pct": round(statistics.mean(x), 2),
                              "excess_win_rate": round(sum(v > 0 for v in x) / len(x), 2)}
    return out


def main(source="gold"):
    bars, idx, cal = backtest.load_prices()
    meta = store.load("stocks")
    cause = causes_from(source)
    groups = defaultdict(lambda: defaultdict(list))
    rows = []
    for s in store.load("spikes"):
        if s.get("synthetic") or s["spike_id"] not in cause:
            continue
        t = backtest.trade(s["stock"], s["date"] + " 15:00:00", bars, idx, cal, meta.get(s["stock"], {}))
        if t["status"] != "filled":
            continue
        c = cause[s["spike_id"]] or "H"
        per = "observe" if s["date"] < "2026-04-01" else "check"
        direction = "bullish" if (s.get("z_bull") or 0) > 0 else "bearish"
        for key in ("all", per, direction):
            groups[c][key].append(t)
            groups["ALL"][key].append(t)
        rows.append({"spike_id": s["spike_id"], "cause": c, "period": per, "direction": direction,
                     "excess": t["excess"], "returns": t["returns"]})
    report = {"cause_source": source, "spikes": len(rows),
              "by_cause": {c: {k: dict(n=len(v), **{"horizons": stats(v)}) for k, v in g.items()}
                           for c, g in sorted(groups.items())}}
    json.dump(report, open(os.path.join(ROOT, "results", "cause_backtest_%s.json" % source), "w"), indent=1)
    json.dump(rows, open(os.path.join(ROOT, "results", "cause_backtest_rows_%s.json" % source), "w"), indent=1)
    for c, g in sorted(groups.items()):
        h = g["all"] and stats(g["all"])
        line = "  ".join("%s %+.1f%%" % (k, v["mean_excess_pct"]) for k, v in h.items())
        print("%-4s n=%2d (observe %d / check %d)  excess: %s" % (c, len(g["all"]), len(g.get("observe", [])),
                                                                 len(g.get("check", [])), line))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gold")
