"""
GubaCheck - MODEL COMPARISON (same spikes, same tools, same prompt)
=========================================================================
    python3 -m pipeline.model_compare                       full-run table (below)
    python3 -m pipeline.model_compare SPK-300308-20260728 \
        --models=deepseek/deepseek-v4.1-flash,anthropic/claude-haiku-4.5 [--arm=routing]
                                                            SINGLE-RUN mode: one spike, one live
        run per model -> conclusion, tests in order, tokens, billed US$, seconds.
        Writes results/model_single_<spike>_<arm>.json. Needs OPENROUTER_API_KEY;
        costs about a cent per model. One run says how a model behaves and what it
        costs, not which model is more accurate.

READS (full-run mode)     every results/results_<arm>_live_<model>.json written by
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


def single(spike_id, models, arm="routing"):
    import time
    from core import config, pricing
    from core.agent import run_case
    if not config.API_KEY:
        raise SystemExit("Single-run mode is live: set OPENROUTER_API_KEY first.")
    cases = json.load(open(os.path.join(ROOT, "evals", "cases.json"), encoding="utf-8"))
    gold = next((c.get("expected_primary") for c in cases if c["case_id"] == spike_id), None)
    config.BACKEND = "live"
    rows = []
    for m in models:
        config.MODEL = m
        p = pricing.price_of(m)
        if p:
            config.PRICE_IN, config.PRICE_OUT = p
        t0 = time.time()
        try:
            rec = run_case(spike_id, arm=arm)
        except Exception as e:                       # one model failing never stops the others
            rec = {"error": str(e)[:200], "tokens_in": 0, "tokens_out": 0, "cost_usd": 0}
        inv = rec.get("investigation") or {}
        rows.append({"model": m, "arm": arm, "primary": rec.get("primary"), "secondary": rec.get("secondary"),
                     "gold": gold, "correct": (rec.get("primary") == gold) if gold else None,
                     "tests": inv.get("order"), "verdicts": inv.get("tested"), "revisions": inv.get("revisions"),
                     "turns": rec.get("turns"), "tokens_in": rec["tokens_in"], "tokens_out": rec["tokens_out"],
                     "usd": rec["cost_usd"], "cost_basis": rec.get("cost_source"), "seconds": round(time.time() - t0, 1),
                     "price_per_1m": p, "reason": (rec.get("reason") or "")[:300], "error": rec.get("error")})
    out = os.path.join(R, "model_single_%s_%s.json" % (spike_id, arm))
    json.dump({"spike_id": spike_id, "arm": arm, "gold": gold, "rows": rows}, open(out, "w"), ensure_ascii=False, indent=1)
    print("%s  arm=%s  my label=%s\n" % (spike_id, arm, gold))
    print("%-30s %-4s %-3s %-22s %7s %6s %9s %6s" % ("model", "pri", "ok", "tests (order)", "tok in", "out", "US$", "sec"))
    for r in rows:
        if r["error"]:
            print("%-30s ERROR %s" % (r["model"][:30], r["error"]))
            continue
        tests = " ".join("%s%s" % (c, (r["verdicts"] or {}).get(c, "?")[:1]) for c in r["tests"] or [])
        print("%-30s %-4s %-3s %-22s %7d %6d %9.5f %6.1f" % (r["model"][:30], r["primary"], "✓" if r["correct"] else "✗",
                                                          tests, r["tokens_in"], r["tokens_out"], r["usd"], r["seconds"]))
    print("\n(tests: cause + P/A/F = PASS / pARTIAL / FAIL)  Wrote %s" % os.path.relpath(out, ROOT))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    if args:
        sys.exit(single(args[0], [m for m in opts.get("models", "").split(",") if m] or [REFERENCE],
                        opts.get("arm", "routing")))
    sys.exit(main())
