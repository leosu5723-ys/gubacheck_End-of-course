"""
GubaCheck - DAILY COLLECTION
=========================================================================
    python3 -m collectors.daily

Run once a day after the close (cron, launchd or GitHub Actions). For
every stock in data/watchlist.json it pulls the last few days of forum
posts, announcements and prices, plus a snapshot of the news feeds.
The news feeds keep no history, so this daily run is what builds the
news archive over time.
=========================================================================
"""
import json
import os
from datetime import date, timedelta

from collectors import guba, market_data

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    with open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8") as fh:
        codes = [w["code"] for w in json.load(fh)]
    today = date.today()
    start = (today - timedelta(days=3)).isoformat()
    for code in codes:
        guba.collect(code, start, today.isoformat())
        market_data.cninfo(code, start, today.isoformat())
        market_data.prices(code, (today - timedelta(days=10)).isoformat(), today.isoformat())
    market_data.news(codes)


if __name__ == "__main__":
    main()
