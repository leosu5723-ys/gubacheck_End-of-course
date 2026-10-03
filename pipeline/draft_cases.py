"""
GubaCheck - EVIDENCE BUNDLES FOR WRITING THE ANSWER KEY
=========================================================================
    python3 -m pipeline.draft_cases

For every spike in data/snapshot/spikes.json, collects what a careful
human needs to apply RULES.md by hand, using the SAME tool functions the
agent uses (so the key and the agent see identical evidence):

    sample posts (+ hostile-text flags)        tools.get_spike
    CNINFO announcements, 14 days to the spike  tools.search_cninfo (all titles)
    news in the same window                     tools.search_news
    next-day tradability, 5-day run-up          tools.get_price_context

and a MECHANICAL first-pass decision that only uses announcement titles
and prices. It cannot tell whether an announcement is what the posts are
talking about; that judgement is made by a person when the key is
written. Output: evals/case_review.md (to read) and
evals/case_drafts.json (to edit into evals/cases.json).
=========================================================================
"""
import json
import os
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import config, store, tools  # noqa: E402


def _shift(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def bundle(spike):
    sid, code, day = spike["spike_id"], spike["stock"], spike["date"]
    s = tools.get_spike(sid)
    frm = _shift(day, -14)
    anns = tools.search_cninfo(code, [], frm, day)["results"]
    names = [s["name"]] + s["aliases"]
    news = tools.search_news(names, frm, day, stock=code)["results"]
    px = tools.get_price_context(code, day)
    allowed = [a for a in anns if a["event_type"] in config.ALLOWED_EVENT_TYPES]
    if s["hostile_posts"]:
        draft = ("flag_do_not_chase", "hostile_text", None)
    elif px is None or px["next_day"] is None:
        draft = ("flag_do_not_chase", "data_missing", None)
    elif any(a["is_clarification"] for a in anns):
        draft = ("flag_do_not_chase", "officially_denied",
                 next(a["ann_id"] for a in anns if a["is_clarification"]))
    elif allowed:
        ev = allowed[0]["ann_id"]
        if px["suspended"] or px["opens_limit_up"]:
            draft = ("flag_do_not_chase", "untradeable", ev)
        elif px["pre5_return_pct"] is not None and px["pre5_return_pct"] > config.PRICED_IN_PCT:
            draft = ("flag_do_not_chase", "priced_in", ev)
        else:
            draft = ("paper_trade", None, ev)
    elif news:
        draft = ("await_confirmation", None, None)
    else:
        draft = ("flag_do_not_chase", "no_evidence", None)
    return {"spike": s, "announcements": anns, "news": news, "price": px,
            "mechanical_draft": {"decision": draft[0], "trigger": draft[1], "evidence_id": draft[2]},
            "news_archive_covers_window": day >= "2026-08-06"}


def main():
    out, md = [], ["# Case review sheet\n",
                   "One section per spike. The mechanical draft uses titles and prices only; "
                   "decide whether any announcement is what the posts are about, then write the "
                   "expected decision into evals/cases.json.\n"]
    for sp in store.load("spikes"):
        b = bundle(sp)
        out.append(b)
        s, px, d = b["spike"], b["price"] or {}, b["mechanical_draft"]
        md.append("\n## %s  %s  %s\n" % (s["spike_id"], s["name"], s["date"]))
        md.append("posts %d (x%.1f), bullish %.0f%% (base %.0f%%), popularity rank %s\n"
                  % (s["posts"], s["heat_ratio"], 100 * s["bull_share"], 100 * s["baseline_bull_share"],
                     s["popularity_rank"]))
        md.append("\n**Top posts**\n")
        md += ["- %s%s" % (p["title"], "  ⚠ hostile" if p["post_id"] in s["hostile_posts"] else "")
               for p in s["sample_posts"]]
        md.append("\n**CNINFO, 14 days to spike**\n")
        md += ["- `%s` %s %s [%s]" % (a["ann_id"], a["date"], a["title"], a["event_type"])
               for a in b["announcements"]] or ["- (none)"]
        md.append("\n**News** %s\n" % ("" if b["news_archive_covers_window"] else "(no archive before 2026-08-06)"))
        md += ["- `%s` %s %s" % (n["news_id"], n["time"][:16], n["title"]) for n in b["news"]] or ["- (none)"]
        md.append("\n**Price** spike day %s%%, 5-day run-up %s%%, next day %s open %s, limit-up open %s\n"
                  % (px.get("spike_day_pct"), px.get("pre5_return_pct"), px.get("next_day"),
                     px.get("next_open"), px.get("opens_limit_up")))
        md.append("**Mechanical draft:** %s %s %s\n" % (d["decision"], d["trigger"] or "", d["evidence_id"] or ""))
    with open(os.path.join(ROOT, "evals", "case_drafts.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(ROOT, "evals", "case_review.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    from collections import Counter
    print(Counter((b["mechanical_draft"]["decision"], b["mechanical_draft"]["trigger"]) for b in out))


if __name__ == "__main__":
    main()
