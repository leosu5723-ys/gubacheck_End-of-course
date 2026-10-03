"""
GubaCheck - ONE ANOMALY ENGINE (z-scores against the series' own history)
=========================================================================
    python3 -m pipeline.anomaly          detect v4 spikes -> data/snapshot/spikes.json

Every "is this abnormal?" question in GubaCheck goes through `zscore()`:
the value is compared with the same series' previous Z_WINDOW observations
(120 trading days), never including the day itself. No fixed percentage
thresholds anywhere (RULES.md section 0.1).

Spike (v4): log(1 + own-bar posts) z >= Z_POSTS (no direction condition;
the bullish-share z is recorded), first day of an episode (no spike in
the previous 5 days). At least Z_MIN_OBS days of history are required.
Only trading days are scored; weekend posts roll into Monday's history
through the trading-day calendar (CSI 300 dates).

Onset: the first hour of the spike day (or of the evening before, from
15:00) whose post count is abnormal (z >= Z_ABNORMAL) against the same
clock hour on the previous 120 trading days. Evidence for a cause must
predate the onset (RULES.md 0.2).
=========================================================================
"""
import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")
SNAP = os.path.join(ROOT, "data", "snapshot")


def zscore(history, value, min_obs=None):
    """z of `value` against `history` (list of numbers, today excluded).
    Returns None when the history is too short or has no spread."""
    min_obs = config.Z_MIN_OBS if min_obs is None else min_obs
    h = [x for x in history if x is not None][-config.Z_WINDOW:]
    if len(h) < min_obs:
        return None
    sd = statistics.pstdev(h)
    return round((value - statistics.mean(h)) / sd, 3) if sd > 0 else None


def percentile(history, value, min_obs=20):
    h = [x for x in history if x is not None][-config.Z_WINDOW:]
    if len(h) < min_obs:
        return None
    return round(100 * sum(1 for x in h if x <= value) / len(h), 1)


def calendar():
    return sorted(r["date"] for r in json.load(open(os.path.join(RAW, "csi300.json"))))


def series_z(values_by_date, cal, day):
    """z of values_by_date[day] against the previous trading days in cal."""
    if day not in values_by_date:
        return None
    i = cal.index(day)
    hist = [values_by_date.get(d) for d in cal[max(0, i - config.Z_WINDOW):i]]
    return zscore(hist, values_by_date[day])


def load_posts(code):
    sent = {json.loads(l)["post_id"]: json.loads(l)["label"]
            for l in open(os.path.join(RAW, "sentiment_bert_%s.jsonl" % code), encoding="utf-8")}
    out = []
    for l in open(os.path.join(RAW, "guba_%s.jsonl" % code), encoding="utf-8"):
        p = json.loads(l)
        if p.get("bar_code") == code:
            p["sentiment"] = sent.get(p["post_id"], "neutral")
            out.append(p)
    return out


def trading_day_of(ts, cal):
    """Posts after 15:00 or on non-trading days belong to the next trading day."""
    d, hm = ts[:10], ts[11:16]
    for c in cal:
        if c > d or (c == d and hm < "15:00"):
            return c
    return None


def daily(code, cal):
    posts = load_posts(code)
    by_day = defaultdict(list)
    for p in posts:
        td = trading_day_of(p["time"], cal)
        if td:
            by_day[td].append(p)
    stats = {}
    for d, ps in by_day.items():
        bull = sum(p["sentiment"] == "bull" for p in ps)
        bear = sum(p["sentiment"] == "bear" for p in ps)
        stats[d] = {"posts": len(ps), "logp": math.log1p(len(ps)),
                    "share": bull / (bull + bear) if bull + bear else 0.5}
    return stats, by_day


def onset(code, day, by_day, cal):
    """First abnormal hour in the window (previous trading day 15:00 .. day 15:00)."""
    i = cal.index(day)
    hist_days = cal[max(0, i - config.Z_WINDOW):i]

    def hour_key(ts):
        return ts[11:13]
    per_hour_hist = defaultdict(list)
    for d in hist_days:
        cnt = defaultdict(int)
        for p in by_day.get(d, []):
            cnt[hour_key(p["time"])] += 1
        for h in ["%02d" % k for k in range(24)]:
            per_hour_hist[h].append(cnt.get(h, 0))
    today = sorted(by_day.get(day, []), key=lambda p: p["time"])
    cnt = defaultdict(int)
    for p in today:
        cnt[(p["time"][:10], hour_key(p["time"]))] += 1
    for (d, h), n in sorted(cnt.items()):
        z = zscore(per_hour_hist[h], n)
        if z is not None and z >= config.Z_ABNORMAL:
            return "%s %s:00:00" % (d, h)
    return day + " 09:30:00"


def detect():
    cal = calendar()
    watch = json.load(open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8"))
    spikes, daily_out = [], {}
    for w in watch:
        code = w["code"]
        stats, by_day = daily(code, cal)
        logp = {d: s["logp"] for d, s in stats.items()}
        share = {d: s["share"] for d, s in stats.items()}
        last = None
        daily_out[code] = []
        for d in cal:
            if d not in stats:
                continue
            zp, zs = series_z(logp, cal, d), series_z(share, cal, d)
            daily_out[code].append({"date": d, "posts": stats[d]["posts"], "bull_share": round(stats[d]["share"], 3),
                                    "z_posts": zp, "z_bull": zs})
            if zp is None or zp < config.Z_POSTS:
                continue
            if config.Z_BULL is not None and (zs is None or zs < config.Z_BULL):
                continue
            if last and (date.fromisoformat(d) - date.fromisoformat(last)).days <= config.EPISODE_GAP_DAYS:
                last = d
                continue
            last = d
            top = sorted(by_day[d], key=lambda p: -p.get("reads", 0))[:15]
            spikes.append({"spike_id": "SPK-%s-%s" % (code, d.replace("-", "")), "stock": code, "date": d,
                           "posts": stats[d]["posts"], "z_posts": zp, "bull_share": round(stats[d]["share"], 3),
                           "z_bull": zs, "onset": onset(code, d, by_day, cal),
                           "sample_post_ids": [p["post_id"] for p in top],
                           "_sample": [{"post_id": p["post_id"], "stock": code, "time": p["time"], "title": p["title"],
                                        "post_type": p.get("post_type"), "reads": p.get("reads"),
                                        "sentiment": p["sentiment"]} for p in top]})
    return spikes, daily_out


def main():
    spikes, daily_out = detect()
    posts = [p for s in spikes for p in s.pop("_sample")]
    json.dump(spikes, open(os.path.join(SNAP, "spikes.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(posts, open(os.path.join(SNAP, "posts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(daily_out, open(os.path.join(SNAP, "daily_stats.json"), "w", encoding="utf-8"), ensure_ascii=False)
    from collections import Counter
    print("v4 spikes:", len(spikes), dict(Counter(s["stock"] for s in spikes)))
    print("before 2026-04-01:", sum(s["date"] < "2026-04-01" for s in spikes), "| from 2026-04-01:",
          sum(s["date"] >= "2026-04-01" for s in spikes))


if __name__ == "__main__":
    main()
