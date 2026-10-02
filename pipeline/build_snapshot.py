"""
GubaCheck - BUILD THE FROZEN SNAPSHOT AND DETECT SPIKES
=========================================================================
    python3 -m pipeline.build_snapshot 2025-10-03 2026-09-30

Turns data/raw/ into data/snapshot/*.json (the only files the agent's
tools read) and writes the work queue spikes.json.

Sentiment per post: the fine-tuned RoBERTa labels in
data/raw/sentiment_bert_<code>.jsonl if present, otherwise the TF-IDF
model (results/sentiment_model.pkl). Only posts from the stock's own bar
are used (true bar codes restored by pipeline/import_guba.py).

Spike rule (RULES.md section 1; thresholds in core/config.py):
    posts_today      >= SPIKE_HEAT_RATIO x mean(posts, previous 20 days)
    bull_share_today >= mean(bull_share, previous 20 days) + SPIKE_BULL_SHIFT
    posts_today      >= SPIKE_MIN_POSTS, and >= SPIKE_MIN_HISTORY prior days
    first day of an episode (no spike in the previous EPISODE_GAP_DAYS days)
bull_share = bullish / (bullish + bearish) posts that day.

Also writes:
    data/snapshot/daily_stats.json    posts, bullish, bearish, rank per stock-day
    results/spike_validation.json     agreement with Eastmoney's popularity
                                      rank: Spearman correlation of daily
                                      post count vs popularity, and how many
                                      forum spikes fall near a rank jump
Sample posts attached to a spike: the 10 most-read posts of that day.
=========================================================================
"""
import json
import os
import pickle
import statistics
import sys
from collections import defaultdict
from datetime import date

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


def _dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)


def _ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return round(cov / (va * vb), 3) if va and vb else None


def load_posts(code, date_from, date_to):
    """Own-bar posts in the window, each with a sentiment label."""
    posts = [p for p in _jsonl("guba_%s.jsonl" % code)
             if p.get("bar_code") == code and date_from <= p["time"][:10] <= date_to]
    bert = {r["post_id"]: r["label"] for r in _jsonl("sentiment_bert_%s.jsonl" % code)}
    if bert:
        for p in posts:
            p["sentiment"] = bert.get(p["post_id"], "neutral")
        return posts, "bert_finetuned"
    with open(sentiment.MODEL_PATH, "rb") as fh:
        model = pickle.load(fh)
    for p, lab in zip(posts, model.predict([p["title"] for p in posts])):
        p["sentiment"] = lab
    return posts, "tfidf_lr"


def detect(days):
    """days: sorted list of (date, n, bull_share). Returns spike records."""
    out, last = [], None
    for i, (d, n, share) in enumerate(days):
        base = days[max(0, i - config.SPIKE_BASELINE_DAYS):i]
        if len(base) < config.SPIKE_MIN_HISTORY:
            continue
        base_n = statistics.mean(b[1] for b in base)
        base_share = statistics.mean(b[2] for b in base)
        if (n >= config.SPIKE_MIN_POSTS and n >= config.SPIKE_HEAT_RATIO * base_n
                and share >= base_share + config.SPIKE_BULL_SHIFT):
            if last is None or (date.fromisoformat(d) - date.fromisoformat(last)).days > config.EPISODE_GAP_DAYS:
                out.append({"date": d, "posts": n, "baseline_posts": round(base_n, 1),
                            "heat_ratio": round(n / base_n, 2), "bull_share": round(share, 3),
                            "baseline_bull_share": round(base_share, 3)})
            last = d
    return out


def main(date_from, date_to):
    with open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8") as fh:
        watch = {w["code"]: w for w in json.load(fh)}
    rank_jumps = candidates.attention_jumps()
    ranks = defaultdict(dict)
    for r in _jsonl("hot_rank.jsonl"):
        ranks[r["stock"]][r["date"]] = r["rank"]

    spikes, sample_posts, daily_stats, validation, source = [], [], {}, {}, None
    for code in watch:
        posts, source = load_posts(code, date_from, date_to)
        by_day = defaultdict(list)
        for p in posts:
            by_day[p["time"][:10]].append(p)
        days = []
        for d in sorted(by_day):
            ps = by_day[d]
            bull = sum(p["sentiment"] == "bull" for p in ps)
            bear = sum(p["sentiment"] == "bear" for p in ps)
            days.append((d, len(ps), bull / (bull + bear) if bull + bear else 0.5))
            daily_stats.setdefault(code, []).append({"date": d, "posts": len(ps), "bull": bull,
                                                     "bear": bear, "rank": ranks[code].get(d)})
        found = detect(days)
        for s in found:
            ps = sorted(by_day[s["date"]], key=lambda p: -p.get("reads", 0))[:10]
            sample_posts += [{"post_id": p["post_id"], "stock": code, "time": p["time"],
                              "title": p["title"], "sentiment": p["sentiment"]} for p in ps]
            spikes.append(dict({"spike_id": "SPK-%s-%s" % (code, s["date"].replace("-", "")),
                                "stock": code, "rank": ranks[code].get(s["date"]),
                                "sample_post_ids": [p["post_id"] for p in ps]}, **s))

        both = [(r["posts"], -r["rank"]) for r in daily_stats[code] if r["rank"]]
        jump_days = {j["date"] for j in rank_jumps.get(code, [])}
        near = sum(1 for s in found if any(abs((date.fromisoformat(s["date"]) - date.fromisoformat(j)).days) <= 2
                                           for j in jump_days))
        validation[code] = {"spearman_posts_vs_popularity": spearman([a for a, _ in both], [b for _, b in both]),
                            "forum_spikes": len(found), "rank_jump_episodes": len(jump_days),
                            "forum_spikes_within_2d_of_rank_jump": near}
        print("%s %-6s posts %7d  spikes %2d  rank-jumps %2d  overlap %2d  spearman %s"
              % (code, watch[code]["name"], len(posts), len(found), len(jump_days), near,
                 validation[code]["spearman_posts_vs_popularity"]))

    _dump(os.path.join(SNAP, "spikes.json"), spikes)
    _dump(os.path.join(SNAP, "posts.json"), sample_posts)
    _dump(os.path.join(SNAP, "daily_stats.json"), daily_stats)
    _dump(os.path.join(SNAP, "cninfo.json"), [a for a in _jsonl("cninfo.jsonl") if a["stock"] in watch])
    _dump(os.path.join(SNAP, "news.json"), _jsonl("news.jsonl"))
    prices = defaultdict(list)
    for b in _jsonl("prices.jsonl"):
        if b["stock"] in watch:
            prices[b["stock"]].append({k: b[k] for k in
                                       ("date", "open", "close", "high", "low", "pct_chg", "prev_close")})
    _dump(os.path.join(SNAP, "prices.json"), prices)
    _dump(os.path.join(SNAP, "stocks.json"), {c: {"name": w["name"], "aliases": w.get("aliases", []),
                                                  "is_st": w.get("is_st", False)} for c, w in watch.items()})
    _dump(os.path.join(ROOT, "results", "spike_validation.json"),
          {"sentiment_source": source, "window": [date_from, date_to], "stocks": validation})
    print("spikes total %d (sentiment: %s)" % (len(spikes), source))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
