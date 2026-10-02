"""
GubaCheck - THE AGENT LOOP
=========================================================================
    thought -> tool calls -> observations -> repeat -> final decision

A hand-written ReAct loop. It is short on purpose: when a run goes wrong,
the twenty lines that did it can be read.

What makes this an agent rather than a fixed pipeline: the number of
turns depends on the case. A post that addresses the system ends after
one turn; a claim the first search misses needs a second search with
different terms; a supported claim goes on to typing, tradability and an
order. The data decides the path, not the code.

Instrumentation is part of the loop, not an add-on: every run records
turns, tokens, cost, every tool call and every guardrail event, because
the cost model and the failure analysis both need numbers captured while
the run happened.

Isolation: everything a run needs is created inside run_case(). No case
depends on a previous one.
=========================================================================
"""
import time

from core import config, prompt, store, tools
from core.backends import make_backend
from core.guardrails import GuardrailStop, Guardrails


def run_case(case_id, approve=None, moves=None, prompt_version="v2",
             verbose=False, guards=None):
    """Run one spike case from a clean state; return the decision record.

    approve   callable(action, payload) -> bool, the human at the gate.
              Defaults to "yes" so scripted runs are deterministic; the
              record still shows the gate was reached.
    moves     optional explicit move list (guardrail and failure demos).
    guards    optional Guardrails instance (failure demos delete one guard).
    """
    started = time.time()
    guards = guards or Guardrails(config.MAX_TURNS, config.MAX_TOKENS_PER_RUN, config.AUTONOMY)
    backend = make_backend(case_id, prompt.build_system_prompt(prompt_version), moves)
    approve = approve or (lambda action, payload: True)

    transcript, calls_made = [], []
    turns = tokens_in = tokens_out = 0
    stopped_by = None

    try:
        for _ in range(config.MAX_TURNS + 2):          # loop safety; the cap is in guards
            move = backend.next_move(transcript)
            ti, to = backend.last_usage
            tokens_in, tokens_out = tokens_in + ti, tokens_out + to
            guards.check_budget(tokens_in + tokens_out)

            if verbose:
                label = "conclude" if "final" in move else "turn %d" % (turns + 1)
                print("  %-9s %s" % (label, move.get("thought", "")[:100]))

            if "final" in move:
                record = dict(move["final"])
                break

            turns += 1
            guards.check_turns(turns)
            observations = []
            for name, args in move.get("calls", []):
                guards.check_duplicate(name, args)
                if name == tools.GATED_ACTION:
                    guards.check_order(args, store.announcement)
                    if not guards.gate(name, args, approve):
                        raise GuardrailStop("gate_held", "order awaits my approval")
                result = tools.call(name, args)
                guards.note_observation(result)
                calls_made.append({"tool": name, "args": args})
                observations.append({"tool": name, "args": args, "result": result})
                if verbose:
                    print("            %-20s -> %s" % (name, _short(result)))

            transcript.append({"role": "assistant", "content": move.get("thought", "")})
            transcript.append({"role": "user", "content": repr(observations)})
        else:
            raise GuardrailStop("step_cap", "loop safety limit")
    except GuardrailStop as stop:
        stopped_by = stop.reason
        trigger = "hostile_text" if stop.reason == "hostile_text" else "halted_" + stop.reason
        record = {"decision": "flag_do_not_chase", "trigger": trigger,
                  "reason": "halted by the %s guardrail: %s" % (stop.reason, stop.detail)}

    record.update({
        "case_id": case_id,
        "tool_calls": calls_made,
        "turns": turns,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(tokens_in / 1e6 * config.PRICE_IN + tokens_out / 1e6 * config.PRICE_OUT, 6),
        "seconds": round(time.time() - started, 3),
        "guardrails_fired": guards.fired,
        "stopped_by": stopped_by,
        "backend": backend.name,
    })
    return record


def _short(value, n=90):
    s = repr(value)
    return s if len(s) <= n else s[:n - 1] + "..."
