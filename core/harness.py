"""
GubaCheck - EVALUATION HARNESS
=========================================================================
Load the answer key, run every case, grade, report.

Two kinds of check, and the project needs both:

  CODE CHECK       decision, trigger and evidence_id compared with the key.
                   Deterministic, free. Produces the headline pass rate.
  JUDGEMENT CHECK  a person reads each reason and rules on the key's
                   must_record items ("names the announcement", "says what
                   was searched"). The harness only builds the queue in
                   results/judgement_queue.json; it does not grade it.

Why both: with three outcomes a coin flip scores 33% on the code check,
and a run can reach the right decision for the wrong reason.

The answer key (evals/cases.json) was written and committed before any
agent run was graded. Its git history is the evidence for that.

Trials: ordinary cases run once, negative cases (await / flag) three
times, because negatives are the cases that flip between live runs.
Every pass rate is printed with its trial count.
=========================================================================
"""
import json
import os
import statistics

from core import config
from core.agent import run_case

DECISIONS = ["paper_trade", "no_trade"]


def load_key():
    path = os.path.join(config.EVALS_DIR, "cases.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def code_check(record, expected):
    """v4: the primary cause the run concluded vs my hand label.
    (Legacy cases with expected_decision are still supported.)"""
    if "expected_primary" in expected:
        if not expected["expected_primary"]:
            return None, ["not labelled"]
        got = record.get("primary")
        return got == expected["expected_primary"], ([] if got == expected["expected_primary"] else
                                                     ["primary %r, expected %r" % (got, expected["expected_primary"])])
    fails = []
    if record.get("decision") != expected.get("expected_decision"):
        fails.append("decision %r, expected %r" % (record.get("decision"), expected.get("expected_decision")))
    if expected.get("trigger") and record.get("trigger") != expected["trigger"]:
        fails.append("trigger %r, expected %r" % (record.get("trigger"), expected["trigger"]))
    if expected.get("evidence_id") and record.get("evidence_id") != expected["evidence_id"]:
        fails.append("evidence_id %r, expected %r" % (record.get("evidence_id"), expected["evidence_id"]))
    return (not fails), fails


def run_set(cases, trials_for=None, verbose=False, prompt_version="v2", workers=1, arm="agent"):
    """Run every case (and trial); workers > 1 runs cases in parallel threads
    (useful on the live backend, where each model call takes seconds)."""
    trials_for = trials_for or (lambda c: 1 if "expected_primary" in c else (3 if c.get("negative") else 1))
    jobs = [(c, t) for c in cases for t in range(1, trials_for(c) + 1)]

    import threading
    lock = threading.Lock()
    ckpt = checkpoint_path(arm, prompt_version)
    done = {}
    if ckpt and os.path.exists(ckpt):
        for line in open(ckpt, encoding="utf-8"):
            r = json.loads(line)
            done[(r["case_id"], r["trial"])] = r

    def one(job):
        c, trial = job
        if (c["case_id"], trial) in done:                 # finished in an earlier, interrupted run
            r = done[(c["case_id"], trial)]
            r["passed"], r["fails"] = code_check(r["record"], c)
            return r
        try:
            rec = run_case(c["case_id"], verbose=verbose, prompt_version=prompt_version, arm=arm)
        except Exception as e:                            # one bad case must not sink the batch
            rec = {"case_id": c["case_id"], "arm": arm, "primary": None, "error": str(e)[:300],
                   "turns": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "stopped_by": "error",
                   "investigation": {"calls": 0}}
            print("  ERROR %s: %s" % (c["case_id"], str(e)[:120]), flush=True)
        ok, fails = code_check(rec, c)
        r = {"case_id": c["case_id"], "trial": trial, "passed": ok, "fails": fails,
             "family": c.get("family"), "period": c.get("period"),
             "expected": c.get("expected_primary", c.get("expected_decision")), "record": rec}
        if ckpt and "error" not in rec:
            with lock, open(ckpt, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
        with lock:
            n_done[0] += 1
            if n_done[0] % 5 == 0:
                print("  %d/%d done" % (n_done[0], len(jobs)), flush=True)
        return r
    n_done = [0]

    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, jobs))
    else:
        results = [one(j) for j in jobs]
    queue = [{"case_id": r["case_id"], "decision": r["record"].get("decision"),
              "reason": r["record"].get("reason", ""),
              "must_record": next(c for c in cases if c["case_id"] == r["case_id"]).get("must_record", []),
              "verdict": None, "graded_by": None} for r in results if r["trial"] == 1]
    return results, queue


def checkpoint_path(arm, prompt_version):
    """Live runs only: one line per finished case, so an interrupted run resumes."""
    if config.BACKEND != "live":
        return None
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    return os.path.join(config.RESULTS_DIR, "checkpoint_%s_%s_%s.jsonl"
                        % (arm, prompt_version, config.MODEL.replace("/", "_")))


def summarise(results):
    return summarise_v4(results)


def summarise_v4(results):
    import collections
    errors = [r for r in results if r["record"].get("error")]
    results = [r for r in results if not r["record"].get("error")]
    graded = [r for r in results if r["passed"] is not None]
    calls = [r["record"].get("investigation", {}).get("calls", 0) for r in results]
    toks = [r["record"]["tokens_in"] + r["record"]["tokens_out"] for r in results]
    premature = 0
    for r in graded:
        inv = r["record"].get("investigation", {})
        if not r["passed"] and r["expected"] not in ("H",) and r["expected"] not in inv.get("tested", {}):
            premature += 1
    by_period = {}
    for per in ("observe", "check"):
        g = [r for r in graded if r.get("period") == per]
        by_period[per] = {"n": len(g), "accuracy": round(sum(r["passed"] for r in g) / len(g), 4) if g else None}
    conf = collections.defaultdict(collections.Counter)
    for r in graded:
        conf[r["expected"]][r["record"].get("primary")] += 1
    labels = sorted({r["expected"] for r in graded} | {r["record"].get("primary") for r in graded} - {None})

    def macro_f1(pairs):
        f1s = []
        for c in sorted({g for g, _ in pairs}):
            tp = sum(1 for g, p in pairs if g == c and p == c)
            fp = sum(1 for g, p in pairs if g != c and p == c)
            fn = sum(1 for g, p in pairs if g == c and p != c)
            f1s.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
        return round(sum(f1s) / len(f1s), 4) if f1s else None
    pairs = [(r["expected"], r["record"].get("primary")) for r in graded]
    majority = collections.Counter(g for g, _ in pairs).most_common(1)[0] if pairs else (None, 0)
    return {
        "arm": results[0]["record"].get("arm") if results else None,
        "errors": len(errors),
        "macro_f1": macro_f1(pairs),
        "majority_class": majority[0],
        "majority_baseline_accuracy": round(majority[1] / len(pairs), 4) if pairs else None,
        "majority_baseline_macro_f1": macro_f1([(g, majority[0]) for g, _ in pairs]),
        "recall_by_cause": {c: "%d/%d" % (sum(1 for g, p in pairs if g == c and p == c), sum(1 for g, _ in pairs if g == c))
                            for c in sorted({g for g, _ in pairs})},
        "runs": len(results), "graded": len(graded),
        "accuracy": round(sum(r["passed"] for r in graded) / len(graded), 4) if graded else None,
        "accuracy_by_period": by_period,
        "always_H_baseline": round(sum(r["expected"] == "H" for r in graded) / len(graded), 4) if graded else None,
        "mean_cause_checks": round(statistics.mean(calls), 3) if calls else None,
        "median_turns": statistics.median(r["record"]["turns"] for r in results) if results else None,
        "worst_turns": max(r["record"]["turns"] for r in results) if results else None,
        "mean_tokens": round(statistics.mean(toks)) if toks else None,
        "total_cost_usd": round(sum(r["record"]["cost_usd"] for r in results), 6),
        "over_investigation_runs": sum(1 for r in results if r["record"].get("investigation", {}).get("over_investigation")),
        "premature_stops": premature,
        "model_vs_code_primary_disagree": sum(1 for r in results if r["record"].get("primary") != r["record"].get("code_primary")),
        "predicted": dict(collections.Counter(r["record"].get("primary") for r in results)),
        "confusion_gold_by_pred": {k: dict(v) for k, v in conf.items()},
    }


def print_report(s, results):
    print("\n" + "=" * 70)
    print("  ARM %s   runs %d   graded %d" % (s["arm"], s["runs"], s["graded"]))
    if s["accuracy"] is not None:
        print("  primary-cause accuracy  %.0f%%  macro-F1 %.2f  | always-%s baseline: accuracy %.0f%%, macro-F1 %.2f | always-H %.0f%%"
              % (100 * s["accuracy"], s["macro_f1"], s["majority_class"], 100 * s["majority_baseline_accuracy"],
                 s["majority_baseline_macro_f1"], 100 * s["always_H_baseline"]))
        print("  recall by cause         %s" % s["recall_by_cause"])
        print("  by period               %s" % s["accuracy_by_period"])
    print("  mean cause checks %.2f | median turns %s, worst %s | mean tokens %s | cost US$%.4f"
          % (s["mean_cause_checks"], s["median_turns"], s["worst_turns"], s["mean_tokens"], s["total_cost_usd"]))
    if s.get("errors"):
        print("  !! %d runs failed (network / provider) - re-run the same command to retry only those" % s["errors"])
    print("  over-investigation runs %d | premature stops %d | model/code primary disagree %d"
          % (s["over_investigation_runs"], s["premature_stops"], s["model_vs_code_primary_disagree"]))
    print("  predicted %s" % s["predicted"])
    print("=" * 70)
