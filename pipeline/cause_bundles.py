"""
GubaCheck - EVIDENCE BUNDLES FOR HAND-LABELLING THE PRIMARY CAUSE
=========================================================================
    python3 -m pipeline.cause_bundles

For every spike: the top posts, the timeline (onset), and the raw evidence
each cause tool looks at - z-scores, filings, articles, US moves, index
moves, top-list rows. The tools' PASS / PARTIAL / FAIL verdicts are NOT
shown: the gold label must be my judgement, not a copy of the tools.

Writes evals/cause_review.md (to read) and evals/cause_labels.csv (to fill:
primary cause A-H, optional secondary, optional note).
=========================================================================
"""
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import causes, store  # noqa: E402

NAMES = {"A": "公司官方", "B": "媒体/传闻", "C": "板块联动", "D": "海外映射", "E": "大盘",
         "F": "政策/宏观", "G": "资金/交易结构", "H": "无法解释"}


def main():
    spikes = store.load("spikes")
    posts = {p["post_id"]: p for p in store.load("posts")}
    md = ["# 异动原因标注表 / Cause review sheet\n",
          "每个异动：读帖子和证据，在 `evals/cause_labels.csv` 填主要原因（A–H 选一个），可选填次要原因。\n",
          "A 公司官方 · B 媒体/传闻 · C 板块联动 · D 海外映射 · E 大盘 · F 政策/宏观 · G 资金/交易结构 · H 无法解释\n",
          "证据只列客观数据，不给结论。z 值是相对该序列自身过去 120 个交易日。\n"]
    rows = []
    for s in spikes:
        meta = store.stock(s["stock"]) or {}
        out = {c: f(s["spike_id"]) for c, f in causes.CAUSE_TOOLS.items()}
        md.append("\n---\n## %s　%s　%s\n" % (s["spike_id"], meta.get("name", ""), s["date"]))
        md.append("帖子 %d（z=%.1f），看多比例 %.0f%%（z=%s），**异动开始 %s**\n"
                  % (s["posts"], s["z_posts"], 100 * s["bull_share"], s["z_bull"], s["onset"]))
        md.append("\n**阅读最多的帖子**\n")
        for pid in s["sample_post_ids"][:12]:
            p = posts.get(pid)
            if p:
                md.append("- %s %s%s" % (p["time"][5:16], p["title"][:70], "  〔资讯〕" if p.get("post_type") == 20 else ""))
        c, d, e = out["C"]["metrics"], out["D"]["metrics"], out["E"]
        md.append("\n**价格**：当日涨跌 %s%%（z=%s），开盘跳空 %s%%（z=%s）"
                  % (c["own_return_pct"], c["own_return_z"], d.get("opening_gap_pct"), d.get("opening_gap_z")))
        md.append("\n**同板块**：" + "，".join("%s %s%%(z=%s)" % (r["id"], r["ret_pct"], r["z"]) for r in out["C"]["evidence"][:6]))
        md.append("\n**美股同行（A股开盘前最后一个美股交易日）**：" +
                  ("，".join("%s %s %s%%(z=%s)" % (r["id"], r["us_date"], r["ret_pct"], r["z"]) for r in out["D"]["evidence"][:5]) or "无"))
        md.append("\n**大盘**：" + "，".join("%s %s%%(z=%s)" % (r["id"], r["ret_pct"], r["z"]) for r in e["evidence"]))
        md.append("\n**龙虎榜**：" + ("，".join("%s 净买入 %.0f 万" % (r["title"], r["net_buy"] / 1e4) for r in out["G"]["evidence"]) or "未上榜"))
        md.append("\n\n**公告 / 董秘回复（D-3 至 D，标出是否早于异动开始）**")
        md += ["- %s %s　%s　〔RAG判断：%s〕" % ("早于" if x["time"] < s["onset"] else "晚于", x["time"][:16], x["title"][:50], x["label"])
               for x in out["A"]["evidence"]] or ["- 无"]
        md.append("\n**公司相关资讯（异动前 72 小时内）**")
        md += ["- %s %s" % (x["time"][5:16], x["title"][:60]) for x in out["B"]["evidence"]] or ["- 无"]
        md.append("\n**政策类资讯（异动前）**")
        md += ["- %s %s" % (x["time"][5:16], x["title"][:60]) for x in out["F"]["evidence"]] or ["- 无"]
        rows.append([s["spike_id"], s["stock"], meta.get("name", ""), s["date"], "", "", ""])
    open(os.path.join(ROOT, "evals", "cause_review.md"), "w", encoding="utf-8").write("\n".join(md))
    with open(os.path.join(ROOT, "evals", "cause_labels.csv"), "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["spike_id", "stock", "name", "date", "primary", "secondary", "note"])
        w.writerows(rows)
    print("bundles for %d spikes -> evals/cause_review.md, evals/cause_labels.csv" % len(rows))


if __name__ == "__main__":
    main()
