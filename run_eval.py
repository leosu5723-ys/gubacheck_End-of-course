#!/usr/bin/env python3
"""
GubaCheck - ENTRY POINT
=========================================================================
    python3 run_eval.py                 run the whole evaluation set
    python3 run_eval.py SPK-...         run one case, every turn shown
    python3 run_eval.py --prompt        print what the model is told
    python3 run_eval.py --prompt-v1     the weak descriptor version
    python3 run_eval.py --v1            run the set with descriptor v1
    --workers=4                         run cases in parallel (live backend)
    --trials=1                          one trial per case (default: 3 for negatives)

Default backend is "scripted": no key, no network, standard library only.
Live runs:  GUBACHECK_BACKEND=live OPENROUTER_API_KEY=... python3 run_eval.py

Writes results/results.json and results/judgement_queue.json. Every
number in PRODUCT.md's "reached" column comes from results.json.
=========================================================================
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config, harness, prompt  # noqa: E402


def main(argv):
    print(config.summary())
    flags = {a for a in argv[1:] if a.startswith("-")}
    args = [a for a in argv[1:] if not a.startswith("-")]

    if "--prompt" in flags or "--prompt-v1" in flags:
        prompt.audit("v1" if "--prompt-v1" in flags else "v2")
        return 0

    key = harness.load_key()
    if not key:
        print("\nNo cases in evals/cases.json yet. See evals/EVALS.md for how to write them.")
        return 1
    version = "v1" if "--v1" in flags else "v2"

    if args:
        case = next((c for c in key if c["case_id"] == args[0]), None)
        if case is None:
            print("No case %r in evals/cases.json" % args[0])
            return 1
        results, queue = harness.run_set([case], trials_for=lambda c: 1,
                                         verbose=True, prompt_version=version)
        print(json.dumps(results[0]["record"], ensure_ascii=False, indent=2)[:3000])
        print("CODE CHECK:", "PASS" if results[0]["passed"] else "FAIL " + "; ".join(results[0]["fails"]))
        print("JUDGEMENT CHECK (read the reason, tick each):")
        for item in queue[0]["must_record"]:
            print("  [ ]", item)
        return 0

    workers = int(next((a.split("=")[1] for a in argv if a.startswith("--workers=")), 1))
    trials = next((int(a.split("=")[1]) for a in argv if a.startswith("--trials=")), None)
    results, queue = harness.run_set(key, prompt_version=version, workers=workers,
                                     trials_for=(lambda c: trials) if trials else None)
    summary = harness.summarise(results)
    harness.print_report(summary, results)

    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    tag = "" if version == "v2" else "_v1"
    tag += "" if config.BACKEND == "scripted" else "_live_" + config.MODEL.replace("/", "_")
    with open(os.path.join(config.RESULTS_DIR, "results%s.json" % tag), "w", encoding="utf-8") as fh:
        json.dump({"config": config.summary(), "prompt_version": version,
                   "summary": summary, "results": results}, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(config.RESULTS_DIR, "judgement_queue%s.json" % tag), "w", encoding="utf-8") as fh:
        json.dump(queue, fh, ensure_ascii=False, indent=2)
    print("\n  Wrote results/results%s.json and results/judgement_queue%s.json" % (tag, tag))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
