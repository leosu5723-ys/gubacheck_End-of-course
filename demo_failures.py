#!/usr/bin/env python3
"""
GubaCheck - TWO REPRODUCED FAILURES
=========================================================================
    python3 demo_failures.py [SPIKE_ID]

Each failure is built as a DELETION from the working system ("the working
agent, minus X"). Putting X back restores the behaviour, which is what
makes it a diagnosis rather than a story. Both run on the scripted
backend, cost nothing, and reproduce exactly.

FAILURE 1 - loop control (code layer)
    X = action de-duplication. After an empty CNINFO search, the agent
    repeats the identical search. With the guard deleted there is no
    error and no crash: it burns turns and tokens until the step cap.
    The step cap and budget ceiling only bound the damage; only
    de-duplication detects the fault.

FAILURE 2 - tool interface
    X = the search window limit and snippet trimming in search_news.
    Without them, an old article that mentions the same keyword comes
    back, and a long body dominates the observation. The fix belongs in
    the tool, not in a prompt sentence: the model cannot be relied on to
    ignore what the tool hands it.
=========================================================================
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import config, store, tools  # noqa: E402
from core.agent import run_case  # noqa: E402
from core.guardrails import Guardrails  # noqa: E402


class NoDedup(Guardrails):
    """The working guardrail layer, minus action de-duplication."""

    def check_duplicate(self, tool, args):
        return None


def failure_1(spike_id):
    s = tools.get_spike(spike_id)
    if s is None:
        print("Spike %s not in the snapshot." % spike_id)
        return
    search = ["search_cninfo", {"stock": s["stock"], "keywords": ["不存在的关键词"],
                                "date_from": s["date"], "date_to": s["date"]}]
    moves = [{"thought": "fetch the spike", "calls": [["get_spike", {"spike_id": spike_id}]]}]
    moves += [{"thought": "search again (the agent has no memory of its last call)",
               "calls": [search]} for _ in range(12)]
    print("\nFAILURE 1 - loop control")
    for label, guards in (("with de-dup (working)", None),
                          ("minus de-dup", NoDedup(config.MAX_TURNS, config.MAX_TOKENS_PER_RUN,
                                                   config.AUTONOMY))):
        rec = run_case(spike_id, moves=moves, guards=guards)
        print("  %-24s turns=%-2d tokens=%-6d cost=US$%.5f stopped_by=%s"
              % (label, rec["turns"], rec["tokens_in"] + rec["tokens_out"],
                 rec["cost_usd"], rec["stopped_by"]))


def failure_2(spike_id):
    s = tools.get_spike(spike_id)
    if s is None:
        return
    terms = [s["name"]] + s.get("aliases", [])
    print("\nFAILURE 2 - tool interface (news window and trimming)")
    working = tools.search_news(terms, _shift(s["date"], -14), s["date"])
    saved = (config.SEARCH_WINDOW_MAX_DAYS, config.NEWS_CONTENT_CHARS)
    config.SEARCH_WINDOW_MAX_DAYS, config.NEWS_CONTENT_CHARS = 10_000, 100_000
    broken = tools.search_news(terms, "2000-01-01", s["date"])
    config.SEARCH_WINDOW_MAX_DAYS, config.NEWS_CONTENT_CHARS = saved
    for label, obs in (("working", working), ("minus window+trim", broken)):
        items = obs.get("results", [])
        stale = sum(1 for i in items if i["time"][:10] < _shift(s["date"], -14))
        print("  %-18s items=%d stale(>14d)=%d observation_chars=%d"
              % (label, len(items), stale, len(repr(obs))))


def _shift(day, n):
    from datetime import date, timedelta
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else (store.load("spikes")[0]["spike_id"]
                                                 if store.load("spikes") else None)
    if not sid:
        print("No spikes in the snapshot yet.")
        sys.exit(1)
    failure_1(sid)
    failure_2(sid)
