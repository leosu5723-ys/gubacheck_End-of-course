"""
GubaCheck - UNIT TESTS (v4)
=========================================================================
    python3 -m unittest discover tests

Run against the committed snapshot in data/snapshot/ (deterministic, no
network). They check that the CODE behaves as documented: the posterior
arithmetic, the stop rule, the cause tools' contracts, the guards. They
say nothing about attribution quality (that is evals/).
=========================================================================
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import causes, config, investigation, market, store  # noqa: E402
from core.agent import run_case  # noqa: E402

SPIKE = "SPK-688256-20260203"


def start(sid=SPIKE):
    return {"thought": "fetch", "calls": [["get_spike", {"spike_id": sid}]]}


class TestPosterior(unittest.TestCase):
    def test_worked_example(self):
        inv = investigation.start("agent")
        inv.set_scores({"A": 8, "C": 7, "D": 6, "E": 2, "B": 1, "G": 1, "F": 0})
        self.assertAlmostEqual(inv.posterior()["A"], 0.32, places=3)
        inv.apply("A", "PASS")
        self.assertFalse(inv.should_stop())
        inv.apply("C", "FAIL")
        inv.apply("D", "FAIL")
        self.assertTrue(inv.should_stop())
        self.assertEqual(inv.result()["primary"], "A")

    def test_uniform_when_no_clue(self):
        inv = investigation.start("agent")
        inv.set_scores({})
        self.assertAlmostEqual(inv.posterior()["G"], 1 / 7, places=3)

    def test_cap_and_H(self):
        inv = investigation.start("agent")
        inv.set_scores({c: 5 for c in config.CAUSES})
        for c in "ABCDE":
            inv.apply(c, "FAIL")
        self.assertTrue(inv.should_stop())
        self.assertEqual(inv.result()["primary"], "H")

    def test_routing_cannot_revise(self):
        inv = investigation.start("routing")
        inv.set_scores({"A": 5})
        self.assertIn("error", inv.revise({"B": 9}, "x"))

    def test_revise_keeps_tested_weight(self):
        inv = investigation.start("agent")
        inv.set_scores({"A": 5, "B": 5})
        inv.apply("A", "PASS")
        before = inv.weights["A"]
        inv.revise({"C": 10}, "peers moved")
        self.assertEqual(inv.weights["A"], before)
        self.assertGreater(inv.posterior()["C"], 0)


class TestCauseTools(unittest.TestCase):
    def test_contract(self):
        for c, f in causes.CAUSE_TOOLS.items():
            out = f(SPIKE)
            self.assertEqual(out["cause"], c)
            self.assertIn(out["verdict"], ("PASS", "PARTIAL", "FAIL"))
            for k in ("metrics", "evidence", "timing", "cost", "note"):
                self.assertIn(k, out)

    def test_us_peer_is_before_open(self):
        for r in causes.check_D(SPIKE)["evidence"]:
            self.assertLess(r["us_date"], store.spike(SPIKE)["date"])

    def test_limits(self):
        self.assertEqual(market.limit_up_price(10.0, "main"), 11.0)
        self.assertEqual(market.limit_up_price(10.0, "star"), 12.0)


class TestAgentLoop(unittest.TestCase):
    def test_keyword_arm_runs(self):
        rec = run_case(SPIKE, arm="keyword")
        self.assertIn(rec["primary"], list("ABCDEFGH"))
        self.assertLessEqual(rec["investigation"]["calls"], config.MAX_CAUSE_CALLS)

    def test_stop_rule_refuses_extra_checks(self):
        moves = [start(), {"thought": "score", "calls": [["score_causes", {"scores": {"C": 10}}]]}]
        moves += [{"thought": "check", "calls": [["check_" + c, {"spike_id": SPIKE}]]} for c in "CBAGDEF"]
        rec = run_case(SPIKE, moves=moves, arm="agent")
        self.assertEqual(rec["investigation"]["calls"], config.MAX_CAUSE_CALLS)
        self.assertEqual(rec["investigation"]["over_investigation"], 1)

    def test_dedup(self):
        moves = [start(), {"thought": "score", "calls": [["score_causes", {"scores": {"C": 10}}]]},
                 {"thought": "c", "calls": [["get_spike", {"spike_id": SPIKE}]]}]
        self.assertEqual(run_case(SPIKE, moves=moves)["stopped_by"], "duplicate_action")

    def test_order_needs_official_filing(self):
        moves = [start(), {"thought": "buy", "calls": [["place_paper_order",
                 {"stock": "688256", "trigger_time": "2026-02-03 20:00:00", "evidence_id": "NOT-A-FILING"}]]}]
        self.assertEqual(run_case(SPIKE, moves=moves)["stopped_by"], "evidence_required")


if __name__ == "__main__":
    unittest.main()
