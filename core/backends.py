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
    """Real model through OpenRouter using NATIVE TOOL CALLING.

    The provider returns structured tool calls (name + JSON arguments), so the
    loop never depends on the model hand-writing JSON in free text. The
    conclusion is itself a tool (`conclude`). Every raw reply is kept in
    self.trace for diagnosis. If the model answers without calling a tool,
    it is reminded (at most twice) before the run concludes H.
    """
    name = "live"

    def __init__(self, case_id, system_prompt, arm="agent"):
        from core import tools
        self.case_id = case_id
        self.messages = [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": "Investigate spike %s. Use the tools; finish by calling conclude." % case_id}]
        self.schemas = tools.tool_schemas(arm)
        self.pending_ids = []
        self.nudges = 0
        self.trace = []
        self.last_usage = (0, 0)

    def next_move(self, transcript):
        msg, usage = _live_chat(self.messages, self.schemas)
        self.last_usage = (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        self.trace.append({"content": (msg.get("content") or "")[:500],
                           "tool_calls": [(c["function"]["name"], c["function"].get("arguments", "")[:300])
                                          for c in msg.get("tool_calls") or []]})
        calls = msg.get("tool_calls") or []
        self.messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls} if calls
                             else {"role": "assistant", "content": msg.get("content") or ""})
        if not calls:
            if self.nudges < 2:
                self.nudges += 1
                self.messages.append({"role": "user", "content": "Call one of the tools now. When the stop flag is true, call conclude."})
                return {"thought": msg.get("content") or "", "calls": []}
            return {"thought": msg.get("content") or "", "final": {
                "primary": "H", "reason": "model stopped calling tools: " + (msg.get("content") or "")[:200]}}
        parsed, self.pending_ids = [], []
        for c in calls:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if c["function"]["name"] == "conclude":
                self.pending_ids = []
                return {"thought": msg.get("content") or "", "final": {
                    "primary": str(args.get("primary", "H")).strip().upper()[:1] or "H",
                    "secondary": args.get("secondary") or [], "reason": args.get("reason", "")}}
            parsed.append([c["function"]["name"], args])
            self.pending_ids.append(c["id"])
        return {"thought": msg.get("content") or "", "calls": parsed}

    def observe(self, observations):
        """Return each tool result to the model, matched to its call id."""
        for cid, o in zip(self.pending_ids, observations):
            self.messages.append({"role": "tool", "tool_call_id": cid,
                                  "content": json.dumps(o["observation"] if "observation" in o else o.get("result"),
                                                        ensure_ascii=False, default=str)[:3500]})
        self.pending_ids = []

    @staticmethod
    def token_estimate(transcript):
        return 0, 0


def _live_chat(messages, schemas, retries=4):
    """Chat completion with tools. Returns (message dict, usage). Same retry policy as _live_call."""
    import time
    import urllib.error
    if not config.API_KEY:
        raise SystemExit("Live backend needs OPENROUTER_API_KEY in the environment.")
    body = json.dumps({"model": config.MODEL, "messages": messages, "tools": schemas, "tool_choice": "auto",
                       "temperature": 0, "max_tokens": 3000}).encode()
    used = {"prompt_tokens": 0, "completion_tokens": 0}
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(config.BASE_URL.rstrip("/") + "/chat/completions", data=body,
                                         headers={"Authorization": "Bearer " + config.API_KEY,
                                                  "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                payload = json.load(r)
            u = payload.get("usage") or {}
            used["prompt_tokens"] += u.get("prompt_tokens", 0)
            used["completion_tokens"] += u.get("completion_tokens", 0)
            if payload.get("error"):
                raise RuntimeError(str(payload["error"])[:200])
            msg = (payload.get("choices") or [{}])[0].get("message") or {}
            if msg.get("tool_calls") or (msg.get("content") or "").strip():
                return msg, used
            last_err = "empty reply"
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s %s" % (e.code, e.read()[:200])
            if e.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(last_err)
        except Exception as e:
            last_err = str(e)[:200]
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("live call failed after %d attempts: %s" % (retries, last_err))


def _parse(text):
    """Models sometimes wrap JSON in a code fence or add prose; take the outermost JSON object."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                pass
    return {"thought": "unparseable reply: %s" % (text or "")[:200],
            "final": {"primary": "H", "decision": "no_trade", "trigger": "data_missing",
                      "reason": "model did not return parseable JSON"}}


def _live_call(messages, retries=4):
    """THE ONLY FUNCTION THAT KNOWS A VENDOR. Returns (text, usage).

    Retries with back-off on network errors, HTTP 429/5xx and EMPTY replies
    (some reasoning models occasionally return content=null). Usage is summed
    over attempts, so retries are paid for in the cost figures.
    """
    import time
    import urllib.error
    if not config.API_KEY:
        raise SystemExit("Live backend needs OPENROUTER_API_KEY in the environment.")
    body = json.dumps({"model": config.MODEL, "messages": messages, "temperature": 0,
                       "max_tokens": 2000}).encode()
    used = {"prompt_tokens": 0, "completion_tokens": 0}
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                config.BASE_URL.rstrip("/") + "/chat/completions", data=body,
                headers={"Authorization": "Bearer " + config.API_KEY, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                payload = json.load(r)
            u = payload.get("usage") or {}
            used["prompt_tokens"] += u.get("prompt_tokens", 0)
            used["completion_tokens"] += u.get("completion_tokens", 0)
            if payload.get("error"):
                raise RuntimeError(str(payload["error"])[:200])
            msg = (payload.get("choices") or [{}])[0].get("message") or {}
            text = msg.get("content")
            if text and text.strip():
                return text, used
            last_err = "empty reply"
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s" % e.code
            if e.code not in (408, 429, 500, 502, 503, 504):
                raise
        except Exception as e:                # timeouts, connection resets, provider errors
            last_err = str(e)[:200]
        time.sleep(3 * (attempt + 1))
    raise RuntimeError("live call failed after %d attempts: %s" % (retries, last_err))


def make_backend(case_id, system_prompt="", moves=None, arm="agent"):
    if moves is not None or config.BACKEND == "scripted":
        return ScriptedBackend(case_id, moves, arm if arm in ("exhaustive",) else "keyword")
    if config.BACKEND == "live":
        return LiveBackend(case_id, system_prompt, arm)
    raise SystemExit("BACKEND must be 'scripted' or 'live', not %r" % config.BACKEND)
