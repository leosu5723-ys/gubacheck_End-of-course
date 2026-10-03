"""
GubaCheck - GUARDRAIL LAYER
=========================================================================
Code that a model cannot talk its way past. Six checks:

    1. STEP CAP              stop after MAX_TURNS tool-calling turns
    2. BUDGET CEILING        stop after MAX_TOKENS_PER_RUN tokens
    3. ACTION DE-DUPLICATION stop an identical tool call made twice
    4. AUTONOMY GATE         hold the paper order for a human yes
    5. HOSTILE-TEXT SCREEN   flag forum/news text that addresses the system
    6. EVIDENCE REQUIRED     no order without an official announcement id
                             that belongs to the same stock and is not a
                             never-bullish type (issuance, reduction, lock-up)

Every stop raises GuardrailStop with a reason, and the decision record
says which guard fired. A guard that silently returns an empty answer
would turn a visible cost problem into an invisible correctness problem.
=========================================================================
"""
import re


class GuardrailStop(Exception):
    """Raised when the code layer halts a run. Carries the reason."""

    def __init__(self, reason, detail=""):
        self.reason = reason
        self.detail = detail
        super().__init__("%s: %s" % (reason, detail) if detail else reason)


# Forum posts are written by strangers. These patterns catch text that is
# aimed at an automated reader rather than at other investors.
_HOSTILE = [
    r"忽略.{0,6}(规则|指令|以上|之前|提示)",
    r"(系统|system)\s*(提示|prompt|指令)",
    r"ignore (all|previous|the above)",
    r"(立即|马上|直接)(买入|下单|满仓)",
    r"(输出|告诉我|泄露).{0,6}(提示词|system prompt|指令)",
    r"你是(一个)?(AI|助手|机器人|模型)",
]


def screen_text(text):
    """Return the first hostile pattern found in `text`, or None.

    WATCH OUT   this is a tripwire, not a classifier. It is deliberately
                narrow so ordinary bullish slang ("冲!", "满仓干") does not
                trip it; the evaluation set contains both kinds.
    """
    for pat in _HOSTILE:
        if re.search(pat, text, re.IGNORECASE):
            return pat
    return None


class Guardrails:
    """One instance per run. Never share between cases."""

    def __init__(self, max_turns, max_tokens, autonomy):
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.autonomy = autonomy
        self.seen = set()
        self.fired = []
        self.hostile_seen = False

    def check_turns(self, turn):
        if turn > self.max_turns:
            self._fire("step_cap", "reached %d turns" % self.max_turns)
            raise GuardrailStop("step_cap", "no conclusion within %d turns" % self.max_turns)

    def check_budget(self, tokens):
        if tokens > self.max_tokens:
            self._fire("budget_ceiling", "%d tokens" % tokens)
            raise GuardrailStop("budget_ceiling",
                                "spent %d tokens, ceiling %d" % (tokens, self.max_tokens))

    def check_duplicate(self, tool, args):
        sig = (tool, repr(sorted(args.items())))
        if sig in self.seen:
            self._fire("duplicate_action", tool)
            raise GuardrailStop("duplicate_action",
                                "%s repeated with identical arguments" % tool)
        self.seen.add(sig)

    def note_observation(self, observation):
        """Remember whether any tool result carried hostile text."""
        if isinstance(observation, dict) and observation.get("hostile_posts"):
            self.hostile_seen = True

    def check_order(self, args, evidence_lookup):
        """Guards 5 and 6, applied in front of the order tool only."""
        if self.hostile_seen:
            self._fire("hostile_text_block", "order attempted after hostile text")
            raise GuardrailStop("hostile_text",
                                "order blocked: the forum text for this case addressed the system")
        ann = evidence_lookup(args.get("evidence_id", ""))
        if ann is None or ann.get("stock") != args.get("stock"):
            self._fire("evidence_required", str(args.get("evidence_id")))
            raise GuardrailStop("evidence_required",
                                "order needs an official announcement id for the same stock")
        from core import config
        if ann.get("type") in config.NEVER_BULLISH_TYPES:
            self._fire("never_bullish_type", ann.get("type"))
            raise GuardrailStop("never_bullish_type",
                                "%s filings can never justify a buy" % ann.get("type"))

    def gate(self, action, payload, approve):
        """Autonomy gate, in front of the order and nothing else."""
        if self.autonomy == "act":
            ok = True
        elif self.autonomy == "suggest":
            ok = False
        else:
            ok = bool(approve and approve(action, payload))
        self._fire("gate_passed" if ok else "gate_held",
                   "%s (autonomy=%s)" % (action, self.autonomy))
        return ok

    def _fire(self, kind, detail):
        self.fired.append({"guardrail": kind, "detail": detail})
