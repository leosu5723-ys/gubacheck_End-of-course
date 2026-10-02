#!/usr/bin/env python3
"""
GubaCheck - GUARDRAIL CHECKLIST RUNNER
=========================================================================
    python3 run_guardrails.py

Runs every case in evals/guardrail_cases.json on the scripted backend.
A guardrail case is not an evaluation case: it does not ask "was the
decision right?", it asks "did the system refuse, cap or stop when it
should have?". Each case scripts the bad attempt (e.g. an order after a
hostile post) and states which guard must fire.

Writes results/guardrails.json - the table in EVALS.md comes from it.
=========================================================================
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config  # noqa: E402
from core.agent import run_case  # noqa: E402
from core.guardrails import Guardrails  # noqa: E402


def main():
    path = os.path.join(config.EVALS_DIR, "guardrail_cases.json")
    if not os.path.exists(path):
        print("No evals/guardrail_cases.json yet.")
        return 1
    with open(path, encoding="utf-8") as fh:
        cases = json.load(fh)

    rows, ok_count = [], 0
    for g in cases:
        guards = Guardrails(g.get("max_turns", config.MAX_TURNS),
                            g.get("max_tokens", config.MAX_TOKENS_PER_RUN),
                            g.get("autonomy", config.AUTONOMY))
        approve = (lambda a, p: True) if g.get("approve", True) else (lambda a, p: False)
        rec = run_case(g["spike_id"], approve=approve, moves=g["moves"], guards=guards)
        fired = [f["guardrail"] for f in rec["guardrails_fired"]]
        exp = g["expect"]
        ok = True
        if "guardrail_fired" in exp and exp["guardrail_fired"] not in fired:
            ok = False
        if "decision" in exp and rec.get("decision") != exp["decision"]:
            ok = False
        if "trigger" in exp and rec.get("trigger") != exp["trigger"]:
            ok = False
        if exp.get("no_order") and any(c["tool"] == "place_paper_order" for c in rec["tool_calls"]):
            ok = False
        ok_count += ok
        rows.append({"id": g["id"], "catches": g["wrong_behaviour"], "passed": ok,
                     "observed": {"decision": rec.get("decision"), "trigger": rec.get("trigger"),
                                  "stopped_by": rec["stopped_by"], "fired": fired,
                                  "turns": rec["turns"]}})
        print("%-4s %-4s %-58s fired=%s" % (g["id"], "PASS" if ok else "FAIL",
                                            g["wrong_behaviour"][:58], ",".join(fired) or "-"))

    print("\n%d of %d guardrail cases behaved as required" % (ok_count, len(cases)))
    os.makedirs(config.RESULTS_DIR, exist_ok=True)
    with open(os.path.join(config.RESULTS_DIR, "guardrails.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    return 0 if ok_count == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
