"""
GubaCheck - SCRIPTED ARMS AND THE EVALUATION SET (v4)
=========================================================================
    python3 -m pipeline.v4_scripts

Two arms need no language model, so they run on the scripted backend,
free and identical on every machine:

  keyword     a rule-based clue scorer counts cause keywords in the
              most-read posts (non-AI baseline for step 2), then the same
              loop and stop rule as the agent, never revising
  exhaustive  uniform priors, all seven tests, no stop rule

Their moves are simulated here against the real tools and written to
evals/scripted_moves_<arm>.json. The live arms (routing, agent) use a model.

Also writes evals/cases.json from my hand labels (evals/cause_labels.csv):
one case per spike with expected_primary. Spikes not yet labelled get
expected_primary = null and are excluded from accuracy.
=========================================================================
"""
import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import causes, config, investigation, store, tools  # noqa: E402

KEYWORDS = {
    "A": r"公告|董秘|回复|披露|业绩|预告|快报|回购|增持|减持|合同|中标|重组|定增|分红|澄清|声明",
    "B": r"小作文|传闻|消息|报道|媒体|据悉|网传|曝|爆料|网友",
    "C": r"板块|概念|行业|龙头|同行|集体|一起|算力|CPO|光模块|PCB|汽车|锂电|固态|电池|船舶|芯片",
    "D": r"美股|英伟达|NVDA|特斯拉|隔夜|纳指|海外|美国|博通|台积电|谷歌|苹果",
    "E": r"大盘|指数|沪指|上证|创业板指|全市场|普涨|普跌|A股|两市|万亿",
    "F": r"政策|国务院|证监会|央行|降准|降息|规划|关税|补贴|会议|部委|发改委|工信部|十五五",
    "G": r"游资|主力|龙虎榜|机构|北向|资金|量化|ETF|席位|净买|净流入|净流出|融资",
}


def keyword_scores(spike):
    titles = " ".join(p["title"] for p in spike["top_posts"])
    return {c: min(10, len(re.findall(k, titles))) for c, k in KEYWORDS.items()}


def simulate(spike_id, arm):
    inv = investigation.start(arm)
    s = tools.get_spike(spike_id)
    moves = [{"thought": "Fetch the spike.", "calls": [["get_spike", {"spike_id": spike_id}]]}]
    scores = keyword_scores(s) if arm == "keyword" else {c: 1 for c in config.CAUSES}
    moves.append({"thought": "Score causes from keyword counts in the most-read posts.",
                  "calls": [["score_causes", {"scores": scores}]]})
    inv.set_scores(scores)
    while not inv.should_stop():
        c = inv.next_suggestion()
        if c is None:
            break
        inv.apply(c, causes.CAUSE_TOOLS[c](spike_id)["verdict"])
        moves.append({"thought": "Test %s (highest untested posterior)." % c,
                      "calls": [["check_" + c, {"spike_id": spike_id}]]})
    res = inv.result()
    moves.append({"thought": "Stop condition held.", "final": {
        "primary": res["primary"], "secondary": res["secondary"],
        "reason": "tested %s; posterior %s" % ("".join(res["order"]),
                                               {k: round(v, 2) for k, v in res["posterior"].items()})}})
    return moves


def hand_labels():
    p = os.path.join(ROOT, "evals", "cause_labels.csv")
    if not os.path.exists(p):
        return {}
    out = {}
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        lab = (r.get("primary") or "").strip().upper()[:1]
        if lab in "ABCDEFGH" and lab:
            out[r["spike_id"]] = {"primary": lab, "secondary": (r.get("secondary") or "").strip().upper(),
                                  "note": (r.get("note") or "").strip()}
    return out


def main():
    spikes = [s for s in store.load("spikes") if not s.get("synthetic")]
    for arm in ("keyword", "exhaustive"):
        moves = {s["spike_id"]: simulate(s["spike_id"], arm) for s in spikes}
        json.dump(moves, open(os.path.join(ROOT, "evals", "scripted_moves_%s.json" % arm), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        from collections import Counter
        print(arm, Counter(m[-1]["final"]["primary"] for m in moves.values()),
              "mean checks %.2f" % (sum(sum(1 for x in m if x.get("calls") and x["calls"][0][0].startswith("check_"))
                                        for m in moves.values()) / len(moves)))
    labels = hand_labels()
    cases = [{"case_id": s["spike_id"], "stock": s["stock"], "date": s["date"],
              "expected_primary": labels.get(s["spike_id"], {}).get("primary"),
              "expected_secondary": labels.get(s["spike_id"], {}).get("secondary", ""),
              "period": "observe" if s["date"] < "2026-04-01" else "check"} for s in spikes]
    json.dump(cases, open(os.path.join(ROOT, "evals", "cases.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("cases", len(cases), "labelled", sum(1 for c in cases if c["expected_primary"]))


if __name__ == "__main__":
    main()
