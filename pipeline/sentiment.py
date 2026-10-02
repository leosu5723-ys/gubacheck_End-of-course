"""
GubaCheck - FORUM POST SENTIMENT (bullish / bearish / neutral)
=========================================================================
    python3 -m pipeline.sentiment sample 300     write data/labels/to_label.csv
    python3 -m pipeline.sentiment eval           compare classifiers on the labels
    python3 -m pipeline.sentiment eval --llm     ... plus an LLM few-shot (costs money)
    python3 -m pipeline.sentiment train          fit the chosen model on all labels

Why a narrow model here: the labels are fixed (three classes), the input
is a short title, and it runs over every post every day. That is the job
narrow ML is cheap and good at; the LLM few-shot is the rented
comparison, and the cost per 1,000 posts of each is reported.

Compared, on the same held-out split (the LATEST 30% of labelled posts by
time, so the test set is never older than the training set):
    majority     always the most common class        - the floor
    lexicon      bull/bear keyword counts           - the non-AI baseline
    tfidf_lr     character 1-3 grams + logistic regression
    llm_fewshot  optional, rented model, 6 worked examples

Abstention: tfidf_lr returns "uncertain" when its top probability is
below ABSTAIN_BELOW. The report gives the abstention rate and the error
rate among abstained posts versus answered posts.

Labels follow data/labels/LABEL_RULES.md, written before any model ran.
=========================================================================
"""
import csv
import json
import os
import pickle
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS = os.path.join(ROOT, "data", "labels", "labelled.csv")
MODEL_PATH = os.path.join(ROOT, "results", "sentiment_model.pkl")
CLASSES = ["bull", "bear", "neutral"]
ABSTAIN_BELOW = 0.50

BULL = ["涨停", "起飞", "加仓", "买入", "抄底", "利好", "主升", "看多", "突破", "翻倍",
        "满仓", "冲", "牛", "拉升", "大涨", "新高", "上车", "低吸", "格局", "吃肉"]
BEAR = ["跌停", "割肉", "清仓", "套牢", "利空", "出货", "崩", "熊", "暴雷", "看空",
        "大跌", "跑了", "快跑", "新低", "減持", "减持", "退市", "亏", "埋", "韭菜"]


def lexicon(title):
    b = sum(title.count(w) for w in BULL)
    s = sum(title.count(w) for w in BEAR)
    return "bull" if b > s else "bear" if s > b else "neutral"


def load_labels():
    with open(LABELS, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("label") in CLASSES]
    rows.sort(key=lambda r: r["time"])
    return rows


def split(rows, test_frac=0.3):
    cut = int(len(rows) * (1 - test_frac))
    return rows[:cut], rows[cut:]


def fit_tfidf(train):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    model = make_pipeline(TfidfVectorizer(analyzer="char", ngram_range=(1, 3), min_df=1),
                          LogisticRegression(max_iter=2000, class_weight="balanced"))
    model.fit([r["title"] for r in train], [r["label"] for r in train])
    return model


def predict(model, titles):
    """Return [(label_or_uncertain, top_probability)]."""
    probs = model.predict_proba(titles)
    out = []
    for p in probs:
        i = p.argmax()
        out.append((model.classes_[i] if p[i] >= ABSTAIN_BELOW else "uncertain", float(p[i])))
    return out


def llm_fewshot(titles):
    """Rented comparison. Returns (labels, tokens_in, tokens_out)."""
    sys.path.insert(0, ROOT)
    from core import backends
    shots = ("Label each Chinese stock-forum title as bull, bear or neutral. Reply with one "
             "label per line, nothing else.\nExamples:\n明天涨停，满仓干 -> bull\n"
             "套牢了，割肉走人 -> bear\n今天成交量多少 -> neutral\n利好兑现，主升浪来了 -> bull\n"
             "又要暴雷，快跑 -> bear\n大家怎么看分红 -> neutral\n")
    labels, tin, tout = [], 0, 0
    for i in range(0, len(titles), 20):
        batch = titles[i:i + 20]
        text, usage = backends._live_call([{"role": "user", "content": shots + "\n".join(batch)}])
        got = [ln.strip().split()[-1].lower() for ln in text.strip().splitlines() if ln.strip()]
        got = (got + ["neutral"] * len(batch))[:len(batch)]
        labels += [g if g in CLASSES else "neutral" for g in got]
        tin += usage.get("prompt_tokens", 0)
        tout += usage.get("completion_tokens", 0)
    return labels, tin, tout


def macro_f1(gold, pred):
    from sklearn.metrics import f1_score
    return round(f1_score(gold, pred, labels=CLASSES, average="macro", zero_division=0), 4)


def cmd_eval(use_llm=False):
    rows = load_labels()
    train, test = split(rows)
    gold = [r["label"] for r in test]
    titles = [r["title"] for r in test]
    majority = max(CLASSES, key=lambda c: sum(r["label"] == c for r in train))
    report = {"n_train": len(train), "n_test": len(test),
              "test_period": [test[0]["time"][:10], test[-1]["time"][:10]] if test else None,
              "class_counts_test": {c: gold.count(c) for c in CLASSES}, "methods": {}}
    report["methods"]["majority"] = {"macro_f1": macro_f1(gold, [majority] * len(gold))}
    report["methods"]["lexicon"] = {"macro_f1": macro_f1(gold, [lexicon(t) for t in titles])}

    model = fit_tfidf(train)
    raw = list(model.predict(titles))
    report["methods"]["tfidf_lr"] = {"macro_f1": macro_f1(gold, raw)}
    pa = predict(model, titles)
    answered = [(g, p) for g, (p, _) in zip(gold, pa) if p != "uncertain"]
    abstained = [(g, r) for g, (p, _), r in zip(gold, pa, raw) if p == "uncertain"]
    report["abstention"] = {
        "threshold": ABSTAIN_BELOW,
        "abstain_rate": round(len(abstained) / len(gold), 4) if gold else None,
        "error_rate_answered": round(sum(g != p for g, p in answered) / len(answered), 4) if answered else None,
        "error_rate_abstained_if_forced": round(sum(g != r for g, r in abstained) / len(abstained), 4) if abstained else None,
        "macro_f1_answered_only": macro_f1([g for g, _ in answered], [p for _, p in answered]) if answered else None,
    }
    if use_llm:
        sys.path.insert(0, ROOT)
        from core import config
        labels, tin, tout = llm_fewshot(titles)
        cost = tin / 1e6 * config.PRICE_IN + tout / 1e6 * config.PRICE_OUT
        report["methods"]["llm_fewshot"] = {
            "macro_f1": macro_f1(gold, labels), "model": config.MODEL,
            "tokens_in": tin, "tokens_out": tout,
            "usd_per_1000_posts": round(1000 * cost / len(titles), 4)}
    report["methods"]["tfidf_lr"]["usd_per_1000_posts"] = 0.0
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "sentiment_eval.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_train():
    model = fit_tfidf(load_labels())
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, "wb") as fh:
        pickle.dump(model, fh)
    print("saved", MODEL_PATH)


def cmd_sample(n):
    """Stratified sample of posts across stocks and days, for hand labelling."""
    posts = []
    raw = os.path.join(ROOT, "data", "raw")
    for f in sorted(os.listdir(raw)):
        if f.startswith("guba_") and f.endswith(".jsonl"):
            with open(os.path.join(raw, f), encoding="utf-8") as fh:
                posts += [json.loads(line) for line in fh]
    random.seed(6201)
    random.shuffle(posts)
    by_stock = {}
    for p in posts:
        by_stock.setdefault(p["stock"], []).append(p)
    pick, i = [], 0
    while len(pick) < n and any(by_stock.values()):
        for code in list(by_stock):
            if by_stock[code] and len(pick) < n:
                pick.append(by_stock[code].pop())
        i += 1
    out = os.path.join(ROOT, "data", "labels", "to_label.csv")
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["post_id", "stock", "time", "title", "label", "note"])
        for p in sorted(pick, key=lambda p: p["time"]):
            w.writerow([p["post_id"], p["stock"], p["time"], p["title"], "", ""])
    print("wrote %d rows to %s - label them per LABEL_RULES.md, save as labelled.csv" % (len(pick), out))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sample":
        cmd_sample(int(sys.argv[2]) if len(sys.argv) > 2 else 300)
    elif cmd == "eval":
        cmd_eval("--llm" in sys.argv)
    elif cmd == "train":
        cmd_train()
    else:
        print(__doc__)
