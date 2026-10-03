"""
GubaCheck - SNAPSHOT AND CASES FOR THE AGENT (forward-watch design)
=========================================================================
    python3 -m pipeline.agent_snapshot

Writes what the agent's tools read, and the evaluation set:

  data/snapshot/announcements.json   every filing: id, stock, exact time, type, procedural
  data/snapshot/ann_texts.json       cleaned text of every filing in a watch window and
                                     of the filings retrieved as their context
  data/snapshot/rag_context.json     per window filing, the ids the RAG step retrieved
  data/snapshot/spikes.json          + watch_until (close of trading day D+10)
  evals/cases.json                   expected outcome per spike
  evals/scripted_moves.json          the moves a correct agent makes, per spike

THE ANSWER KEY. The expected outcome of a spike is RULES.md section 2
applied to filing labels: the first bullish non-procedural filing in the
watch window -> paper_trade with that filing as evidence (or no_trade /
untradeable if the entry day cannot be bought); none -> no_trade /
no_bullish_filing. The filing labels are the RAG judge's, REPLACED BY MY
HAND LABEL wherever I labelled that filing. So this key tests whether the
agent follows the procedure and reads the right filings; how good the
labels themselves are is measured separately (results/judge_eval.json).

The scripted moves are the same procedure written as tool calls, one
filing read per turn, so the scripted run is the deterministic "workflow"
baseline the live agent is compared with.
=========================================================================
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config, market  # noqa: E402
from pipeline import backtest, judge, rag  # noqa: E402

SNAP = os.path.join(ROOT, "data", "snapshot")


def hand_labels():
    out = {}
    for name in ("ann_labelled.csv", "ann_labelled_batch2.csv"):
        p = os.path.join(ROOT, "data", "labels", name)
        if os.path.exists(p):
            out.update({r["ann_id"]: r["label"].strip().lower() for r in csv.DictReader(open(p, encoding="utf-8-sig"))})
    return out


def main():
    rows = judge.load_announcements()
    by_id = {r["ann_id"]: r for r in rows}
    recs = {json.loads(l)["ann_id"]: json.loads(l)
            for l in open(os.path.join(ROOT, "data", "raw", "judgements_rag.jsonl"), encoding="utf-8")}
    hand = hand_labels()
    label = {i: (hand.get(i) or (recs[i]["label"] if i in recs else "neutral")) for i in by_id}
    for i, r in by_id.items():
        if r["procedural"]:
            label[i] = "neutral"

    bars, idx, calendar = backtest.load_prices()
    meta = json.load(open(os.path.join(SNAP, "stocks.json"), encoding="utf-8"))
    spikes = json.load(open(os.path.join(SNAP, "spikes.json"), encoding="utf-8"))

    texts, ctx, cases, moves, reads = {}, {}, [], {}, []
    for s in spikes:
        code, d = s["stock"], s["date"]
        start = next(i for i, c in enumerate(calendar) if c >= d)
        until = calendar[min(start + config.WATCH_TRADING_DAYS, len(calendar) - 1)]
        s["watch_until"] = until
        window = sorted([r for r in rows if r["stock"] == code and d <= r["time"][:10] <= until
                         and r["time"] <= until + " 15:00:00"], key=lambda r: r["time"])
        to_read = [r for r in window if not r["procedural"]]
        m = [{"thought": "Fetch the spike.", "calls": [["get_spike", {"spike_id": s["spike_id"]}]]},
             {"thought": "List the company's filings in the watch window.",
              "calls": [["list_announcements", {"stock": code, "date_from": d, "date_to": until}]]}]
        decision, trigger, evidence, n_read = "no_trade", "no_bullish_filing", None, 0
        verdicts = {}
        for r in to_read:
            n_read += 1
            m.append({"thought": "Read %s (%s)." % (r["ann_id"], r["title"][:30]),
                      "calls": [["read_announcement", {"ann_id": r["ann_id"]}]]})
            verdicts[r["ann_id"]] = label[r["ann_id"]]
            texts[r["ann_id"]] = rag.clean(judge.text_of(r["ann_id"], 6000))[:1500]
            ids = recs.get(r["ann_id"], {}).get("context_ids", [])
            ctx[r["ann_id"]] = ids
            for cid in ids:
                texts.setdefault(cid, rag.clean(judge.text_of(cid, 3000))[:800])
            if label[r["ann_id"]] == "bullish":
                t = backtest.trade(code, r["time"], bars, idx, calendar, meta.get(code, {}))
                m.append({"thought": "Bullish: place the paper order (goes through the gate).",
                          "calls": [["place_paper_order", {"stock": code, "trigger_time": r["time"],
                                                           "evidence_id": r["ann_id"]}]]})
                if t["status"] == "filled":
                    decision, trigger, evidence = "paper_trade", None, r["ann_id"]
                else:
                    decision, trigger, evidence = "no_trade", "untradeable", r["ann_id"]
                break
        reason = ("First bullish filing %s: %s" % (evidence, by_id[evidence]["title"]) if evidence
                  else "No bullish filing among %d read in %s..%s" % (n_read, d, until))
        m.append({"thought": "Conclude.", "final": {"decision": decision, "trigger": trigger,
                                                     "evidence_id": evidence, "judgements": verdicts,
                                                     "reason": reason}})
        moves[s["spike_id"]] = m
        reads.append(n_read)
        must = ["names the filing that decided it, or says none was bullish",
                "quotes a fact or number from the deciding filing"]
        cases.append({"case_id": s["spike_id"], "expected_decision": decision, "trigger": trigger,
                      "evidence_id": evidence, "family": "buy" if decision == "paper_trade" else (trigger or ""),
                      "negative": decision != "paper_trade", "filings_in_window": len(window),
                      "filings_to_read": len(to_read),
                      "labels_from_hand": sum(1 for r in to_read[:n_read] if r["ann_id"] in hand),
                      "must_record": must})

    # Synthetic red-team spikes (guardrail checklist only, never in cases.json)
    rt = json.load(open(os.path.join(ROOT, "evals", "redteam_posts.json"), encoding="utf-8"))
    posts = json.load(open(os.path.join(SNAP, "posts.json"), encoding="utf-8"))
    posts = [p for p in posts if not str(p["post_id"]).startswith("RT-")]
    spikes = [s for s in spikes if not s["spike_id"].startswith("RT-")]
    real = {s["spike_id"]: s for s in spikes}
    for k, item in enumerate(rt["spikes"]):
        base = dict(real[item["copies"]])
        ids = ["RT-%d-%d" % (k, j) for j in range(len(item["posts"]))]
        base.update(spike_id=item["spike_id"], sample_post_ids=ids, synthetic=True)
        spikes.append(base)
        posts += [{"post_id": i, "stock": base["stock"], "time": base["date"] + " 10:00:00",
                   "title": t, "sentiment": "bull"} for i, t in zip(ids, item["posts"])]
    json.dump(posts, open(os.path.join(SNAP, "posts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    announcements = [{"ann_id": r["ann_id"], "stock": r["stock"], "name": r["name"], "title": r["title"],
                      "time": r["time"], "type": r["type"], "procedural": r["procedural"]} for r in rows]
    for name, obj in (("announcements", announcements), ("ann_texts", texts), ("rag_context", ctx), ("spikes", spikes)):
        json.dump(obj, open(os.path.join(SNAP, name + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(cases, open(os.path.join(ROOT, "evals", "cases.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(moves, open(os.path.join(ROOT, "evals", "scripted_moves.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from collections import Counter
    turns = sorted(r + 2 + (1 if c["evidence_id"] else 0) for r, c in zip(reads, cases))
    print("cases", Counter((c["expected_decision"], c["trigger"]) for c in cases))
    print("filings read per case: median %s max %s | tool turns per case: median %s, max %s"
          % (sorted(reads)[len(reads) // 2], max(reads), turns[len(turns) // 2], turns[-1]))
    print("labels from my hand labels used in the key:", sum(c["labels_from_hand"] for c in cases))


if __name__ == "__main__":
    main()
