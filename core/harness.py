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

DECISIONS = ["paper_trade", "await_confirmation", "flag_do_not_chase"]


def load_key():
    path = os.path.join(config.EVALS_DIR, "cases.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def code_check(record, expected):
    """Returns (passed, [reasons]). Wording, turns and cost are NOT compared."""
    fails = []
    if record.get("decision") != expected["expected_decision"]:
        fails.append("decision %r, expected %r" % (record.get("decision"), expected["expected_decision"]))
    if expected.get("trigger") and record.get("trigger") != expected["trigger"]:
        fails.append("trigger %r, expected %r" % (record.get("trigger"), expected["trigger"]))
    if expected.get("evidence_id") and record.get("evidence_id") != expected["evidence_id"]:
        fails.append("evidence_id %r, expected %r" % (record.get("evidence_id"), expected["evidence_id"]))
    return (not fails), fails


def run_set(cases, trials_for=None, verbose=False, prompt_version="v2"):
    trials_for = trials_for or (lambda c: 3 if c.get("negative") else 1)
    results, queue = [], []
    for c in cases:
        for trial in range(1, trials_for(c) + 1):
            rec = run_case(c["case_id"], verbose=verbose, prompt_version=prompt_version)
            ok, fails = code_check(rec, c)
            results.append({"case_id": c["case_id"], "trial": trial, "passed": ok,
                            "fails": fails, "family": c.get("family"),
                            "expected": c["expected_decision"], "record": rec})
            if trial == 1:
                queue.append({"case_id": c["case_id"], "decision": rec.get("decision"),
                              "reason": rec.get("reason", ""),
                              "must_record": c.get("must_record", []),
                              "verdict": None, "graded_by": None})
    return results, queue


def summarise(results):
    n = len(results)
    passed = sum(r["passed"] for r in results)
    turns = [r["record"]["turns"] for r in results]
    # The most expensive mistake: acting on something that should not be acted on.
    should_not_act = [r for r in results if r["expected"] != "paper_trade"]
    false_act = sum(1 for r in should_not_act if r["record"].get("decision") == "paper_trade")
    confusion = {e: {g: 0 for g in DECISIONS + ["other"]} for e in DECISIONS}
    for r in results:
        got = r["record"].get("decision")
        confusion[r["expected"]][got if got in DECISIONS else "other"] += 1
    return {
        "trials": n, "passed": passed,
        "pass_rate": round(passed / n, 4) if n else None,
        "false_act_rate": round(false_act / len(should_not_act), 4) if should_not_act else None,
        "false_act_trials": "%d of %d" % (false_act, len(should_not_act)),
        "median_turns": statistics.median(turns) if turns else None,
        "worst_turns": max(turns) if turns else None,
        "hit_step_cap": sum(1 for r in results if r["record"]["stopped_by"] == "step_cap"),
        "total_cost_usd": round(sum(r["record"]["cost_usd"] for r in results), 6),
        "mean_cost_usd": round(statistics.mean(r["record"]["cost_usd"] for r in results), 6) if n else None,
        "confusion_expected_by_got": confusion,
    }


def print_report(s, results):
    print("\n" + "=" * 70)
    print("  PASS RATE   %s of %s trials  (%s)" % (s["passed"], s["trials"],
          "-" if s["pass_rate"] is None else "%.0f%%" % (100 * s["pass_rate"])))
    print("  FALSE ACT   %s  (acted when the key says do not)" % s["false_act_trials"])
    print("  turns       median %s, worst %s, step-cap hits %s"
          % (s["median_turns"], s["worst_turns"], s["hit_step_cap"]))
    print("  cost        US$%.4f total, US$%.5f per trial" % (s["total_cost_usd"], s["mean_cost_usd"] or 0))
    print("=" * 70)
    for r in results:
        if not r["passed"]:
            print("  FAIL %-28s trial %d [%s]: %s" % (r["case_id"], r["trial"], r["family"], "; ".join(r["fails"])))
    print("\n  Before fixing the agent, ask whether the LABEL is right.")
