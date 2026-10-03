"""
GubaCheck - INCREMENTAL DATA REFRESH (the app's "update data" button)
=========================================================================
    python3 -m pipeline.refresh            (or the 🔄 button in the app)

Brings every source up to today, then rebuilds the snapshot:

  1 guba        new own-bar posts since the last stored post (stops at the
                site's identity check; never works around it)
  2 sentiment   RoBERTa labels for the new posts only (local model)
  3 filings     CNINFO list for the last days + text of the new filings
  4 judge       LLM + RAG judgement of new filings (only with an API key)
  5 market      A-share bars (watchlist + peers), US peers, CSI 300 /
                ChiNext, exchange top list of the current months
  6 rebuild     spikes / daily stats (pipeline.anomaly), context snapshot
                (pipeline.context_snapshot), data/snapshot/meta.json

Every step reports ok / skipped / failed and the run continues: a failed
source leaves its previous data in place. Needs data/raw/ (not in the
repository, see data/DATA.md); without it the refresh refuses to start.
Spike detection uses only each day's past, so earlier spikes - and every
evaluation result tied to them - do not move when new days are added.
=========================================================================
"""
import json
import os
import sys
import time
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import config  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")
SNAP = os.path.join(ROOT, "data", "snapshot")


def watchlist():
    return [w["code"] for w in json.load(open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8"))]


def ready():
    """(ok, reason) - whether a refresh can run on this machine."""
    if not os.path.isdir(RAW) or not any(f.startswith("guba_") for f in os.listdir(RAW)):
        return False, "data/raw/ is missing (raw data is not in the repository; see data/DATA.md)"
    return True, ""


def _last_time(path, key="time"):
    last = ""
    if os.path.exists(path):
        for l in open(path, encoding="utf-8"):
            t = json.loads(l).get(key) or ""
            if t > last:
                last = t
    return last


# ------------------------------------------------------------------ steps
def step_guba(log):
    from collectors import guba
    today, total = date.today().isoformat(), 0
    for code in watchlist():
        start = (_last_time(os.path.join(RAW, "guba_%s.jsonl" % code))[:10] or
                 (date.today() - timedelta(days=3)).isoformat())
        try:
            n = guba.collect(code, start, today)
        except guba.Blocked as e:
            return "failed", "forum identity check (%s); stopped, %d new posts kept" % (str(e)[:60], total)
        total += n
        log("guba %s: +%d" % (code, n))
    return "ok", "%d new posts" % total


def step_sentiment(log):
    if not os.path.isdir(os.path.join(ROOT, "results", "bert_model")):
        return "skipped", "local RoBERTa model not found (results/bert_model)"
    from pipeline import bert_sentiment
    model, tok = bert_sentiment._load()
    total = 0
    for code in watchlist():
        target = os.path.join(RAW, "sentiment_bert_%s.jsonl" % code)
        done = {json.loads(l)["post_id"] for l in open(target, encoding="utf-8")} if os.path.exists(target) else set()
        new = [p for p in (json.loads(l) for l in open(os.path.join(RAW, "guba_%s.jsonl" % code), encoding="utf-8"))
               if p.get("bar_code") == code and p["post_id"] not in done]
        if not new:
            continue
        res = bert_sentiment._predict(model, tok, [p["title"] for p in new])
        with open(target, "a", encoding="utf-8") as fh:
            for p, (lab, prob) in zip(new, res):
                fh.write(json.dumps({"post_id": p["post_id"], "label": lab, "p": round(prob, 3)}) + "\n")
        total += len(new)
        log("sentiment %s: +%d" % (code, len(new)))
    return "ok", "%d posts labelled" % total


def step_filings(log):
    from collectors import announcements, market_data
    before = {json.loads(l)["ann_id"] for l in open(os.path.join(RAW, "cninfo.jsonl"), encoding="utf-8")}
    start = (date.today() - timedelta(days=7)).isoformat()
    for code in watchlist():
        market_data.cninfo(code, start, date.today().isoformat())
        time.sleep(0.5)
    after = {json.loads(l)["ann_id"] for l in open(os.path.join(RAW, "cninfo.jsonl"), encoding="utf-8")}
    new = after - before
    announcements.main(only=new)            # text for the new filings only
    return "ok", "%d new filings" % len(new)


def step_judge(log):
    if not config.API_KEY:
        return "skipped", "no API key: new filings count as neutral until judged"
    from pipeline import judge
    judge.cmd_run("rag", workers=4)
    return "ok", "new filings judged (LLM + RAG)"


def step_market(log):
    import akshare as ak
    from collectors import context_data, market_data
    peers = json.load(open(os.path.join(ROOT, "data", "peers.json"), encoding="utf-8"))["groups"]
    codes = watchlist() + [c for g in peers.values() for c in g["extra_peers"]]
    start, today = (date.today() - timedelta(days=15)).isoformat(), date.today().isoformat()
    for code in codes:
        market_data.prices(code, start, today)
        time.sleep(0.5)
    context_data.us()
    for name, sym in (("csi300", "sh000300"), ("chinext", "sz399006")):
        df = ak.stock_zh_index_daily(symbol=sym)
        df = df[df["date"].astype(str) >= "2025-03-01"]
        rows = [{"date": str(r["date"])[:10], "open": float(r["open"]), "close": float(r["close"])} for _, r in df.iterrows()]
        json.dump(rows, open(os.path.join(RAW, "%s.json" % name), "w"))
    # top list: the months not yet complete in the file
    path = os.path.join(RAW, "toplist.jsonl")
    seen = {(r["stock"], r["date"], r["reason"]) for r in (json.loads(l) for l in open(path, encoding="utf-8"))}
    s = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y%m%d")
    df = ak.stock_lhb_detail_em(start_date=s, end_date=date.today().strftime("%Y%m%d"))
    added = 0
    with open(path, "a", encoding="utf-8") as fh:
        for _, r in df.iterrows():
            row = {"stock": str(r["代码"]), "date": str(r["上榜日"])[:10], "net_buy": float(r["龙虎榜净买额"] or 0),
                   "turnover": float(r["龙虎榜成交额"] or 0), "reason": str(r["上榜原因"]), "note": str(r["解读"])}
            if (row["stock"], row["date"], row["reason"]) not in seen:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                added += 1
    return "ok", "bars to %s; top list +%d" % (today, added)


def step_rebuild(log):
    from pipeline import anomaly, context_snapshot, redteam
    real = lambda: {s["spike_id"] for s in json.load(open(os.path.join(SNAP, "spikes.json"), encoding="utf-8"))
                    if not s.get("synthetic")}
    before = real()
    anomaly.main()
    context_snapshot.main()
    redteam.main()                          # re-inject the synthetic guardrail spikes (G1-G3)
    write_meta()
    new = sorted(real() - before)
    return "ok", "%d new spikes%s" % (len(new), (": " + ", ".join(new)) if new else "")


def write_meta():
    """Latest raw timestamps the snapshot cannot show by itself (e.g. the newest forum post)."""
    meta = {"built_at": datetime.now().isoformat(timespec="seconds"),
            "guba_latest_post": max(_last_time(os.path.join(RAW, "guba_%s.jsonl" % c)) for c in watchlist())}
    json.dump(meta, open(os.path.join(SNAP, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


STEPS = [("guba", "股吧帖子", step_guba), ("sentiment", "情感标注", step_sentiment),
         ("filings", "巨潮公告", step_filings), ("judge", "公告判断", step_judge),
         ("market", "行情 / 美股 / 指数 / 龙虎榜", step_market), ("rebuild", "重算异动与快照", step_rebuild)]


def run(log=print, on_step=None):
    ok, why = ready()
    if not ok:
        return [("ready", "failed", why)]
    out = []
    for key, label, fn in STEPS:
        if on_step:
            on_step(key, label, "running", "")
        try:
            status, msg = fn(log)
        except Exception as e:                     # one source failing never stops the others
            status, msg = "failed", str(e)[:200]
        out.append((key, status, msg))
        if on_step:
            on_step(key, label, status, msg)
        log("%-9s %-7s %s" % (key, status, msg))
    return out


if __name__ == "__main__":
    run()
