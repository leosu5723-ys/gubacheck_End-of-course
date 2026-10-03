#!/usr/bin/env python3
"""
GubaCheck - TWO REPRODUCED FAILURES (v4)
=========================================================================
    python3 demo_failures.py

Each failure is "the working system minus X"; putting X back restores it.
Both run on the scripted backend: no key, no cost, identical every time.

FAILURE 1 - loop control (code layer), X = action de-duplication
    The model repeats a cause test it already ran. Nothing crashes. Each
    repeat multiplies that cause's weight again (PASS x3, x3, x3 ...), so the
    posterior silently drifts towards whatever was repeated and the stop
    rule fires on evidence that was counted several times. De-duplication
    refuses the repeat; the step cap only bounds the damage.

FAILURE 2 - tool interface, X = the timing rule in check_D
    Without "the US session must close BEFORE the A-share open", the tool
    may pair a spike with the US session of the SAME calendar date, which
    happened after the A-share close: an explanation that could not have
    caused the move. The fix belongs in the tool (it decides which session
    is eligible), not in a prompt sentence asking the model to mind time.
=========================================================================
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import causes, config, store  # noqa: E402
from core.agent import run_case  # noqa: E402
from core.guardrails import Guardrails  # noqa: E402


class NoDedup(Guardrails):
    def check_duplicate(self, tool, args):
        return None


def failure_1(sid="SPK-600150-20260831"):
    moves = [{"thought": "fetch", "calls": [["get_spike", {"spike_id": sid}]]},
             {"thought": "score", "calls": [["score_causes", {"scores": {"C": 4, "E": 4, "A": 2}}]]}]
    moves += [{"thought": "test E again (no memory of the last call)", "calls": [["check_E", {"spike_id": sid}]]}
              for _ in range(6)]
    moves.append({"thought": "conclude", "final": {"primary": "?", "reason": "-"}})
    print("\nFAILURE 1 - loop control (minus de-duplication)")
    for label, guards in (("working", None), ("minus de-dup", NoDedup(config.MAX_TURNS, config.MAX_TOKENS_PER_RUN,
                                                                      config.AUTONOMY))):
        rec = run_case(sid, moves=moves, guards=guards, arm="agent")
        inv = rec.get("investigation", {})
        print("  %-14s turns=%d  cause tests=%d  order=%s  posterior(E)=%.2f  primary=%s  stopped_by=%s"
              % (label, rec["turns"], inv.get("calls", 0), "".join(inv.get("order", [])),
                 inv.get("posterior", {}).get("E", 0), rec.get("code_primary"), rec["stopped_by"]))


def failure_2():
    print("\nFAILURE 2 - tool interface (minus the US-before-open timing rule)")
    spikes = [s for s in store.load("spikes") if not s.get("synthetic")]
    working = {s["spike_id"]: causes.check_D(s["spike_id"]) for s in spikes}
    causes.US_BEFORE_OPEN = False          # minus X
    broken = {s["spike_id"]: causes.check_D(s["spike_id"]) for s in spikes}
    causes.US_BEFORE_OPEN = True           # X restored
    flips = [k for k in working if working[k]["verdict"] != broken[k]["verdict"]]
    late = sum(1 for k in broken for r in broken[k]["evidence"]
               if r.get("us_date", "") >= store.spike(k)["date"])
    print("  verdicts that change once the timing rule is removed: %d of %d spikes" % (len(flips), len(spikes)))
    print("  US sessions used that closed AFTER the A-share session they 'explain': working 0, minus rule %d" % late)
    for k in flips[:5]:
        print("   ", k, working[k]["verdict"], "->", broken[k]["verdict"])


if __name__ == "__main__":
    failure_1()
    failure_2()
