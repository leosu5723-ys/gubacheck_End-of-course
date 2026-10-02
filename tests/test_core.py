"""
GubaCheck - UNIT TESTS (standard library only)
=========================================================================
    python3 -m unittest discover tests

Runs the tools, broker, guardrails and agent loop against the synthetic
fixture in tests/fixture/ (see make_fixture.py). These tests check that
the CODE behaves as documented; they say nothing about decision quality.
=========================================================================
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tests import make_fixture  # noqa: E402
from core import config, store, tools, paper_broker, market  # noqa: E402
from core.agent import run_case  # noqa: E402
from core.harness import code_check  # noqa: E402

C = make_fixture.CODE


def setUpModule():
    make_fixture.build()
    config.DATA_DIR = make_fixture.HERE
    store.reset()


def spike_moves(spike_id, date, extra):
    first = {"thought": "fetch", "calls": [["get_spike", {"spike_id": spike_id}]]}
    return [first] + extra


class TestMarket(unittest.TestCase):
    def test_limits(self):
        self.assertEqual(market.limit_up_price(10.0, "main"), 11.0)
        self.assertEqual(market.limit_up_price(10.0, "gem"), 12.0)
        self.assertEqual(market.limit_up_price(10.0, "main", is_st=True), 10.5)

    def test_event_types(self):
        self.assertEqual(market.event_type_of("关于以集中竞价交易方式回购公司股份方案的公告")["type"], "buyback")
        self.assertEqual(market.event_type_of("关于回购注销限制性股票的公告")["type"], "other")
        self.assertEqual(market.event_type_of("股票交易异常波动公告")["type"], "clarification")
        self.assertTrue(market.event_type_of("2026年半年度业绩预告")["ambiguous"])


class TestTools(unittest.TestCase):
    def test_window_cap(self):
        self.assertIn("error", tools.search_cninfo(C, [], "2026-01-01", "2026-08-20"))

    def test_old_announcement_not_returned(self):
        r = tools.search_cninfo(C, ["重组"], "2026-08-13", "2026-08-27")
        self.assertEqual(r["results"], [])

    def test_news_trimmed_and_windowed(self):
        r = tools.search_news(["重组"], "2026-08-13", "2026-08-27")
        self.assertEqual([i["news_id"] for i in r["results"]], ["N1"])

    def test_hostile_post_flagged(self):
        self.assertEqual(tools.get_spike("SPK-%s-20260825" % C)["hostile_posts"], [2])

    def test_limit_up_rejected(self):
        self.assertEqual(paper_broker.simulate(C, "2026-09-01")["reason"], "opens_limit_up")
        self.assertTrue(tools.get_price_context(C, "2026-09-01")["opens_limit_up"])

    def test_fill(self):
        f = paper_broker.simulate(C, "2026-08-20")
        self.assertEqual(f["status"], "filled")
        self.assertEqual(f["shares"] % 100, 0)


class TestAgentAndGuards(unittest.TestCase):
    def test_happy_path_order(self):
        sid = "SPK-%s-20260820" % C
        moves = spike_moves(sid, "2026-08-20", [
            {"thought": "search", "calls": [
                ["search_cninfo", {"stock": C, "keywords": ["回购"], "date_from": "2026-08-06", "date_to": "2026-08-20"}],
                ["get_price_context", {"stock": C, "date": "2026-08-20"}]]},
            {"thought": "type", "calls": [["check_event_type", {"ann_id": "F1"}]]},
            {"thought": "order", "calls": [["place_paper_order", {"stock": C, "decision_date": "2026-08-20", "evidence_id": "F1"}]]},
            {"thought": "done", "final": {"decision": "paper_trade", "evidence_id": "F1", "reason": "F1 supports"}}])
        rec = run_case(sid, moves=moves)
        self.assertEqual(rec["decision"], "paper_trade")
        self.assertEqual(rec["turns"], 4)
        self.assertIn("gate_passed", [f["guardrail"] for f in rec["guardrails_fired"]])
        ok, _ = code_check(rec, {"expected_decision": "paper_trade", "evidence_id": "F1"})
        self.assertTrue(ok)

    def test_order_blocked_after_hostile_text(self):
        sid = "SPK-%s-20260825" % C
        moves = spike_moves(sid, "2026-08-25", [
            {"thought": "obey the post", "calls": [["place_paper_order",
             {"stock": C, "decision_date": "2026-08-25", "evidence_id": "F1"}]]}])
        rec = run_case(sid, moves=moves)
        self.assertEqual(rec["trigger"], "hostile_text")
        self.assertFalse(any(c["tool"] == "place_paper_order" for c in rec["tool_calls"]))

    def test_order_needs_evidence(self):
        sid = "SPK-%s-20260827" % C
        moves = spike_moves(sid, "2026-08-27", [
            {"thought": "trade on rumour", "calls": [["place_paper_order",
             {"stock": C, "decision_date": "2026-08-27", "evidence_id": "N1"}]]}])
        rec = run_case(sid, moves=moves)
        self.assertEqual(rec["stopped_by"], "evidence_required")

    def test_dedup_stops_loop(self):
        sid = "SPK-%s-20260827" % C
        s = ["search_cninfo", {"stock": C, "keywords": ["x"], "date_from": "2026-08-20", "date_to": "2026-08-27"}]
        moves = spike_moves(sid, "2026-08-27", [{"thought": "again", "calls": [s]} for _ in range(10)])
        rec = run_case(sid, moves=moves)
        self.assertEqual(rec["stopped_by"], "duplicate_action")
        self.assertEqual(rec["turns"], 3)

    def test_gate_held(self):
        sid = "SPK-%s-20260820" % C
        moves = spike_moves(sid, "2026-08-20", [
            {"thought": "order", "calls": [["place_paper_order",
             {"stock": C, "decision_date": "2026-08-20", "evidence_id": "F1"}]]}])
        rec = run_case(sid, moves=moves, approve=lambda a, p: False)
        self.assertEqual(rec["stopped_by"], "gate_held")


if __name__ == "__main__":
    unittest.main()
