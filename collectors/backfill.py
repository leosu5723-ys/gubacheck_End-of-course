"""
GubaCheck - ONE-OFF HISTORICAL BACKFILL
=========================================================================
    python3 -m collectors.backfill 2025-10-01 2026-09-30 [workers]

Collects the whole evaluation window for every stock in
data/watchlist.json: announcements and prices first (fast), one news
snapshot, then forum posts with a few stocks in parallel. Each forum
worker still waits 1.5 s between its own requests.

Resumable: re-running skips posts and rows already in data/raw/.
=========================================================================
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from collectors import guba, market_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(date_from, date_to, workers=3):
    with open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8") as fh:
        codes = [w["code"] for w in json.load(fh)]
    d0 = date.fromisoformat(date_from)
    for code in codes:
        # announcements from a month earlier, prices from two months earlier
        # (20-day baselines) to a month later (20-day holding period)
        market_data.cninfo(code, (d0 - timedelta(days=31)).isoformat(), date_to)
        market_data.prices(code, (d0 - timedelta(days=62)).isoformat(),
                           (date.fromisoformat(date_to) + timedelta(days=45)).isoformat())
    try:
        market_data.news(codes)
    except Exception as e:  # news is a bonus here; the daily job builds the archive
        print("news snapshot failed:", e)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda c: guba.collect(c, date_from, date_to, max_pages=20000), codes))
    print("BACKFILL DONE")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3)
