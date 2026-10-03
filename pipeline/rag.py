"""
GubaCheck - RETRIEVAL OVER EACH COMPANY'S OWN FILINGS (chunked RAG)
=========================================================================
    python3 -m pipeline.rag build                 chunk + embed every filing text
    python3 -m pipeline.rag show <ann_id>         print what would be retrieved

Knowledge base: the text of every downloaded CNINFO filing
(data/raw/ann_text/), i.e. the companies' own disclosures.

Pipeline
  1 CHUNK    300 characters, 50 overlapping, whitespace removed; chunks
             under 40 characters dropped.
  2 EMBED    BAAI/bge-small-zh-v1.5 (512-d, MIT licence), run locally,
             normalised vectors; stored in data/raw/rag_index.npz with
             chunk metadata in data/raw/rag_chunks.jsonl.
  3 FILTER   metadata first: same company, published strictly BEFORE the
             filing being judged (no look-ahead), not the filing itself.
  4 TOP-K    cosine similarity to the query (title + first 300 characters,
             with bge's retrieval instruction); top 5 chunks scoring >= 0.80,
             at most 2 per source filing so one long report cannot fill the
             context. (Below ~0.80 the hits were unrelated filings that only
             shared an opening phrase; the boilerplate header every filing
             carries is stripped before chunking for the same reason.)
  5 FORCED   two documents are added by rule, not by similarity:
             - the most recent earlier periodic report's key-figures section
               (the company's baseline);
             - for a periodic report or earnings express, the earnings
               forecast of the SAME reporting period, if one was published:
               a final report is only news relative to what was already
               pre-announced, and similarity search does not reliably rank
               that forecast first (the previous quarterly report looks more
               alike).
             `force=False` drops step 5, for the ablation.
=========================================================================
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RAW = os.path.join(ROOT, "data", "raw")
MODEL = "BAAI/bge-small-zh-v1.5"
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
CHUNK, OVERLAP, MIN_CHUNK, TOP_K, PER_SOURCE = 300, 50, 40, 5, 2
MIN_SCORE = 0.80   # below this, retrieved chunks were unrelated filings sharing an opening phrase

_STATE = {}


def _model():
    if "model" not in _STATE:
        from sentence_transformers import SentenceTransformer
        import torch
        dev = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
        _STATE["model"] = SentenceTransformer(MODEL, device=dev)
    return _STATE["model"]


_BOILER = [r"证券代码[:：].{0,40}?公告编号[:：]?[A-Za-z0-9\-－]+",
           r"本公司及(全体)?董事会.{0,40}?(重大遗漏|连带责任)[^。]*。",
           r"(证券简称|股票简称|债券代码|债券简称)[:：]\S{0,12}"]


def clean(text):
    """Remove the header every filing starts with; it made unrelated
    filings look alike (similarity 0.86+ on boilerplate alone)."""
    t = re.sub(r"\s+", "", text)
    for pat in _BOILER:
        t = re.sub(pat, "", t)
    return t


def chunks_of(text):
    t = clean(text)
    out, i = [], 0
    while i < len(t):
        c = t[i:i + CHUNK]
        if len(c) >= MIN_CHUNK:
            out.append(c)
        i += CHUNK - OVERLAP
    return out


def build():
    import numpy as np
    from collectors.announcements import records
    meta, texts = [], []
    for a in records():
        p = os.path.join(RAW, "ann_text", "%s.txt" % a["ann_id"])
        if not os.path.exists(p):
            continue
        for k, c in enumerate(chunks_of(open(p, encoding="utf-8").read())):
            meta.append({"ann_id": a["ann_id"], "stock": a["stock"], "time": a["time"],
                         "title": a["title"], "k": k})
            texts.append(c)
    emb = _model().encode(texts, batch_size=128, normalize_embeddings=True, show_progress_bar=False)
    np.savez_compressed(os.path.join(RAW, "rag_index.npz"), emb=emb.astype("float32"))
    with open(os.path.join(RAW, "rag_chunks.jsonl"), "w", encoding="utf-8") as fh:
        for m, t in zip(meta, texts):
            fh.write(json.dumps(dict(m, text=t), ensure_ascii=False) + "\n")
    print("chunks %d from %d filings, dim %d" % (len(texts), len({m["ann_id"] for m in meta}), emb.shape[1]))


def _index():
    if "emb" not in _STATE:
        import numpy as np
        _STATE["emb"] = np.load(os.path.join(RAW, "rag_index.npz"))["emb"]
        _STATE["chunks"] = [json.loads(l) for l in open(os.path.join(RAW, "rag_chunks.jsonl"), encoding="utf-8")]
    return _STATE["emb"], _STATE["chunks"]


_PERIOD = re.compile(r"(20\d\d)\s*(年第一季度|年一季度|年第三季度|年三季度|年半年度|年年度|年度)")


def period_of(title):
    """'2025年度业绩预告' and '2025年年度报告' -> '2025-FY'; '2026年半年度…' -> '2026-H1'."""
    m = _PERIOD.search(title)
    if not m:
        return None
    p = m.group(2)
    tag = "H1" if "半年" in p else "Q1" if "一季" in p else "Q3" if "三季" in p else "FY"
    return "%s-%s" % (m.group(1), tag)


def forced(ann, rows):
    """Rule-based documents: baseline periodic report + same-period forecast."""
    earlier = [r for r in rows if r["stock"] == ann["stock"] and r["time"] < ann["time"]
               and r["ann_id"] != ann["ann_id"] and r.get("has_text")]
    out = []
    periodic = [r for r in earlier if r.get("periodic")]
    if periodic:
        out.append(("最近一期定期报告（主要财务数据）", max(periodic, key=lambda r: r["time"])))
    is_result = ann.get("periodic") or "业绩快报" in ann["title"]
    per = period_of(ann["title"])
    if is_result and per:
        fc = [r for r in earlier if re.search(r"业绩预告|业绩预增|业绩快报", r["title"])
              and period_of(r["title"]) == per and r["ann_id"] != ann["ann_id"]]
        if fc:
            out.append(("同一报告期此前的业绩预告/快报", max(fc, key=lambda r: r["time"])))
    return out


def retrieve(ann, query_text, force=True):
    """Returns (forced_docs, top_chunks); top_chunks are chunk dicts with score."""
    import numpy as np
    from pipeline import judge
    emb, chunks = _index()
    rows = judge.load_announcements()
    forced_docs = forced(ann, rows) if force else []
    skip = {d["ann_id"] for _, d in forced_docs} | {ann["ann_id"]}
    mask = np.array([c["stock"] == ann["stock"] and c["time"] < ann["time"] and c["ann_id"] not in skip
                     for c in chunks])
    if not mask.any():
        return forced_docs, []
    q = _model().encode([QUERY_PREFIX + ann["title"] + clean(query_text)[:300]], normalize_embeddings=True)[0]
    scores = emb @ q
    scores[~mask] = -1
    picked, per_src = [], {}
    for i in np.argsort(-scores):
        if scores[i] < MIN_SCORE or len(picked) >= TOP_K:
            break
        c = chunks[i]
        if per_src.get(c["ann_id"], 0) >= PER_SOURCE:
            continue
        per_src[c["ann_id"]] = per_src.get(c["ann_id"], 0) + 1
        picked.append(dict(c, score=round(float(scores[i]), 3)))
    return forced_docs, picked


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        build()
    elif cmd == "show":
        from pipeline import judge
        rows = {r["ann_id"]: r for r in judge.load_announcements()}
        a = rows[sys.argv[2]]
        f, top = retrieve(a, judge.text_of(a["ann_id"]))
        print("QUERY:", a["time"], a["title"])
        for label, d in f:
            print("FORCED [%s] %s %s" % (label, d["time"][:10], d["title"]))
        for c in top:
            print("TOP %.3f %s %s | %s" % (c["score"], c["time"][:10], c["title"][:30], c["text"][:60]))
    else:
        print(__doc__)
