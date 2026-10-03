"""
GubaCheck - FINE-TUNED CHINESE ROBERTA (sentiment, option B)
=========================================================================
    python3 -m pipeline.bert_sentiment train      fine-tune on the LLM labels
    python3 -m pipeline.bert_sentiment eval       score on the hand labels
    python3 -m pipeline.bert_sentiment predict    label every own-bar post

Why: TF-IDF matches character patterns and cannot read sarcasm ("空狗，
没吃饭吗，给爷砸个跌停" is a taunt at short sellers, i.e. bullish). A
pretrained Chinese encoder has seen enough text to model meaning.

Model: hfl/chinese-roberta-wwm-ext (110M parameters, Apache-2.0),
downloaded from Hugging Face on first run. Runs locally (Apple MPS / CUDA
/ CPU); no API cost.

Training data: the 3,000 LLM-labelled posts only. 10% of them are held
out for choosing the epoch; the hand-labelled test set is never used for
training or model choice.

The fine-tuned weights (~400 MB) are not committed; `train` rebuilds them.
`predict` writes data/raw/sentiment_bert_<code>.jsonl, which the snapshot
builder uses when present.
=========================================================================
"""
import json
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from pipeline import sentiment as S  # noqa: E402

BASE_MODEL = "hfl/chinese-roberta-wwm-ext"
OUT_DIR = os.path.join(ROOT, "results", "bert_model")
MAX_LEN = 64
LABEL2ID = {c: i for i, c in enumerate(S.CLASSES)}
SEED = 6201


def _device():
    import torch
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _predict(model, tok, titles, batch=256):
    """[(label, probability)] in input order. Titles are processed sorted by
    length so each batch pads to a similar length (much faster)."""
    import torch
    dev = next(model.parameters()).device
    order = sorted(range(len(titles)), key=lambda i: len(titles[i]))
    out = [None] * len(titles)
    model.eval()
    with torch.no_grad():
        for idx in _batches(order, batch):
            enc = tok([titles[i] for i in idx], truncation=True, max_length=MAX_LEN,
                      padding=True, return_tensors="pt").to(dev)
            probs = torch.softmax(model(**enc).logits.float(), dim=-1).cpu()
            for i, p in zip(idx, probs):
                k = int(p.argmax())
                out[i] = (S.CLASSES[k], float(p[k]))
    return out


def cmd_train(epochs=3, lr=2e-5, batch=32):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    random.seed(SEED)
    torch.manual_seed(SEED)
    rows = S.load_llm_train()
    random.shuffle(rows)
    cut = int(len(rows) * 0.9)
    train, val = rows[:cut], rows[cut:]
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL, num_labels=3).to(_device())
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * ((len(train) + batch - 1) // batch)
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: max(0.0, 1 - s / steps))
    best, log = -1.0, []
    for ep in range(1, epochs + 1):
        model.train()
        random.shuffle(train)
        t0 = time.time()
        for chunk in _batches(train, batch):
            enc = tok([r["title"] for r in chunk], truncation=True, max_length=MAX_LEN,
                      padding=True, return_tensors="pt").to(model.device)
            labels = torch.tensor([LABEL2ID[r["label"]] for r in chunk]).to(model.device)
            loss = model(**enc, labels=labels).loss
            loss.backward()
            opt.step()
            sched.step()
            opt.zero_grad()
        pred = [p for p, _ in _predict(model, tok, [r["title"] for r in val])]
        f1 = S.macro_f1([r["label"] for r in val], pred)
        log.append({"epoch": ep, "val_macro_f1_vs_llm_labels": f1, "seconds": round(time.time() - t0, 1)})
        print(log[-1])
        if f1 > best:
            best = f1
            model.save_pretrained(OUT_DIR)
            tok.save_pretrained(OUT_DIR)
    with open(os.path.join(ROOT, "results", "bert_train_log.json"), "w", encoding="utf-8") as fh:
        json.dump({"base_model": BASE_MODEL, "n_train": len(train), "n_val": len(val),
                   "lr": lr, "batch": batch, "epochs": log, "best_val": best}, fh, indent=2)


def _load():
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(OUT_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(OUT_DIR).to(_device())
    return model, tok


def cmd_eval():
    """Adds "bert_finetuned" to results/sentiment_eval.json."""
    model, tok = _load()
    test = [r for r in S._read_labelled(S.LABELS) if r["label"] in S.CLASSES]
    gold = [r["label"] for r in test]
    pa = _predict(model, tok, [r["title"] for r in test])
    pred = [p for p, _ in pa]
    path = os.path.join(ROOT, "results", "sentiment_eval.json")
    report = json.load(open(path, encoding="utf-8"))

    def share(ls):
        b, s = ls.count("bull"), ls.count("bear")
        return round(b / (b + s), 4) if b + s else None
    answered = [(g, p) for g, (p, q) in zip(gold, pa) if q >= S.ABSTAIN_BELOW]
    report["methods"]["bert_finetuned"] = {
        "macro_f1": S.macro_f1(gold, pred), "ci95": S.bootstrap_ci(gold, pred),
        "accuracy": round(sum(g == p for g, p in zip(gold, pred)) / len(gold), 4),
        "confusion_gold_by_pred": {g: {c: sum(1 for x, y in zip(gold, pred) if x == g and y == c)
                                       for c in S.CLASSES} for g in S.CLASSES},
        "usd_per_1000_posts": 0.0, "base_model": BASE_MODEL}
    report["abstention_bert"] = {
        "threshold": S.ABSTAIN_BELOW,
        "abstain_rate": round(1 - len(answered) / len(gold), 4),
        "error_rate_answered": round(sum(g != p for g, p in answered) / len(answered), 4) if answered else None}
    report.setdefault("aggregate_bullish_share", {})["true"] = share(gold)
    report["aggregate_bullish_share"]["bert_finetuned"] = share(pred)
    tf = S.fit_tfidf(S.load_llm_train())
    report["aggregate_bullish_share"]["tfidf_lr"] = share(list(tf.predict([r["title"] for r in test])))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    for k, v in report["methods"].items():
        print("%-22s macro-F1 %.3f  CI %s  acc %s" % (k, v["macro_f1"], v["ci95"], v["accuracy"]))
    print("aggregate bullish share", report["aggregate_bullish_share"])


def cmd_predict():
    """Label every own-bar post; records throughput for the cost section."""
    model, tok = _load()
    with open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8") as fh:
        codes = [w["code"] for w in json.load(fh)]
    stats = {}
    for code in codes:
        posts = []
        with open(os.path.join(ROOT, "data", "raw", "guba_%s.jsonl" % code), encoding="utf-8") as fh:
            for line in fh:
                p = json.loads(line)
                if p.get("bar_code") == code:
                    posts.append(p)
        target = os.path.join(ROOT, "data", "raw", "sentiment_bert_%s.jsonl" % code)
        if os.path.exists(target) and sum(1 for _ in open(target)) == len(posts):
            print(code, "already labelled, skipped", flush=True)
            continue
        t0 = time.time()
        res = _predict(model, tok, [p["title"] for p in posts])
        secs = time.time() - t0
        with open(os.path.join(ROOT, "data", "raw", "sentiment_bert_%s.jsonl" % code), "w", encoding="utf-8") as fh:
            for p, (lab, prob) in zip(posts, res):
                fh.write(json.dumps({"post_id": p["post_id"], "label": lab, "p": round(prob, 3)}) + "\n")
        stats[code] = {"posts": len(posts), "seconds": round(secs, 1),
                       "posts_per_second": round(len(posts) / secs, 1)}
        print(code, stats[code], flush=True)
    path = os.path.join(ROOT, "results", "bert_predict_stats.json")
    old = json.load(open(path)) if os.path.exists(path) else {"stocks": {}}
    old["stocks"].update(stats)
    old["device"] = _device()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(old, fh, indent=2)
    print("PREDICT DONE", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    {"train": cmd_train, "eval": cmd_eval, "predict": cmd_predict}.get(cmd, lambda: print(__doc__))()
