"""
GubaCheck - BUILD THE FROZEN SNAPSHOT AND DETECT SPIKES
=========================================================================
    python3 -m pipeline.build_snapshot 2026-07-01 2026-09-30

Turns data/raw/*.jsonl into data/snapshot/*.json (the only files the
agent's tools read), and writes the work queue spikes.json.

Spike rule (thresholds from RULES.md, fixed before results were seen):
    stage 1  attention jump on the popularity rank (pipeline/candidates.py)
    stage 2  that day's collected posts: at least SPIKE_MIN_POSTS, and
             bullish / (bullish + bearish) >= SPIKE_BULL_SHARE_MIN
             (sentiment from the trained model; uncertain and neutral
             posts are not counted)

A stock's list also carries reposts from other bars and Eastmoney
articles; only posts whose true bar_code is this stock are kept (bar
codes restored by pipeline/import_guba.py).

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
from pipeline import candidates, sentiment  # noqa: E402

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
            if p.get("bar_code") != code:
                continue                      # repost from another bar or a site article

            if date_from <= p["time"][:10] <= date_to:
                posts.append(p)

    with open(sentiment.MODEL_PATH, "rb") as fh:
        model = pickle.load(fh)
    for p, (lab, prob) in zip(posts, sentiment.predict(model, [p["title"] for p in posts])):
        p["sentiment"], p["sentiment_p"] = lab, round(prob, 3)

    by_day = defaultdict(list)
    for p in posts:
        by_day[(p["stock"], p["time"][:10])].append(p)

    spikes, used_posts, rejected = [], set(), []
    for code, jumps in candidates.attention_jumps().items():
        if code not in watch:
            continue
        for j in jumps:
            if not (date_from <= j["date"] <= date_to):
                continue
            ps = by_day.get((code, j["date"]), [])
            bull = sum(p["sentiment"] == "bull" for p in ps)
            bear = sum(p["sentiment"] == "bear" for p in ps)
            share = bull / (bull + bear) if bull + bear else 0.0
            if len(ps) < config.SPIKE_MIN_POSTS or share < config.SPIKE_BULL_SHARE_MIN:
                rejected.append({"stock": code, "date": j["date"], "posts": len(ps),
                                 "bull_share": round(share, 3)})
                continue
            sample = sorted(ps, key=lambda p: -p.get("reads", 0))[:10]
            used_posts.update(p["post_id"] for p in sample)
            spikes.append({"spike_id": "SPK-%s-%s" % (code, j["date"].replace("-", "")),
                           "stock": code, "date": j["date"],
                           "rank": j["rank"], "baseline_rank": j["baseline_rank"],
                           "rank_ratio": j["rank_ratio"], "posts_collected": len(ps),
                           "bull_share": round(share, 3),
                           "sample_post_ids": [p["post_id"] for p in sample]})

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

    _dump("rejected_candidates.json", rejected)
    print("posts in window: %d | candidates: %d | spikes kept: %d | rejected: %d"
          % (len(posts), len(spikes) + len(rejected), len(spikes), len(rejected)))
    for c in watch:
        print("  %s %-6s spikes %d" % (c, watch[c]["name"], sum(s["stock"] == c for s in spikes)))
