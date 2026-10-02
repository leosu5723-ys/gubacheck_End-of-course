"""
GubaCheck - EASTMONEY GUBA (stock forum) COLLECTOR
=========================================================================
    python3 -m collectors.guba range 600519 2026-09-20 2026-09-30   every post in a window
    python3 -m collectors.guba days                                 posts on candidate spike days

Pages through https://guba.eastmoney.com/list,<code>,f_<n>.html, which
lists a stock's posts newest-first by publish time (80 per page). Each
page embeds its list as JSON (`var article_list=...`).

Stored per post: post_id, stock, publish time, title, reads, comments,
post_type, bar_code. NOT stored: user ids, nicknames, IP region, bodies.

ACCESS POLICY. One request at a time, DELAY_S seconds apart. If the site
answers with its identity-check page ("身份核实"), the collector STOPS and
says so. It never tries to get around the check. (An earlier version
treated that page as "no more posts" and ended quietly with almost no
data - a silent failure, recorded in EVALS.md.)

"days" mode does not page through a whole year. For each candidate spike
day (from the popularity-rank history, see pipeline/candidates.py) it
locates the pages for that date with a cached binary search and reads at
most MAX_PAGES_PER_DAY pages of that day.
Output: data/raw/guba_<code>.jsonl
=========================================================================
"""
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Safari/605.1.15")
DELAY_S = 3.0
MAX_PAGES_PER_DAY = 4


class Blocked(Exception):
    """The site served its identity check. Stop; do not retry around it."""


_last = [0.0]


def fetch_page(code, page):
    wait = DELAY_S - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    url = "https://guba.eastmoney.com/list,%s,f_%d.html" % (code, page)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read().decode("utf-8", errors="replace")
    _last[0] = time.time()
    if "身份核实" in html:
        raise Blocked("identity check served at %s page %d" % (code, page))
    m = re.search(r"var article_list=(\{.*?\});\s*var", html, re.S)
    if not m:
        raise Blocked("unexpected page shape at %s page %d" % (code, page))
    return json.loads(m.group(1)).get("re", [])


def _row(code, p):
    return {"post_id": p["post_id"], "stock": code, "time": p["post_publish_time"],
            "title": p.get("post_title", ""), "reads": p.get("post_click_count", 0),
            "comments": p.get("post_comment_count", 0), "post_type": p.get("post_type"),
            "bar_code": p.get("stockbar_code")}


def _median_day(posts):
    t = sorted(p["post_publish_time"] for p in posts)
    return t[len(t) // 2][:10] if t else None


class _Writer:
    def __init__(self, code):
        os.makedirs(RAW, exist_ok=True)
        self.path = os.path.join(RAW, "guba_%s.jsonl" % code)
        self.seen, self.per_day = set(), {}
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    r = json.loads(line)
                    self.seen.add(r["post_id"])
                    self.per_day[r["time"][:10]] = self.per_day.get(r["time"][:10], 0) + 1
        self.fh = open(self.path, "a", encoding="utf-8")
        self.code, self.kept = code, 0

    def add(self, posts, keep=lambda day: True):
        for p in posts:
            if p["post_id"] in self.seen or not keep(p["post_publish_time"][:10]):
                continue
            self.seen.add(p["post_id"])
            self.fh.write(json.dumps(_row(self.code, p), ensure_ascii=False) + "\n")
            self.kept += 1
        self.fh.flush()


def collect(code, date_from, date_to, max_pages=20000):
    """Every post of `code` published in [date_from, date_to]."""
    w = _Writer(code)
    for page in range(1, max_pages + 1):
        posts = fetch_page(code, page)
        if not posts:
            break
        w.add(posts, lambda d: date_from <= d <= date_to)
        if _median_day(posts) < date_from:
            break
    print("%s: kept %d new posts" % (code, w.kept))
    return w.kept


def collect_days(code, days):
    """Posts of `code` on each date in `days`, newest date first."""
    w = _Writer(code)
    probes = {}                                   # page -> median day, shared across dates

    def day_at(page):
        if page not in probes:
            probes[page] = _median_day(fetch_page(code, page)) or "0000-00-00"
        return probes[page]

    for day in sorted(days, reverse=True):
        if w.per_day.get(day, 0) >= 30:          # collected in an earlier run
            continue
        # newest-first: find the first page whose median day is <= `day`
        known_newer = [p for p, d in probes.items() if d > day]
        lo = max(known_newer) if known_newer else 1
        hi = lo
        while day_at(hi) > day:
            lo, hi = hi, hi * 2
        while lo < hi:
            mid = (lo + hi) // 2
            if day_at(mid) > day:
                lo = mid + 1
            else:
                hi = mid
        start = max(1, lo - 1)
        for page in range(start, start + MAX_PAGES_PER_DAY + 1):
            posts = fetch_page(code, page)
            probes[page] = _median_day(posts) or "0000-00-00"
            w.add(posts, lambda d: d == day)
            if probes[page] < day:
                break
        print("  %s %s: total kept %d" % (code, day, w.kept))
    return w.kept


if __name__ == "__main__":
    try:
        if len(sys.argv) == 5 and sys.argv[1] == "range":
            collect(sys.argv[2], sys.argv[3], sys.argv[4])
        elif len(sys.argv) == 2 and sys.argv[1] == "days":
            with open(os.path.join(ROOT, "data", "candidate_days.json"), encoding="utf-8") as fh:
                todo = json.load(fh)
            for code, days in todo.items():
                collect_days(code, days)
            print("DAYS DONE")
        else:
            print(__doc__)
    except Blocked as b:
        print("STOPPED - %s. Wait and re-run later; collected data is kept and skipped." % b)
        sys.exit(2)
