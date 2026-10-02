"""
GubaCheck - BUILD THE FROZEN SNAPSHOT AND DETECT SPIKES
=========================================================================
    python3 -m pipeline.build_snapshot 2026-07-01 2026-09-30

Turns data/raw/*.jsonl into data/snapshot/*.json (the only files the
agent's tools read), and writes the work queue spikes.json.

Spike rule (thresholds from RULES.md, fixed before results were seen):
    posts_today      >= SPIKE_HEAT_RATIO x mean(posts, previous 20 days)
    bull_share_today >= mean(bull_share, previous 20 days) + SPIKE_BULL_SHIFT
    posts_today      >= SPIKE_MIN_POSTS
bull_share = bullish posts / (bullish + bearish posts), using the trained
sentiment model; "uncertain" and neutral posts are not counted.

List pages also carry posts from other bars and site-promoted articles.
Dropped: bar_code naming another stock, and promoted posts (no bar_code,
post_type 20).

Sample posts attached to a spike: the 10 most-read posts of that day.
=========================================================================
"""
import json
import os
import pickle
import statistics
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config  # noqa: E402
from pipeline import sentiment  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")
SNAP = os.path.join(ROOT, "data", "snapshot")


def _jsonl(name):
    path = os.path.join(RAW, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def _dump(name, obj):
    os.makedirs(SNAP, exist_ok=True)
    with open(os.path.join(SNAP, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def main(date_from, date_to):
    with open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8") as fh:
        watch = {w["code"]: w for w in json.load(fh)}

    posts = []
    for code in watch:
        for p in _jsonl("guba_%s.jsonl" % code):
            bar = p.get("bar_code")
            if bar not in (None, "", code):
                continue                      # another stock's bar
            if not bar and p.get("post_type") == 20:
                continue                      # site-promoted article, not this stock's forum

            if date_from <= p["time"][:10] <= date_to:
                posts.append(p)

    with open(sentiment.MODEL_PATH, "rb") as fh:
        model = pickle.load(fh)
    for p, (lab, prob) in zip(posts, sentiment.predict(model, [p["title"] for p in posts])):
        p["sentiment"], p["sentiment_p"] = lab, round(prob, 3)

    by_day = defaultdict(list)
    for p in posts:
        by_day[(p["stock"], p["time"][:10])].append(p)

    spikes, used_posts = [], set()
    for code in watch:
        days = sorted(d for (c, d) in by_day if c == code)
        hist = []
        for d in days:
            ps = by_day[(code, d)]
            bull = sum(p["sentiment"] == "bull" for p in ps)
            bear = sum(p["sentiment"] == "bear" for p in ps)
            share = bull / (bull + bear) if bull + bear else 0.5
            base = hist[-config.SPIKE_BASELINE_DAYS:]
            if len(base) >= 10:
                base_n = statistics.mean(h[0] for h in base)
                base_share = statistics.mean(h[1] for h in base)
                if (len(ps) >= config.SPIKE_MIN_POSTS
                        and len(ps) >= config.SPIKE_HEAT_RATIO * base_n
                        and share >= base_share + config.SPIKE_BULL_SHIFT):
                    sample = sorted(ps, key=lambda p: -p.get("reads", 0))[:10]
                    used_posts.update(p["post_id"] for p in sample)
                    spikes.append({"spike_id": "SPK-%s-%s" % (code, d.replace("-", "")),
                                   "stock": code, "date": d, "posts_today": len(ps),
                                   "baseline_posts": round(base_n, 1),
                                   "heat_ratio": round(len(ps) / base_n, 2) if base_n else None,
                                   "bull_share": round(share, 3),
                                   "baseline_bull_share": round(base_share, 3),
                                   "sample_post_ids": [p["post_id"] for p in sample]})
            hist.append((len(ps), share))

    _dump("spikes.json", spikes)
    _dump("posts.json", [{"post_id": p["post_id"], "stock": p["stock"], "time": p["time"],
                          "title": p["title"], "sentiment": p["sentiment"]}
                         for p in posts if p["post_id"] in used_posts])
    _dump("cninfo.json", [a for a in _jsonl("cninfo.jsonl") if a["stock"] in watch])
    _dump("news.json", _jsonl("news.jsonl"))
    prices = defaultdict(list)
    for b in _jsonl("prices.jsonl"):
        if b["stock"] in watch:
            prices[b["stock"]].append({k: b[k] for k in
                                       ("date", "open", "close", "high", "low", "pct_chg", "prev_close")})
    _dump("prices.json", prices)
    _dump("stocks.json", {c: {"name": w["name"], "aliases": w.get("aliases", []),
                              "is_st": w.get("is_st", False)} for c, w in watch.items()})

    daily = defaultdict(int)
    for (c, d), ps in by_day.items():
        daily[c] += len(ps)
    print("posts in window: %d | spikes detected: %d" % (len(posts), len(spikes)))
    for c in watch:
        n_days = len([1 for (cc, _) in by_day if cc == c])
        print("  %s %-6s posts/day %.0f  spikes %d" % (c, watch[c]["name"], daily[c] / max(n_days, 1),
                                                       sum(s["stock"] == c for s in spikes)))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
