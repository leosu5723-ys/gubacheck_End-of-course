"""
GubaCheck - CANDIDATE SPIKE DAYS FROM THE POPULARITY RANK
=========================================================================
    python3 -m pipeline.candidates

Reads data/raw/hot_rank.jsonl (Eastmoney's daily popularity rank, about
one year per stock) and writes data/candidate_days.json: the days whose
forum posts must be collected.

A day is an attention jump when (thresholds in RULES.md / config.py):
    rank_today <= SPIKE_MAX_RANK
    median(rank over the previous SPIKE_BASELINE_DAYS days) / rank_today
        >= SPIKE_RANK_RATIO
Only the FIRST day of an episode counts: a jump within EPISODE_GAP_DAYS
trading days of a previous jump belongs to the same episode.

Why the rank and not a post count: counting posts means paging through
every post of the year (tens of thousands of requests for the busiest
stocks), which the site does not allow. The rank is one request per
stock and is Eastmoney's own measure of attention.
=========================================================================
"""
import json
import os
import statistics
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config  # noqa: E402


def attention_jumps():
    """{code: [{"date", "rank", "baseline_rank", "rank_ratio"}]}, first day of each episode."""
    by = defaultdict(list)
    with open(os.path.join(ROOT, "data", "raw", "hot_rank.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            by[r["stock"]].append(r)
    out = {}
    for code, rows in by.items():
        rows.sort(key=lambda r: r["date"])
        ranks = [r["rank"] for r in rows]
        jumps, last_i = [], -10**9
        for i in range(config.SPIKE_BASELINE_DAYS, len(rows)):
            base = statistics.median(ranks[i - config.SPIKE_BASELINE_DAYS:i])
            ratio = base / ranks[i]
            if ranks[i] <= config.SPIKE_MAX_RANK and ratio >= config.SPIKE_RANK_RATIO:
                if i - last_i > config.EPISODE_GAP_DAYS:
                    jumps.append({"date": rows[i]["date"], "rank": ranks[i],
                                  "baseline_rank": base, "rank_ratio": round(ratio, 2)})
                last_i = i
        out[code] = jumps
    return out


def main():
    jumps = attention_jumps()
    days = {c: [j["date"] for j in js] for c, js in jumps.items()}
    with open(os.path.join(ROOT, "data", "candidate_days.json"), "w", encoding="utf-8") as fh:
        json.dump(days, fh, ensure_ascii=False, indent=1)
    for c, js in jumps.items():
        print("%s  %2d episodes  %s" % (c, len(js), ", ".join(j["date"][5:] for j in js[:8])))
    print("total candidate days:", sum(len(v) for v in days.values()))


if __name__ == "__main__":
    main()
