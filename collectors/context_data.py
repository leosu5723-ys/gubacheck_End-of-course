"""
GubaCheck - CONTEXT DATA FOR THE CAUSE TOOLS (C, D, E, G, A)
=========================================================================
    python3 -m collectors.context_data

  peers      daily bars of the extra A-share peers in data/peers.json (Sina)  -> prices.jsonl
  us         daily bars of the US peers (Sina)                                -> us_prices.jsonl
  chinext    ChiNext index daily                                              -> chinext.json
  toplist    the exchange top list (龙虎榜) for the whole window, month by month -> toplist.jsonl
  irm        board-secretary Q&A: CNINFO 互动易 (Shenzhen listings) and SSE e互动
             (Shanghai listings) -> irm.jsonl. These feeds only return recent
             questions (about three months), so cause A uses filings for the
             earlier part of the year.
=========================================================================
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from collectors import market_data  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")


def peers():
    cfg = json.load(open(os.path.join(ROOT, "data", "peers.json")))["groups"]
    for g in cfg.values():
        for code in g["extra_peers"]:
            market_data.prices(code, "2025-04-01", "2026-10-02")
            time.sleep(1)


def us():
    import akshare as ak
    cfg = json.load(open(os.path.join(ROOT, "data", "peers.json")))["groups"]
    tickers = sorted({t for g in cfg.values() for t in g["us_peers"]})
    with open(os.path.join(RAW, "us_prices.jsonl"), "w", encoding="utf-8") as fh:
        for t in tickers:
            df = ak.stock_us_daily(symbol=t, adjust="")
            df = df[df["date"].astype(str) >= "2025-03-01"]
            prev = None
            for _, r in df.iterrows():
                c = float(r["close"])
                if prev:
                    fh.write(json.dumps({"ticker": t, "date": str(r["date"])[:10], "close": c,
                                         "ret": round(100 * (c / prev - 1), 3)}) + "\n")
                prev = c
            print("us", t, len(df), flush=True)
            time.sleep(1)


def chinext():
    import akshare as ak
    df = ak.stock_zh_index_daily(symbol="sz399006")
    df = df[df["date"].astype(str) >= "2025-03-01"]
    rows = [{"date": str(r["date"])[:10], "close": float(r["close"])} for _, r in df.iterrows()]
    json.dump(rows, open(os.path.join(RAW, "chinext.json"), "w"))
    print("chinext", len(rows))


def toplist():
    import akshare as ak
    import pandas as pd
    months = pd.date_range("2025-09-01", "2026-10-01", freq="MS")
    with open(os.path.join(RAW, "toplist.jsonl"), "w", encoding="utf-8") as fh:
        for a, b in zip(months[:-1], months[1:]):
            s, e = a.strftime("%Y%m%d"), (b - pd.Timedelta(days=1)).strftime("%Y%m%d")
            for attempt in range(3):
                try:
                    df = ak.stock_lhb_detail_em(start_date=s, end_date=e)
                    break
                except Exception as ex:
                    print("  retry", s, ex, flush=True)
                    time.sleep(5)
            else:
                continue
            for _, r in df.iterrows():
                fh.write(json.dumps({"stock": str(r["代码"]), "date": str(r["上榜日"])[:10],
                                     "net_buy": float(r["龙虎榜净买额"] or 0), "turnover": float(r["龙虎榜成交额"] or 0),
                                     "reason": str(r["上榜原因"]), "note": str(r["解读"])}, ensure_ascii=False) + "\n")
            print("toplist", s, len(df), flush=True)
            time.sleep(1)


def irm():
    import akshare as ak
    watch = [w["code"] for w in json.load(open(os.path.join(ROOT, "data", "watchlist.json")))]
    with open(os.path.join(RAW, "irm.jsonl"), "w", encoding="utf-8") as fh:
        for code in watch:
            try:
                if code.startswith(("0", "3")):
                    df = ak.stock_irm_cninfo(symbol=code)
                    for _, r in df.iterrows():
                        fh.write(json.dumps({"stock": code, "q_time": str(r["提问时间"]), "a_time": str(r["更新时间"]),
                                             "question": str(r["问题"]), "answer": str(r["回答内容"])}, ensure_ascii=False) + "\n")
                else:
                    df = ak.stock_sns_sseinfo(symbol=code)
                    cols = list(df.columns)
                    for _, r in df.iterrows():
                        fh.write(json.dumps({"stock": code, "raw": {c: str(r[c]) for c in cols}}, ensure_ascii=False) + "\n")
                print("irm", code, len(df), flush=True)
            except Exception as e:
                print("irm", code, "failed", str(e)[:100], flush=True)
            time.sleep(1)


if __name__ == "__main__":
    for step in (sys.argv[1:] or ["chinext", "us", "peers", "toplist", "irm"]):
        globals()[step]()
    print("CONTEXT DONE")
