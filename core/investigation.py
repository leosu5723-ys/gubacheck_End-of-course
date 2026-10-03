"""
GubaCheck - THE INVESTIGATION STATE (priors, posterior, stopping rule)
=========================================================================
One Investigation per run. It holds the arithmetic the model must never do
itself (RULES.md section 0.3):

  scores -> priors     prior_i = max(score_i, 0.5) / sum   (all zero -> uniform)
  test result          weight_i *= {PASS: 3, PARTIAL: 1, FAIL: 0.2}; renormalise
  revision             the model may re-score UNTESTED causes; tested ones keep
                       their evidence-based weight
  STOP                 (>= 1 PASS  and  untested posterior < 20%)
                       or  MAX_CAUSE_CALLS cause tests made
  result               primary = PASSED cause with the highest posterior;
                       none passed -> "H" (never scored, never tested)

Arms (RULES.md 0.4) change what is allowed, not the arithmetic:
  agent       scores, tests, may revise; stop rule enforced
  routing     scores once, may not revise; stop rule enforced
  exhaustive  uniform prior, tests all seven, no stop rule
=========================================================================
"""
import threading

from core import config

_LOCAL = threading.local()


class Investigation:
    def __init__(self, arm="agent"):
        self.arm = arm
        self.weights = None          # cause -> weight (unnormalised)
        self.tested = {}             # cause -> verdict
        self.order = []              # causes in the order tested
        self.revisions = []          # [{scores, reason}]
        self.over_investigation = 0  # cause calls attempted after STOP held
        self.history = []            # posterior snapshots after each step

    # ---- scoring -------------------------------------------------------
    def set_scores(self, scores):
        raw = {c: max(0.0, min(10.0, float(scores.get(c, 0) or 0))) for c in config.CAUSES}
        if self.arm == "exhaustive" or sum(raw.values()) == 0:
            raw = {c: 1.0 for c in config.CAUSES}
        raw = {c: max(config.SCORE_FLOOR, v) for c, v in raw.items()}   # a zero prior could never recover
        total = sum(raw.values())
        self.weights = {c: raw[c] / total for c in config.CAUSES}
        self._snap("scores")

    def revise(self, scores, reason):
        if self.arm != "agent":
            return {"error": "revision is not allowed in the %s arm" % self.arm}
        untested = [c for c in config.CAUSES if c not in self.tested]
        mass = sum(self.weights[c] for c in untested)
        raw = {c: max(config.SCORE_FLOOR, min(10.0, float(scores.get(c, 0) or 0))) for c in untested}
        if sum(raw.values()) > 0 and mass > 0:
            # redistribute the untested mass according to the new scores
            for c in untested:
                self.weights[c] = mass * raw[c] / sum(raw.values())
        self.revisions.append({"scores": raw, "reason": reason[:300]})
        self._snap("revise")
        return self.status()

    # ---- evidence ------------------------------------------------------
    def apply(self, cause, verdict):
        self.tested[cause] = verdict
        self.order.append(cause)
        self.weights[cause] *= config.WEIGHT[verdict]
        self._snap("test %s %s" % (cause, verdict))

    def posterior(self):
        total = sum(self.weights.values())
        return {c: round(w / total, 4) for c, w in self.weights.items()} if total else {}

    def untested_mass(self):
        p = self.posterior()
        return round(sum(v for c, v in p.items() if c not in self.tested), 4)

    def calls(self):
        return len(self.order)

    def should_stop(self):
        if self.arm == "exhaustive":
            return len(self.tested) == len(config.CAUSES)
        passed = any(v == "PASS" for v in self.tested.values())
        return (passed and self.untested_mass() < config.STOP_UNTESTED_MASS) or \
            self.calls() >= config.MAX_CAUSE_CALLS

    def next_suggestion(self):
        p = self.posterior()
        cand = [c for c in config.CAUSES if c not in self.tested]
        if not cand:
            return None
        return max(cand, key=lambda c: (p[c], c in config.CHEAP_CAUSES))

    def result(self):
        p = self.posterior()
        passed = sorted([c for c, v in self.tested.items() if v == "PASS"], key=lambda c: -p[c])
        return {"primary": passed[0] if passed else "H", "secondary": passed[1:],
                "posterior": p, "tested": dict(self.tested), "order": list(self.order),
                "calls": self.calls(), "revisions": len(self.revisions),
                "over_investigation": self.over_investigation}

    def status(self):
        return {"posterior": self.posterior(), "tested": dict(self.tested),
                "untested_mass": self.untested_mass(), "stop": self.should_stop(),
                "next_suggested": None if self.should_stop() else self.next_suggestion(),
                "cause_calls": self.calls()}

    def _snap(self, event):
        self.history.append({"event": event, "posterior": self.posterior(),
                             "untested_mass": self.untested_mass() if self.weights else None})


def start(arm="agent"):
    _LOCAL.inv = Investigation(arm)
    return _LOCAL.inv


def current():
    return getattr(_LOCAL, "inv", None)
