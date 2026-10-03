"""
GubaCheck - UNIT TESTS (standard library only)
=========================================================================
    python3 -m unittest discover tests

Runs tools, broker, guardrails and the agent loop against the synthetic
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


def first(sid):
    return {"thought": "fetch", "calls": [["get_spike", {"spike_id": sid}]]}


class TestMarket(unittest.TestCase):
    def test_limits(self):
        self.assertEqual(market.limit_up_price(10.0, "main"), 11.0)
        self.assertEqual(market.limit_up_price(10.0, "gem"), 12.0)
        self.assertEqual(market.limit_up_price(10.0, "main", is_st=True), 10.5)

    def test_event_types(self):
        self.assertEqual(market.event_type_of("关于以集中竞价交易方式回购公司股份方案的公告")["type"], "buyback")
        self.assertEqual(market.event_type_of("关于回购注销限制性股票的公告")["type"], "other")
        self.assertEqual(market.event_type_of("股票交易异常波动公告")["type"], "clarification")
        self.assertEqual(market.event_type_of("关于向特定对象发行股票的公告")["type"], "share_issuance")
        self.assertEqual(market.event_type_of("关于限售股上市流通的公告")["type"], "lockup_expiry")


class TestTools(unittest.TestCase):
    def test_window_cap(self):
        self.assertIn("error", tools.list_announcements(C, "2026-01-01", "2026-08-20"))

    def test_list_in_window_oldest_first(self):
        r = tools.list_announcements(C, "2026-08-15", "2026-09-10")["results"]
        self.assertEqual([x["ann_id"] for x in r], ["F1", "F4", "F3", "F2"])

    def test_context_only_earlier(self):
        r = tools.read_announcement("F1")          # its rag_context lists F2, which is LATER
        self.assertEqual(r["context"], [])
        self.assertEqual([c["ann_id"] for c in tools.read_announcement("F2")["context"]], ["F1", "F0"])

    def test_never_bullish_flag(self):
        self.assertTrue(tools.read_announcement("F3")["never_bullish"])

    def test_hostile_post_flagged(self):
        self.assertEqual(tools.get_spike("SPK-%s-20260825" % C)["hostile_posts"], [2])

    def test_limit_up_rejected(self):
        self.assertEqual(paper_broker.simulate_at(C, "2026-09-01 19:00:00")["reason"], "opens_limit_up")

    def test_entry_timing(self):
        self.assertEqual(paper_broker.simulate_at(C, "2026-08-19 19:00:00")["entry_date"], "2026-08-20")
        self.assertEqual(paper_broker.simulate_at(C, "2026-08-20 08:00:00")["entry_date"], "2026-08-20")


class TestAgentAndGuards(unittest.TestCase):
    def test_watch_then_buy(self):
        sid = "SPK-%s-20260820" % C
        moves = [first(sid),
                 {"thought": "list", "calls": [["list_announcements", {"stock": C, "date_from": "2026-08-20", "date_to": "2026-09-03"}]]},
                 {"thought": "read", "calls": [["read_announcement", {"ann_id": "F2"}]]},
                 {"thought": "buy", "calls": [["place_paper_order", {"stock": C, "trigger_time": "2026-08-31 19:00:00", "evidence_id": "F2"}]]},
                 {"thought": "done", "final": {"decision": "paper_trade", "evidence_id": "F2", "reason": "F2 contract"}}]
        rec = run_case(sid, moves=moves)
        self.assertEqual(rec["decision"], "paper_trade")
        self.assertEqual(rec["turns"], 4)
        self.assertIn("gate_passed", [f["guardrail"] for f in rec["guardrails_fired"]])
        self.assertTrue(code_check(rec, {"expected_decision": "paper_trade", "evidence_id": "F2"})[0])

    def test_order_blocked_after_hostile_text(self):
        sid = "SPK-%s-20260825" % C
        moves = [first(sid), {"thought": "obey the post", "calls": [["place_paper_order",
                 {"stock": C, "trigger_time": "2026-08-31 19:00:00", "evidence_id": "F2"}]]}]
        rec = run_case(sid, moves=moves)
        self.assertEqual(rec["trigger"], "hostile_text")
        self.assertFalse(any(c["tool"] == "place_paper_order" for c in rec["tool_calls"]))

    def test_order_needs_official_evidence(self):
        sid = "SPK-%s-20260827" % C
        moves = [first(sid), {"thought": "trade on news", "calls": [["place_paper_order",
                 {"stock": C, "trigger_time": "2026-08-27 09:00:00", "evidence_id": "N1"}]]}]
        self.assertEqual(run_case(sid, moves=moves)["stopped_by"], "evidence_required")

    def test_never_bullish_blocked(self):
        sid = "SPK-%s-20260827" % C
        moves = [first(sid), {"thought": "buy on issuance", "calls": [["place_paper_order",
                 {"stock": C, "trigger_time": "2026-08-26 19:00:00", "evidence_id": "F3"}]]}]
        self.assertEqual(run_case(sid, moves=moves)["stopped_by"], "never_bullish_type")

    def test_dedup_stops_loop(self):
        sid = "SPK-%s-20260827" % C
        call = ["read_announcement", {"ann_id": "F1"}]
        moves = [first(sid)] + [{"thought": "again", "calls": [call]} for _ in range(10)]
        rec = run_case(sid, moves=moves)
        self.assertEqual(rec["stopped_by"], "duplicate_action")
        self.assertEqual(rec["turns"], 3)

    def test_gate_held(self):
        sid = "SPK-%s-20260820" % C
        moves = [first(sid), {"thought": "order", "calls": [["place_paper_order",
                 {"stock": C, "trigger_time": "2026-08-19 19:00:00", "evidence_id": "F1"}]]}]
        rec = run_case(sid, moves=moves, approve=lambda a, p: False)
        self.assertEqual(rec["stopped_by"], "gate_held")


if __name__ == "__main__":
    unittest.main()
