"""
GubaCheck - FROZEN CONTEXT FOR THE CAUSE TOOLS
=========================================================================
    python3 -m pipeline.context_snapshot

Writes into data/snapshot/ everything the seven cause tools read, so they
run offline and identically for a marker:

  prices.json        daily bars: the 10 watched stocks and their A-share peers
  us_prices.json     US peers, daily close and return
  indices.json       CSI 300 and ChiNext daily closes
  toplist.json       exchange top-list (龙虎榜) rows for the watched stocks, plus
                     the market-wide distribution of |net buy| / turnover
  announcements.json filings with exact time, type, procedural flag
  judgements.json    the RAG judge's label and reason per filing
  articles.json      article-type forum posts (post_type 20) of each watched
                     stock from 3 days before to the end of each spike day
  peers.json         peer groups and US peers
=========================================================================
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import judge  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")
SNAP = os.path.join(ROOT, "data", "snapshot")


def _jsonl(name):
    p = os.path.join(RAW, name)
    return [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []


def dump(name, obj):
    json.dump(obj, open(os.path.join(SNAP, name + ".json"), "w", encoding="utf-8"), ensure_ascii=False)


def main():
    watch = [w["code"] for w in json.load(open(os.path.join(ROOT, "data", "watchlist.json")))]
    peers = json.load(open(os.path.join(ROOT, "data", "peers.json")))
    codes = set(watch) | {c for g in peers["groups"].values() for c in g["extra_peers"]}
    prices = defaultdict(dict)
    for b in _jsonl("prices.jsonl"):
        if b["stock"] in codes:
            prices[b["stock"]][b["date"]] = {k: b[k] for k in ("date", "open", "close", "high", "low", "pct_chg", "prev_close")}
    dump("prices", {c: sorted(v.values(), key=lambda b: b["date"]) for c, v in prices.items()})
    us = defaultdict(list)
    for r in _jsonl("us_prices.jsonl"):
        us[r["ticker"]].append({"date": r["date"], "ret": r["ret"]})
    dump("us_prices", us)
    dump("indices", {"CSI300": json.load(open(os.path.join(RAW, "csi300.json"))),
                     "ChiNext": json.load(open(os.path.join(RAW, "chinext.json")))})
    tl = _jsonl("toplist.jsonl")
    ratios = sorted(abs(r["net_buy"]) / r["turnover"] for r in tl if r["turnover"])
    dump("toplist", {"rows": [r for r in tl if r["stock"] in watch], "market_abs_netbuy_ratio_sorted": ratios[::max(1, len(ratios) // 2000)]})
    rows = judge.load_announcements()
    dump("announcements", [{"ann_id": r["ann_id"], "stock": r["stock"], "name": r["name"], "title": r["title"],
                            "time": r["time"], "type": r["type"], "procedural": r["procedural"]} for r in rows])
    jud = {}
    for l in open(os.path.join(RAW, "judgements_rag.jsonl"), encoding="utf-8"):
        r = json.loads(l)
        jud[r["ann_id"]] = {"label": r["label"], "reason": r["reason"]}
    dump("judgements", jud)
    spikes = json.load(open(os.path.join(SNAP, "spikes.json"), encoding="utf-8"))
    arts = []
    for code in watch:
        days = [s["date"] for s in spikes if s["stock"] == code]
        if not days:
            continue
        lo = {d: (date.fromisoformat(d) - timedelta(days=3)).isoformat() for d in days}
        for l in open(os.path.join(RAW, "guba_%s.jsonl" % code), encoding="utf-8"):
            p = json.loads(l)
            if p.get("bar_code") != code or p.get("post_type") != 20:
                continue
            day = p["time"][:10]
            if any(lo[d] <= day <= d for d in days):
                arts.append({"post_id": p["post_id"], "stock": code, "time": p["time"], "title": p["title"],
                             "reads": p.get("reads", 0)})
    dump("articles", arts)
    # daily counts of company-specific articles over the whole year, for cause B's z-score
    import re as _re
    from core.causes import MARKET_WRAP, POLICY
    meta = {w["code"]: [w["name"]] + w.get("aliases", []) for w in json.load(open(os.path.join(ROOT, "data", "watchlist.json")))}
    counts = {}
    for code in watch:
        c = defaultdict(int)
        for l in open(os.path.join(RAW, "guba_%s.jsonl" % code), encoding="utf-8"):
            p = json.loads(l)
            if p.get("bar_code") == code and p.get("post_type") == 20 and any(n in p["title"] for n in meta[code]) \
                    and not MARKET_WRAP.search(p["title"]) and not POLICY.search(p["title"]):
                c[p["time"][:10]] += 1
        counts[code] = c
    dump("article_daily_counts", counts)
    dump("peers", peers["groups"])
    print("prices", len(prices), "us", len(us), "toplist rows", sum(r["stock"] in watch for r in tl),
          "articles", len(arts), "judgements", len(jud))


if __name__ == "__main__":
    main()
