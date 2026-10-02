"""
GubaCheck - ANNOUNCEMENTS, NEWS AND PRICES (via AKShare, free)
=========================================================================
    python3 -m collectors.market_data cninfo 600519 2026-06-01 2026-09-30
    python3 -m collectors.market_data prices 600519 2026-05-01 2026-10-30
    python3 -m collectors.market_data news   600519 000858 ...   (snapshot now)

Sources, all public and free, all through AKShare:
    cninfo   stock_zh_a_disclosure_report_cninfo   official disclosures
                                                   (CNINFO is the statutory
                                                   disclosure site of both
                                                   exchanges); full history
    prices   stock_zh_a_hist (unadjusted)          daily bars
    news     stock_info_global_cls                 CLS telegraph, latest ~20
             stock_info_global_em                  Eastmoney flash, latest ~200
             stock_news_em(code)                   per-stock news, latest ~10

The news feeds have NO history: they only return the latest items. That
is why `news` must run every day (see README, "daily snapshot"); the
archive it builds is the only way to evaluate news search later.

Known limitation: CNINFO timestamps carry a date but no time. Every
announcement is therefore treated as published after the close.
Output: data/raw/*.jsonl
=========================================================================
"""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")


def _append(name, rows, key):
    os.makedirs(RAW, exist_ok=True)
    path = os.path.join(RAW, name)
    seen = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            seen = {json.loads(line)[key] for line in fh}
    new = [r for r in rows if r[key] not in seen]
    with open(path, "a", encoding="utf-8") as fh:
        for r in new:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("%s: %d new rows (%d already present)" % (name, len(new), len(rows) - len(new)))


def cninfo(code, date_from, date_to):
    import akshare as ak
    df = ak.stock_zh_a_disclosure_report_cninfo(
        symbol=code, market="沪深京",
        start_date=date_from.replace("-", ""), end_date=date_to.replace("-", ""))
    rows = []
    for _, r in df.iterrows():
        m = re.search(r"announcementId=(\d+)", str(r["公告链接"]))
        rows.append({"ann_id": m.group(1) if m else hashlib.md5(str(r["公告链接"]).encode()).hexdigest()[:12],
                     "stock": code, "name": r["简称"], "title": r["公告标题"],
                     "date": str(r["公告时间"])[:10], "url": r["公告链接"]})
    _append("cninfo.jsonl", rows, "ann_id")


def prices(code, date_from, date_to):
    import akshare as ak
    df = ak.stock_zh_a_hist(symbol=code, period="daily", adjust="",
                            start_date=date_from.replace("-", ""), end_date=date_to.replace("-", ""))
    rows, prev = [], None
    for _, r in df.iterrows():
        close = float(r["收盘"])
        rows.append({"key": "%s_%s" % (code, r["日期"]), "stock": code, "date": str(r["日期"])[:10],
                     "open": float(r["开盘"]), "close": close, "high": float(r["最高"]),
                     "low": float(r["最低"]), "pct_chg": float(r["涨跌幅"]),
                     "prev_close": prev if prev is not None else round(close / (1 + float(r["涨跌幅"]) / 100), 2)})
        prev = close
    _append("prices.jsonl", rows, "key")


def news(codes):
    import akshare as ak
    rows = []

    def nid(*parts):
        return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:16]

    for _, r in ak.stock_info_global_cls(symbol="全部").iterrows():
        t = "%s %s" % (r["发布日期"], r["发布时间"])
        rows.append({"news_id": nid("cls", t, r["标题"]), "source": "cls_telegraph", "time": t,
                     "title": r["标题"] or r["内容"][:40], "content": r["内容"], "stocks": [], "url": ""})
    for _, r in ak.stock_info_global_em().iterrows():
        rows.append({"news_id": nid("em", r["发布时间"], r["标题"]), "source": "eastmoney_flash",
                     "time": str(r["发布时间"]), "title": r["标题"], "content": r["摘要"],
                     "stocks": [], "url": r["链接"]})
    for code in codes:
        for _, r in ak.stock_news_em(symbol=code).iterrows():
            rows.append({"news_id": nid("emstock", r["发布时间"], r["新闻标题"]),
                         "source": "eastmoney_stock_news", "time": str(r["发布时间"]),
                         "title": r["新闻标题"], "content": r["新闻内容"], "stocks": [code],
                         "url": r["新闻链接"]})
    _append("news.jsonl", rows, "news_id")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "cninfo":
        cninfo(*sys.argv[2:5])
    elif cmd == "prices":
        prices(*sys.argv[2:5])
    elif cmd == "news":
        news(sys.argv[2:])
    else:
        print(__doc__)
