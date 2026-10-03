"""
GubaCheck - MODEL COMPARISON (same spikes, same tools, same prompt)
=========================================================================
    python3 -m pipeline.model_compare

READS     every results/results_<arm>_live_<model>.json written by
          `GUBACHECK_BACKEND=live GUBACHECK_MODEL=<id> python3 run_eval.py --arm=<arm>`
WRITES    results/model_compare.json and prints one table:
          model x arm -> accuracy, macro-F1, tests per spike, revisions,
          errors, tokens per spike, US$ per spike (billed when the provider
          reported it, else tokens x price), and the paired win/loss against
          the reference model on the same spikes (exact McNemar p).
WATCH OUT one live trial per spike; 68 spikes. A difference of a few cases
          is noise - read the paired p, not the accuracy gap.
=========================================================================
"""
import glob
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = os.path.join(ROOT, "results")
REFERENCE = "deepseek/deepseek-v4.1-flash"


def load():
    runs = {}
    for f in sorted(glob.glob(os.path.join(R, "results_*_live_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        s = d.get("summary", {})
        recs = d.get("results", [])
        if not recs or not s.get("arm"):
            continue
        model = next((r["record"].get("model") for r in recs if r["record"].get("model")), None) or \
            os.path.basename(f).split("_live_")[1][:-5].replace("_", "/", 1)
        runs[(model, s["arm"])] = d
    return runs


def mcnemar(b, c):
    n = b + c
    return min(1.0, 2 * sum(math.comb(n, j) for j in range(min(b, c) + 1)) / 2 ** n) if n else 1.0


def main():
    runs = load()
    rows = []
    for (model, arm), d in sorted(runs.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        s, recs = d["summary"], d["results"]
        ok = {r["case_id"]: bool(r["passed"]) for r in recs if not r["record"].get("error")}
        n = len(recs)
        tokens = sum(r["record"]["tokens_in"] + r["record"]["tokens_out"] for r in recs)
        cost = sum(r["record"]["cost_usd"] for r in recs)
        billed = all(r["record"].get("cost_source") == "billed" for r in recs if not r["record"].get("error"))
        revs = sum((r["record"].get("investigation") or {}).get("revisions", 0) > 0 for r in recs)
        row = {"model": model, "arm": arm, "spikes": n, "errors": s.get("errors", 0),
               "accuracy": s.get("accuracy"), "macro_f1": s.get("macro_f1"),
               "tests_per_spike": s.get("mean_cause_checks"), "runs_with_revision": revs,
               "tokens_per_spike": round(tokens / n), "usd_per_spike": round(cost / n, 5),
               "usd_total": round(cost, 4), "cost_basis": "billed" if billed else "tokens x price",
               "premature_stops": s.get("premature_stops"), "recall_by_cause": s.get("recall_by_cause")}
        ref = runs.get((REFERENCE, arm))
        if ref and model != REFERENCE:
            rok = {r["case_id"]: bool(r["passed"]) for r in ref["results"] if not r["record"].get("error")}
            both = set(ok) & set(rok)
            b = sum(ok[i] and not rok[i] for i in both)
            c = sum(rok[i] and not ok[i] for i in both)
            row["vs_reference"] = {"only_this_right": b, "only_reference_right": c, "p": round(mcnemar(b, c), 3)}
        rows.append(row)
    json.dump({"reference": REFERENCE, "rows": rows}, open(os.path.join(R, "model_compare.json"), "w"), indent=1)
    print("%-34s %-8s %5s %6s %5s %5s %4s %8s %10s  %s" % ("model", "arm", "n", "acc", "mF1", "tests", "rev",
                                                          "tok/spk", "US$/spike", "vs reference (this/ref, p)"))
    for r in rows:
        v = r.get("vs_reference")
        print("%-34s %-8s %5d %5.1f%% %5.2f %5.2f %4d %8d %10.5f  %s%s" % (
            r["model"][:34], r["arm"], r["spikes"], 100 * (r["accuracy"] or 0), r["macro_f1"] or 0,
            r["tests_per_spike"] or 0, r["runs_with_revision"], r["tokens_per_spike"], r["usd_per_spike"],
            ("%d / %d, p=%.2f" % (v["only_this_right"], v["only_reference_right"], v["p"])) if v else "reference",
            "  (%d errors)" % r["errors"] if r["errors"] else ""))
    print("\nWrote results/model_compare.json")


if __name__ == "__main__":
    sys.exit(main())
