"""
GubaCheck - SYNTHETIC RED-TEAM SPIKES (guardrail checklist only)
=========================================================================
    python3 -m pipeline.redteam

Copies a real spike (stock, date, statistics) and replaces its most-read
posts with hostile text from evals/redteam_posts.json. Marked
synthetic=true: never part of cases.json, the arms or the backtests.
=========================================================================
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, "data", "snapshot")


def main():
    rt = json.load(open(os.path.join(ROOT, "evals", "redteam_posts.json"), encoding="utf-8"))
    spikes = [s for s in json.load(open(os.path.join(SNAP, "spikes.json"), encoding="utf-8")) if not s.get("synthetic")]
    posts = [p for p in json.load(open(os.path.join(SNAP, "posts.json"), encoding="utf-8")) if not str(p["post_id"]).startswith("RT-")]
    real = {s["spike_id"]: s for s in spikes}
    for k, item in enumerate(rt["spikes"]):
        base = dict(real[item["copies"]])
        ids = ["RT-%d-%d" % (k, j) for j in range(len(item["posts"]))]
        base.update(spike_id=item["spike_id"], sample_post_ids=ids, synthetic=True)
        spikes.append(base)
        posts += [{"post_id": i, "stock": base["stock"], "time": base["date"] + " 10:00:00", "title": t,
                   "post_type": 0, "sentiment": "bull"} for i, t in zip(ids, item["posts"])]
    json.dump(spikes, open(os.path.join(SNAP, "spikes.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(posts, open(os.path.join(SNAP, "posts.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("red-team spikes:", [s["spike_id"] for s in spikes if s.get("synthetic")])


if __name__ == "__main__":
    main()
