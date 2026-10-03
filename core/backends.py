"""
GubaCheck - BACKENDS: who decides the agent's next move
=========================================================================
A backend answers one question: given the conversation so far, what does
the agent do next? It returns either
    {"thought": "...", "calls": [[tool, {args}], ...]}     call tools
    {"thought": "...", "final": {...}}                       conclude

ScriptedBackend replays moves written in evals/scripted_moves.json. The
tools underneath still run for real against the snapshot; only the
model's choices are pre-written. That makes the full evaluation free and
identical on every machine, and it is the right way to test code-layer
guardrails, because a model has no say in whether a guard fires.

LiveBackend calls a real model through OpenRouter and records the token
usage the API reports, so cost figures are measured, not estimated.

Only `_live_call` knows a vendor exists. Changing vendor means editing
that function plus MODEL / BASE_URL in config.py.
=========================================================================
"""
import json
import os
import urllib.request

from core import config

_SCRIPTS = None


def scripts(arm="keyword"):
    """Scripted move lists for one arm, keyed by case id."""
    global _SCRIPTS
    if _SCRIPTS is None:
        _SCRIPTS = {}
    if arm not in _SCRIPTS:
        path = os.path.join(config.EVALS_DIR, "scripted_moves_%s.json" % arm)
        if not os.path.exists(path):
            path = os.path.join(config.EVALS_DIR, "scripted_moves.json")
        loaded = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
        _SCRIPTS[arm] = loaded       # assign only once fully loaded (threads may race here)
    return _SCRIPTS[arm]


class ScriptedBackend:
    name = "scripted"

    def __init__(self, case_id, moves=None, arm="keyword"):
        if moves is None:
            if case_id not in scripts(arm):
                raise SystemExit("No scripted moves for %r in evals/scripted_moves.json. "
                                 "Write them, or run with GUBACHECK_BACKEND=live." % case_id)
            moves = scripts(arm)[case_id]
        self.moves = moves
        self.i = 0
        self.last_usage = (0, 0)

    def next_move(self, transcript):
        """`transcript` is ignored on purpose: a script does not react."""
        if self.i >= len(self.moves):
            return {"thought": "script exhausted",
                    "final": {"decision": "no_trade", "trigger": "data_missing",
                              "reason": "scripted moves ended without a conclusion"}}
        move = self.moves[self.i]
        self.i += 1
        # Token counts on the scripted backend are ESTIMATES (characters/3),
        # used only so the cost arithmetic runs. Reported costs come from live runs.
        chars = sum(len(t["content"]) for t in transcript) + 6000
        self.last_usage = (chars // 3, 150)
        return move


class LiveBackend:
    name = "live"

    def __init__(self, case_id, system_prompt):
        self.case_id = case_id
        self.system_prompt = system_prompt
        self.last_usage = (0, 0)

    def next_move(self, transcript):
        messages = [{"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": "Check spike %s." % self.case_id}]
        messages += [{"role": t["role"], "content": t["content"]} for t in transcript]
        text, usage = _live_call(messages)
        self.last_usage = (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        return _parse(text)


def _parse(text):
    """Models sometimes wrap JSON in a code fence; strip it, then insist on JSON."""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return {"thought": "unparseable reply: %s" % text[:200],
                "final": {"decision": "no_trade", "trigger": "data_missing",
                          "reason": "model did not return parseable JSON"}}


def _live_call(messages):
    """THE ONLY FUNCTION THAT KNOWS A VENDOR. Returns (text, usage)."""
    if not config.API_KEY:
        raise SystemExit("Live backend needs OPENROUTER_API_KEY in the environment.")
    body = json.dumps({"model": config.MODEL, "messages": messages,
                       "temperature": 0}).encode()
    req = urllib.request.Request(
        config.BASE_URL.rstrip("/") + "/chat/completions", data=body,
        headers={"Authorization": "Bearer " + config.API_KEY,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        payload = json.load(r)
    return payload["choices"][0]["message"]["content"], payload.get("usage", {})


def make_backend(case_id, system_prompt="", moves=None, arm="agent"):
    if moves is not None or config.BACKEND == "scripted":
        return ScriptedBackend(case_id, moves, arm if arm in ("exhaustive",) else "keyword")
    if config.BACKEND == "live":
        return LiveBackend(case_id, system_prompt)
    raise SystemExit("BACKEND must be 'scripted' or 'live', not %r" % config.BACKEND)
