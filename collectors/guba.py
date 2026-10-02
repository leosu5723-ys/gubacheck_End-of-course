"""
GubaCheck - EASTMONEY GUBA (stock forum) COLLECTOR
=========================================================================
    python3 -m collectors.guba 600519 2026-07-01 2026-09-30

Pages through https://guba.eastmoney.com/list,<code>,f_<n>.html, which
lists a stock's forum posts newest-first by publish time (about 80 per
page). Each page embeds its post list as JSON (`var article_list=...`),
so no HTML parsing is needed.

Stored per post: post_id, stock, publish time, title, read count, comment
count, post_type, bar_code. NOT stored: user ids, nicknames, IP region,
post body. The project needs what was said and when, not who said it.

Politeness: one request every 1.5 s, a plain browser user-agent, stop as
soon as the window is covered. Output: data/raw/guba_<code>.jsonl.
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
DELAY_S = 1.5


def fetch_page(code, page):
    url = "https://guba.eastmoney.com/list,%s,f_%d.html" % (code, page)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        html = r.read().decode("utf-8", errors="replace")
    m = re.search(r"var article_list=(\{.*?\});\s*var", html, re.S)
    if not m:
        return []
    return json.loads(m.group(1)).get("re", [])


def collect(code, date_from, date_to, max_pages=2000):
    os.makedirs(RAW, exist_ok=True)
    out_path = os.path.join(RAW, "guba_%s.jsonl" % code)
    seen = set()
    if os.path.exists(out_path):
        with open(out_path, encoding="utf-8") as fh:
            seen = {json.loads(line)["post_id"] for line in fh}
    kept = 0
    with open(out_path, "a", encoding="utf-8") as out:
        for page in range(1, max_pages + 1):
            for attempt in range(3):
                try:
                    posts = fetch_page(code, page)
                    break
                except Exception as e:  # network hiccup: back off and retry
                    print("  page %d attempt %d failed: %s" % (page, attempt + 1, e))
                    time.sleep(5 * (attempt + 1))
            else:
                print("  giving up at page %d" % page)
                break
            if not posts:
                break
            times = sorted(p["post_publish_time"] for p in posts)
            for p in posts:
                day = p["post_publish_time"][:10]
                if p["post_id"] in seen or not (date_from <= day <= date_to):
                    continue
                seen.add(p["post_id"])
                out.write(json.dumps({
                    "post_id": p["post_id"], "stock": code,
                    "time": p["post_publish_time"], "title": p.get("post_title", ""),
                    "reads": p.get("post_click_count", 0),
                    "comments": p.get("post_comment_count", 0),
                    "post_type": p.get("post_type"), "bar_code": p.get("stockbar_code"),
                }, ensure_ascii=False) + "\n")
                kept += 1
            # The median publish time of the page tells us where we are; the
            # first page also carries a few pinned older posts, so not the min.
            if times[len(times) // 2][:10] < date_from:
                break
            if page % 20 == 0:
                print("  %s page %d, reached %s, kept %d" % (code, page, times[0][:10], kept))
            time.sleep(DELAY_S)
    print("%s: kept %d new posts -> %s" % (code, kept, out_path))
    return kept


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    collect(sys.argv[1], sys.argv[2], sys.argv[3])
