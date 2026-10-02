"""
GubaCheck - IMPORT THE FULL-YEAR FORUM DATASET
=========================================================================
    python3 -m pipeline.import_guba /path/to/guba

Reads the external full-year forum collection (10 stocks, 2025-10-03 to
2026-10-02) and writes data/raw/guba_<code>.jsonl in the project format.

Source layout (outside this repository, too large to commit):
    <guba>/十个股票的股吧数据/<code>_365days.jsonl   cleaned posts, 8 fields
    <guba>/原始数据与断点/<code>_raw_pages.jsonl     raw API pages

Why the raw pages are read too: in the cleaned files bar_code is set to
the target stock for every row, but a stock's list also carries posts
from other bars (reposts from other stocks, Eastmoney "cfhpl" articles).
The true source bar is restored from the raw pages so build_snapshot can
drop them.

Writes data/raw/guba_import_report.json: per stock, rows read, rows by
source bar, days covered, and days with zero posts.
=========================================================================
"""
import collections
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")


def true_bars(raw_path):
    """post_id -> stockbar_code from the raw API pages (streamed)."""
    bars = {}
    with open(raw_path, encoding="utf-8") as fh:
        for line in fh:
            for p in json.loads(line)["data"].get("re", []):
                bars[int(p["post_id"])] = p.get("stockbar_code")
    return bars


def main(src):
    with open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8") as fh:
        codes = [w["code"] for w in json.load(fh)]
    os.makedirs(RAW, exist_ok=True)
    report = {}
    for code in codes:
        clean = os.path.join(src, "十个股票的股吧数据", "%s_365days.jsonl" % code)
        raw = os.path.join(src, "原始数据与断点", "%s_raw_pages.jsonl" % code)
        bars = true_bars(raw)
        by_bar, per_day, n = collections.Counter(), collections.Counter(), 0
        with open(clean, encoding="utf-8") as fin, \
                open(os.path.join(RAW, "guba_%s.jsonl" % code), "w", encoding="utf-8") as fout:
            for line in fin:
                r = json.loads(line)
                r["bar_code"] = bars.get(int(r["post_id"]), r.get("bar_code"))
                by_bar[r["bar_code"] if r["bar_code"] == code else "other:" + str(r["bar_code"])] += 1
                per_day[r["time"][:10]] += 1
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                n += 1
        first = dt.date(2025, 10, 3)
        days = [(first + dt.timedelta(i)).isoformat() for i in range(365)]
        report[code] = {"rows": n, "own_bar": by_bar[code],
                        "other_bars": n - by_bar[code],
                        "top_other_bars": by_bar.most_common(4)[1:],
                        "days_with_posts": sum(1 for d in days if per_day[d]),
                        "zero_days": [d for d in days if not per_day[d]]}
        print("%s rows %7d  own bar %7d  other bars %6d  days %d"
              % (code, n, by_bar[code], n - by_bar[code], report[code]["days_with_posts"]))
    with open(os.path.join(RAW, "guba_import_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
