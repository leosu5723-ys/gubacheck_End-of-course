"""
GubaCheck - FORUM POST SENTIMENT (bullish / bearish / neutral)
=========================================================================
    python3 -m pipeline.sentiment sample 300     write data/labels/to_label.csv (human test set)
    python3 -m pipeline.sentiment sample_llm 3000  write llm_part*.csv (LLM-labelled training set)
    python3 -m pipeline.sentiment eval           compare classifiers on the labels
    python3 -m pipeline.sentiment eval --llm     ... plus an LLM few-shot (costs money)
    python3 -m pipeline.sentiment train          fit the chosen model on all labels

Why a narrow model here: the labels are fixed (three classes), the input
is a short title, and it runs over every post every day. That is the job
narrow ML is cheap and good at; the LLM few-shot is the rented
comparison, and the cost per 1,000 posts of each is reported.

Design: the 300 human-labelled posts are the TEST set and are never
trained on. Training data is 3,000 other posts labelled by an LLM with
the prompt in data/labels/LLM_LABEL_PROMPT.md (an LLM used as a labeller,
measured: the same LLM also labels the 300 test titles blind, and its
agreement with the human labels is reported). Compared on the human set:
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
    """Human labels (the gold test set), oldest first."""
    rows = [r for r in _read_labelled(LABELS) if r["label"] in CLASSES]
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


def _read_labelled(path):
    with open(path, encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh)]
    for r in rows:
        r["label"] = (r.get("label") or "").strip().lower()
    return rows


def load_llm_train():
    """LLM-labelled training rows from data/labels/llm_done/llm_part*.csv."""
    import glob
    rows = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "labels", "llm_done", "llm_part*.csv"))):
        rows += [r for r in _read_labelled(f) if r["label"] in CLASSES]
    return rows


def bootstrap_ci(gold, pred, n=2000, seed=6201):
    """95% interval of Macro-F1 over resampled test sets. With ~100 test
    posts a single number hides a wide range; this shows it."""
    rng = random.Random(seed)
    idx = range(len(gold))
    vals = []
    for _ in range(n):
        s = [rng.choice(idx) for _ in idx]
        vals.append(macro_f1([gold[i] for i in s], [pred[i] for i in s]))
    vals.sort()
    return [vals[int(0.025 * n)], vals[int(0.975 * n)]]


def cmd_eval(use_llm=False):
    """Train on LLM labels, test on the hand-labelled posts (never trained on).
    Posts I marked "unsure" are excluded from scoring and counted."""
    all_human = [r for r in _read_labelled(LABELS) if r["label"] in CLASSES + ["unsure"]]
    unsure = [r for r in all_human if r["label"] == "unsure"]
    test = [r for r in all_human if r["label"] in CLASSES]
    train = load_llm_train()
    design = "train: LLM-labelled posts; test: hand-labelled posts (unsure excluded)"
    if not train:
        train, test = split(sorted(test, key=lambda r: r["time"]))
        design = "train/test: time split of hand labels (no LLM labels found)"
    gold = [r["label"] for r in test]
    titles = [r["title"] for r in test]
    majority = max(CLASSES, key=lambda c: sum(r["label"] == c for r in train))
    preds = {"majority": [majority] * len(gold),
             "lexicon": [lexicon(t) for t in titles]}
    model = fit_tfidf(train)
    preds["tfidf_lr"] = list(model.predict(titles))

    check = sorted(__import__("glob").glob(os.path.join(ROOT, "data", "labels", "llm_done", "llm_check_99*.csv")))
    if check:
        llm = {r["post_id"]: r["label"] for r in _read_labelled(check[0])}
        preds["llm_labeller_direct"] = [llm.get(r["post_id"]) if llm.get(r["post_id"]) in CLASSES
                                        else "neutral" for r in test]
    extra = {}
    if use_llm:
        sys.path.insert(0, ROOT)
        from core import config
        labels, tin, tout = llm_fewshot(titles)
        preds["llm_fewshot_openrouter"] = labels
        cost = tin / 1e6 * config.PRICE_IN + tout / 1e6 * config.PRICE_OUT
        extra["llm_fewshot_openrouter"] = {"model": config.MODEL, "tokens_in": tin, "tokens_out": tout,
                                           "usd_per_1000_posts": round(1000 * cost / len(titles), 4)}
    extra.setdefault("tfidf_lr", {})["usd_per_1000_posts"] = 0.0

    report = {"design": design, "n_train": len(train), "n_test": len(test),
              "n_unsure_excluded": len(unsure),
              "test_period": [min(r["time"] for r in test)[:10], max(r["time"] for r in test)[:10]],
              "class_counts_train": {c: sum(r["label"] == c for r in train) for c in CLASSES},
              "class_counts_test": {c: gold.count(c) for c in CLASSES}, "methods": {}}
    for name, pred in preds.items():
        report["methods"][name] = dict({"macro_f1": macro_f1(gold, pred),
                                        "ci95": bootstrap_ci(gold, pred),
                                        "accuracy": round(sum(g == q for g, q in zip(gold, pred)) / len(gold), 4),
                                        "confusion_gold_by_pred": {g: {c: sum(1 for x, y in zip(gold, pred) if x == g and y == c)
                                                                       for c in CLASSES} for g in CLASSES}},
                                       **extra.get(name, {}))
    pa = predict(model, titles)
    raw = preds["tfidf_lr"]
    answered = [(g, p) for g, (p, _) in zip(gold, pa) if p != "uncertain"]
    abstained = [(g, r) for g, (p, _), r in zip(gold, pa, raw) if p == "uncertain"]
    report["abstention_tfidf"] = {
        "threshold": ABSTAIN_BELOW,
        "abstain_rate": round(len(abstained) / len(gold), 4) if gold else None,
        "error_rate_answered": round(sum(g != p for g, p in answered) / len(answered), 4) if answered else None,
        "error_rate_abstained_if_forced": round(sum(g != r for g, r in abstained) / len(abstained), 4) if abstained else None,
    }
    if unsure:
        report["unsure_posts_model_says"] = {r["title"][:40]: q for r, (q, _) in
                                             zip(unsure, predict(model, [u["title"] for u in unsure]))}
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    with open(os.path.join(ROOT, "results", "sentiment_eval.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def cmd_train():
    """Final model: LLM-labelled training rows if present, else human labels."""
    model = fit_tfidf(load_llm_train() or load_labels())
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, "wb") as fh:
        pickle.dump(model, fh)
    print("saved", MODEL_PATH)


def cmd_sample(n):
    """Hand-labelling sample: equal numbers per stock, spread evenly over the
    months of the year, own-bar posts only, fixed seed (6201)."""
    import collections
    raw = os.path.join(ROOT, "data", "raw")
    with open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8") as fh:
        codes = [w["code"] for w in json.load(fh)]
    rng = random.Random(6201)
    per_stock = n // len(codes)
    pick = []
    for code in codes:
        by_month = collections.defaultdict(list)
        with open(os.path.join(raw, "guba_%s.jsonl" % code), encoding="utf-8") as fh:
            for line in fh:
                p = json.loads(line)
                if p.get("bar_code") == code and p["title"].strip():
                    by_month[p["time"][:7]].append(p)
        months = sorted(by_month)
        for i in range(per_stock):
            pick.append(rng.choice(by_month[months[i % len(months)]]))
    out = os.path.join(ROOT, "data", "labels", "to_label.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:   # BOM so Excel shows Chinese
        w = csv.writer(fh)
        w.writerow(["post_id", "stock", "time", "title", "label", "note"])
        for p in sorted(pick, key=lambda p: p["time"]):
            w.writerow([p["post_id"], p["stock"], p["time"], p["title"], "", ""])
    print("wrote %d rows to %s - label them per LABEL_RULES.md, save as labelled.csv" % (len(pick), out))


def cmd_sample_llm(n, part_size=500):
    """Training sheet for LLM labelling: n own-bar posts, equal per stock,
    spread over months, EXCLUDING every post in the human test sheet.
    Also writes llm_check_300.csv: the human-test titles, shuffled and
    without labels, so the same LLM's accuracy can be measured."""
    import collections
    labels_dir = os.path.join(ROOT, "data", "labels")
    with open(os.path.join(labels_dir, "to_label.csv"), encoding="utf-8-sig") as fh:
        test_rows = list(csv.DictReader(fh))
    exclude = {r["post_id"] for r in test_rows}
    with open(os.path.join(ROOT, "data", "watchlist.json"), encoding="utf-8") as fh:
        codes = [w["code"] for w in json.load(fh)]
    rng = random.Random(62010)
    pick = []
    for code in codes:
        by_month = collections.defaultdict(list)
        with open(os.path.join(ROOT, "data", "raw", "guba_%s.jsonl" % code), encoding="utf-8") as fh:
            for line in fh:
                p = json.loads(line)
                if p.get("bar_code") == code and p["title"].strip() and str(p["post_id"]) not in exclude:
                    by_month[p["time"][:7]].append(p)
        months = sorted(by_month)
        quota = n // len(codes)
        # spread the quota over months; a short month (e.g. the 2 days of
        # 2026-10) gives what it has and the rest is redistributed
        taken = {m: 0 for m in months}
        while sum(taken.values()) < quota:
            progress = False
            for m in months:
                if sum(taken.values()) < quota and taken[m] < len(by_month[m]):
                    taken[m] += 1
                    progress = True
            if not progress:
                break
        for m in months:
            pick += rng.sample(by_month[m], taken[m])
    rng.shuffle(pick)
    for k in range(0, len(pick), part_size):
        path = os.path.join(labels_dir, "llm_part%d.csv" % (k // part_size + 1))
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["post_id", "title", "label"])
            for p in pick[k:k + part_size]:
                w.writerow([p["post_id"], p["title"], ""])
    check = [(r["post_id"], r["title"]) for r in test_rows]
    rng.shuffle(check)
    with open(os.path.join(labels_dir, "llm_check_300.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["post_id", "title", "label"])
        w.writerows([pid, t, ""] for pid, t in check)
    print("wrote %d rows in %d parts + llm_check_300.csv" % (len(pick), (len(pick) + part_size - 1) // part_size))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sample":
        cmd_sample(int(sys.argv[2]) if len(sys.argv) > 2 else 300)
    elif cmd == "sample_llm":
        cmd_sample_llm(int(sys.argv[2]) if len(sys.argv) > 2 else 3000)
    elif cmd == "eval":
        cmd_eval("--llm" in sys.argv)
    elif cmd == "train":
        cmd_train()
    else:
        print(__doc__)
