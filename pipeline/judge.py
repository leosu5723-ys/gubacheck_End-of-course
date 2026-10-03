"""
GubaCheck - ANNOUNCEMENT JUDGE (LLM reads the filing, with or without RAG)
=========================================================================
    python3 -m pipeline.judge sample 40          sheet for hand labelling
    python3 -m pipeline.judge run text --limit=5 try 5 calls first
    python3 -m pipeline.judge run text           LLM reads the filing only
    python3 -m pipeline.judge run rag            LLM reads the filing + retrieved company history
    python3 -m pipeline.judge eval               both modes vs my hand labels

Each non-procedural announcement gets {label: bullish|bearish|neutral,
reason, confidence}. Procedural filings are neutral by code, no model
call. Share issuance, shareholder reduction and lock-up expiry can never
be bullish: a model answer of "bullish" on those is overridden to neutral
and the override is recorded.

RAG: the knowledge base is the same company's earlier filings
(data/raw/ann_text/ + titles in data/raw/announcements.jsonl). For an
announcement published at time T, only documents published BEFORE T are
eligible - retrieval never sees the future. Context = the most recent
periodic report's key-figures section + the latest earlier earnings
forecast/express (a final report is only news relative to what was
pre-announced) + the most similar earlier filings (character-bigram
overlap; terminology repeats within one company's filings, so lexical
retrieval is enough and costs nothing). 3 retrieved filings in total.

Model calls go through core/backends._live_call (OpenRouter); token usage
returned by the API is recorded, so costs are measured. Results are
cached in data/raw/judgements_<mode>.jsonl; re-runs only call the model
for missing announcements.
=========================================================================
"""
import csv
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config, market  # noqa: E402

RAW = os.path.join(ROOT, "data", "raw")
LABELS = os.path.join(ROOT, "data", "labels")
CLASSES = ["bullish", "bearish", "neutral"]

PROMPT = """你是A股公告分析员。判断这条公告对该公司股价未来几个交易日的影响：
bullish（利好）、bearish（利空）或 neutral（中性/程序性/影响不明）。
要求：只依据给出的公告正文和公司历史资料；不要猜测公告以外的信息；
与公司过去的业绩或公告相比较（例如增速是加快还是放缓）。
只输出JSON：{"label": "bullish|bearish|neutral", "confidence": 0到1, "reason": "一句话，引用公告中的具体数字或事实"}

公司：%(name)s（%(code)s）
公告标题：%(title)s
发布时间：%(time)s
公告正文（节选）：
%(body)s
%(context)s"""


def load_announcements():
    from collectors.announcements import records
    rows = records()
    for r in rows:
        r["type"] = market.event_type_of(r["title"])["type"]
    return rows


def text_of(ann_id, limit=2500):
    p = os.path.join(RAW, "ann_text", "%s.txt" % ann_id)
    return open(p, encoding="utf-8").read()[:limit] if os.path.exists(p) else ""


def _bigrams(s):
    s = re.sub(r"\s+", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def retrieve(ann, rows, k=3):
    """Earlier filings of the same company only (published before ann)."""
    earlier = [r for r in rows if r["stock"] == ann["stock"] and r["time"] < ann["time"]
               and r["ann_id"] != ann["ann_id"]]
    periodic = [r for r in earlier if r.get("periodic") and r.get("has_text")]
    latest = max(periodic, key=lambda r: r["time"]) if periodic else None
    # The most recent earnings forecast / express is always included: a final
    # report is only news relative to what was already pre-announced.
    fc = [r for r in earlier if r.get("has_text") and re.search(r"业绩预告|业绩快报|业绩预增", r["title"])]
    forecast = max(fc, key=lambda r: r["time"]) if fc else None
    q = _bigrams(ann["title"] + text_of(ann["ann_id"], 600))
    scored = []
    for r in earlier:
        if r.get("procedural") or r is latest:
            continue
        d = _bigrams(r["title"] + text_of(r["ann_id"], 400))
        if q and d:
            scored.append((len(q & d) / (len(q) * len(d)) ** 0.5, r))
    top = [r for _, r in sorted(scored, key=lambda x: -x[0]) if r is not forecast][:k]
    if forecast:
        top = [forecast] + top[:k - 1]
    return latest, top


def context_block(ann, rows):
    latest, top = retrieve(ann, rows)
    parts = []
    if latest:
        parts.append("【最近一期定期报告：%s（%s）主要财务数据】\n%s"
                     % (latest["title"], latest["time"][:10], text_of(latest["ann_id"], 1500)))
    for r in top:
        parts.append("【历史公告 %s：%s】\n%s" % (r["time"][:10], r["title"], text_of(r["ann_id"], 400)))
    ids = ([latest["ann_id"]] if latest else []) + [r["ann_id"] for r in top]
    return ("\n公司历史资料（仅限本公告发布之前）：\n" + "\n\n".join(parts)) if parts else "", ids


def judge_one(ann, rows, mode):
    from core import backends
    ctx, ctx_ids = context_block(ann, rows) if mode == "rag" else ("", [])
    prompt = PROMPT % {"name": ann["name"], "code": ann["stock"], "title": ann["title"],
                       "time": ann["time"], "body": text_of(ann["ann_id"]) or "（无正文）", "context": ctx}
    text, usage = backends._live_call([{"role": "user", "content": prompt}])
    m = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        out = {}
    label = out.get("label") if out.get("label") in CLASSES else "neutral"
    rec = {"ann_id": ann["ann_id"], "label": label, "confidence": out.get("confidence"),
           "reason": out.get("reason", "")[:300], "context_ids": ctx_ids,
           "tokens_in": usage.get("prompt_tokens", 0), "tokens_out": usage.get("completion_tokens", 0),
           "model": config.MODEL, "override": None}
    if label == "bullish" and ann["type"] in config.NEVER_BULLISH_TYPES:
        rec["override"] = "%s can never be bullish" % ann["type"]
        rec["label"] = "neutral"
    return rec


def cmd_run(mode, limit=None):
    rows = load_announcements()
    path = os.path.join(RAW, "judgements_%s.jsonl" % mode)
    done = {}
    if os.path.exists(path):
        done = {json.loads(l)["ann_id"]: 1 for l in open(path, encoding="utf-8")}
    todo = [r for r in rows if not r["procedural"] and r.get("has_text") and r["ann_id"] not in done]
    if limit:
        todo = todo[:limit]
    print("%s: %d to judge (%d cached)" % (mode, len(todo), len(done)), flush=True)
    tin = tout = 0
    with open(path, "a", encoding="utf-8") as fh:
        for i, ann in enumerate(todo, 1):
            try:
                rec = judge_one(ann, rows, mode)
            except Exception as e:
                print("  failed", ann["ann_id"], str(e)[:100], flush=True)
                continue
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            tin, tout = tin + rec["tokens_in"], tout + rec["tokens_out"]
            if i % 25 == 0:
                print("  %d/%d  tokens in %d out %d  ~US$%.4f" % (i, len(todo), tin, tout,
                      tin / 1e6 * config.PRICE_IN + tout / 1e6 * config.PRICE_OUT), flush=True)
    print("JUDGE DONE", mode, "tokens", tin, tout)


def all_judgements(mode):
    """ann_id -> label for every announcement (procedural = neutral by code)."""
    labels = {r["ann_id"]: "neutral" for r in load_announcements() if r["procedural"]}
    path = os.path.join(RAW, "judgements_%s.jsonl" % mode)
    if os.path.exists(path):
        for l in open(path, encoding="utf-8"):
            r = json.loads(l)
            labels[r["ann_id"]] = r["label"]
    return labels


def cmd_sample(n):
    """Hand-label sheet: non-procedural announcements, half from spike watch
    windows (the ones that matter for trading), half from the rest of the year.
    The sheet shows the same context the RAG mode sees."""
    rows = load_announcements()
    spikes = json.load(open(os.path.join(ROOT, "data", "snapshot", "spikes.json"), encoding="utf-8"))
    from datetime import date, timedelta
    win = set()
    for s in spikes:
        d0 = date.fromisoformat(s["date"])
        for r in rows:
            if r["stock"] == s["stock"] and s["date"] <= r["time"][:10] <= (d0 + timedelta(days=16)).isoformat():
                win.add(r["ann_id"])
    pool = [r for r in rows if not r["procedural"] and r.get("has_text") and not r.get("periodic")]
    rng = random.Random(6201)
    a = [r for r in pool if r["ann_id"] in win]
    b = [r for r in pool if r["ann_id"] not in win]
    pick = rng.sample(a, min(n // 2, len(a)))
    pick += rng.sample(b, min(n - len(pick), len(b)))
    rng.shuffle(pick)
    with open(os.path.join(LABELS, "ann_to_label.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ann_id", "stock", "name", "time", "title", "text_excerpt", "company_context", "label", "note"])
        for r in pick:
            ctx, _ = context_block(r, rows)
            w.writerow([r["ann_id"], r["stock"], r["name"], r["time"], r["title"],
                        text_of(r["ann_id"], 800), ctx[:1200], "", ""])
    print("wrote %d rows (%d from watch windows) to data/labels/ann_to_label.csv" % (len(pick), min(n // 2, len(a))))


QUOTA_BATCH2 = {"earnings_forecast": 11, "earnings_preincrease": 4, "periodic": 5, "buyback": 3,
                "shareholder_increase": 2, "major_contract": 2, "restructuring": 1,
                "shareholder_decrease": 1, "clarification": 1}


def cmd_sample2():
    """Batch 2, the held-out test set: substantive filings only, weighted to
    earnings pre-announcements. Batch 1 (40 random filings, 37 neutral)
    shaped the procedural filter, so it is not used as the main test."""
    import csv as _csv
    rows = load_announcements()
    b1 = {r["ann_id"] for r in _csv.DictReader(open(os.path.join(LABELS, "ann_labelled.csv"), encoding="utf-8-sig"))}
    pool = [r for r in rows if not r["procedural"] and r.get("has_text") and r["ann_id"] not in b1]
    rng = random.Random(62012)
    pick = []
    for kind, n in QUOTA_BATCH2.items():
        cand = [r for r in pool if (r["periodic"] if kind == "periodic" else (r["type"] == kind and not r["periodic"]))]
        pick += rng.sample(cand, min(n, len(cand)))
    rng.shuffle(pick)
    with open(os.path.join(LABELS, "ann_to_label_batch2.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = _csv.writer(fh)
        w.writerow(["ann_id", "stock", "name", "time", "title", "text_excerpt", "company_context", "label", "note"])
        for r in pick:
            ctx, _ = context_block(r, rows)
            w.writerow([r["ann_id"], r["stock"], r["name"], r["time"], r["title"],
                        text_of(r["ann_id"], 1200), ctx[:2000], "", ""])
    print("wrote %d rows to data/labels/ann_to_label_batch2.csv" % len(pick))


def cmd_eval():
    sys.path.insert(0, ROOT)
    from pipeline.sentiment import bootstrap_ci
    path = os.path.join(LABELS, "ann_labelled.csv")
    gold = {r["ann_id"]: r["label"].strip().lower() for r in csv.DictReader(open(path, encoding="utf-8-sig"))
            if r["label"].strip().lower() in CLASSES}
    report = {"n": len(gold), "gold_counts": {c: sum(v == c for v in gold.values()) for c in CLASSES}, "modes": {}}
    for mode in ("text", "rag"):
        pred = all_judgements(mode)
        ids = [i for i in gold if i in pred]
        if not ids:
            continue
        g, p = [gold[i] for i in ids], [pred[i] for i in ids]
        recs = [json.loads(l) for l in open(os.path.join(RAW, "judgements_%s.jsonl" % mode), encoding="utf-8")]
        tin, tout = sum(r["tokens_in"] for r in recs), sum(r["tokens_out"] for r in recs)
        report["modes"][mode] = {
            "n": len(ids), "macro_f1": _mf1(g, p), "ci95": bootstrap_ci(g, p),
            "accuracy": round(sum(x == y for x, y in zip(g, p)) / len(ids), 4),
            "false_bullish": sum(1 for x, y in zip(g, p) if y == "bullish" and x != "bullish"),
            "calls": len(recs), "tokens_in": tin, "tokens_out": tout,
            "usd_total": round(tin / 1e6 * config.PRICE_IN + tout / 1e6 * config.PRICE_OUT, 4),
            "usd_per_call": round((tin / 1e6 * config.PRICE_IN + tout / 1e6 * config.PRICE_OUT) / max(len(recs), 1), 6)}
    json.dump(report, open(os.path.join(ROOT, "results", "judge_eval.json"), "w"), ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _mf1(g, p):
    from sklearn.metrics import f1_score
    return round(f1_score(g, p, labels=CLASSES, average="macro", zero_division=0), 4)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sample2":
        cmd_sample2()
    elif cmd == "sample":
        cmd_sample(int(sys.argv[2]) if len(sys.argv) > 2 else 40)
    elif cmd == "run":
        lim = [int(a.split("=")[1]) for a in sys.argv if a.startswith("--limit=")]
        cmd_run(sys.argv[2], lim[0] if lim else None)
    elif cmd == "eval":
        cmd_eval()
    else:
        print(__doc__)
