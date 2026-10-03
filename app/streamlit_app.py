"""
GubaCheck - FRONT END (Streamlit, Chinese / English)
=========================================================================
    streamlit run app/streamlit_app.py

Reads only the frozen snapshot (data/snapshot/) and results/ - no API key,
no network. Four pages:

  1 Watchlist      forum heat (posts z) and bullish share per stock, spikes marked
  2 Attribution    one spike: clues and priors -> each cause test -> posterior after
                   each step -> why it stopped -> conclusion + timeline -> how spikes
                   of that cause behaved afterwards (D+1 ... D+20)
  3 Evaluation     sentiment, filing judge (RAG ablation), arms comparison, guardrails
  4 Paper trading  reserved: the gated order, kept for completeness

Investigations shown on page 2 are replayed from results/results_<arm>*.json,
or run live on the scripted keyword arm if no saved run exists.
=========================================================================
"""
import glob
import json
import os
import sys

import altair as alt
import pandas as pd
import streamlit as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import causes, config, store  # noqa: E402

st.set_page_config(page_title="GubaCheck", page_icon="🔎", layout="wide")

T = {
    "zh": {"lang": "语言", "pages": ["自选股面板", "异动归因报告", "评测指标", "模拟盘（预留）"],
           "title": "GubaCheck · 股吧异动归因", "sub": "股吧讨论突然暴增时，查明原因，并告诉你这类原因历史上之后怎么走",
           "stock": "股票", "posts_z": "帖子量 z", "bull": "看多比例", "spikes": "异动", "spike": "选择异动",
           "clues": "线索与先验", "steps": "调查过程", "conclusion": "结论", "history": "这类原因的历史表现",
           "posterior": "后验概率", "verdict": "结果", "stop": "停止原因", "timeline": "时间线",
           "onset": "异动开始", "arm": "调查方案", "no_hist": "样本不足", "evid": "证据",
           "cause_names": {"A": "公司官方", "B": "媒体/传闻", "C": "板块联动", "D": "海外映射", "E": "大盘",
                           "F": "政策/宏观", "G": "资金/交易结构", "H": "无法解释"},
           "gate": "确认下单（人工 gate）", "reserved": "预留功能：不是归因的核心。下单需要一份官方公告作为依据，并由你确认。",
           "n_warn": "样本数少于 5，仅供参考", "excess": "相对沪深300超额收益（扣费）", "top_posts": "阅读最多的帖子"},
    "en": {"lang": "Language", "pages": ["Watchlist", "Spike attribution", "Evaluation", "Paper trading (reserved)"],
           "title": "GubaCheck · why did the forum explode?", "sub": "When a stock's forum suddenly surges, find the cause and show how spikes with that cause behaved afterwards",
           "stock": "Stock", "posts_z": "posts z", "bull": "bullish share", "spikes": "spikes", "spike": "Pick a spike",
           "clues": "Clues and priors", "steps": "Investigation", "conclusion": "Conclusion", "history": "How spikes of this cause behaved",
           "posterior": "posterior", "verdict": "verdict", "stop": "Why it stopped", "timeline": "Timeline",
           "onset": "onset", "arm": "Arm", "no_hist": "not enough data", "evid": "Evidence",
           "cause_names": {"A": "company official", "B": "media / rumour", "C": "sector", "D": "overseas", "E": "market",
                           "F": "policy / macro", "G": "money / structure", "H": "unexplained"},
           "gate": "Confirm order (human gate)", "reserved": "Reserved: not the core of attribution. An order needs an official filing as evidence and your confirmation.",
           "n_warn": "fewer than 5 spikes: indicative only", "excess": "excess return vs CSI 300, net of fees", "top_posts": "Most-read posts"},
}

lang = st.sidebar.radio("语言 / Language", ["zh", "en"], format_func=lambda x: "中文" if x == "zh" else "English")
L = T[lang]
page = st.sidebar.radio("", L["pages"])
st.title(L["title"])
st.caption(L["sub"])

spikes = [s for s in store.load("spikes") if not s.get("synthetic")]
stocks = store.load("stocks")
daily = store.load("daily_stats")
CN = L["cause_names"]


def cause_label(c):
    return "%s · %s" % (c, CN.get(c, c))


def load_results():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "results", "results_*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if d.get("results") and d["results"][0]["record"].get("arm"):
            out[os.path.basename(f)[8:-5]] = d
    return out


# ---------------------------------------------------------------- page 1
if page == L["pages"][0]:
    rows = []
    for code, meta in stocks.items():
        d = daily.get(code, [])
        last = d[-1] if d else {}
        rows.append({L["stock"]: "%s %s" % (code, meta["name"]), L["posts_z"]: last.get("z_posts"),
                     L["bull"]: last.get("bull_share"), L["spikes"]: sum(s["stock"] == code for s in spikes)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    code = st.selectbox(L["stock"], list(stocks), format_func=lambda c: "%s %s" % (c, stocks[c]["name"]))
    df = pd.DataFrame(daily.get(code, []))
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        sp = pd.DataFrame([{"date": pd.to_datetime(s["date"]), "z_posts": s["z_posts"]} for s in spikes if s["stock"] == code])
        base = alt.Chart(df).encode(x=alt.X("date:T", title=None))
        line = base.mark_line().encode(y=alt.Y("z_posts:Q", title=L["posts_z"]))
        rule = alt.Chart(pd.DataFrame({"y": [config.Z_POSTS]})).mark_rule(strokeDash=[4, 4]).encode(y="y:Q")
        pts = alt.Chart(sp).mark_point(size=90, filled=True, color="#d62728").encode(x="date:T", y="z_posts:Q") if not sp.empty else None
        st.altair_chart((line + rule + pts) if pts is not None else (line + rule), use_container_width=True)
        st.altair_chart(base.mark_area(opacity=0.4).encode(y=alt.Y("bull_share:Q", title=L["bull"])),
                        use_container_width=True)

# ---------------------------------------------------------------- page 2
elif page == L["pages"][1]:
    res = load_results()
    arms = list(res) or ["keyword"]
    arm = st.sidebar.selectbox(L["arm"], arms, index=next((i for i, a in enumerate(arms) if a.startswith("agent")), 0))
    sid = st.selectbox(L["spike"], [s["spike_id"] for s in spikes],
                       format_func=lambda i: "%s  %s  %s" % (i[4:10], stocks[i[4:10]]["name"], i[-8:]))
    s = store.spike(sid)
    rec = None
    if arm in res:
        rec = next((r["record"] for r in res[arm]["results"] if r["case_id"] == sid), None)
    if rec is None:
        from core.agent import run_case
        rec = run_case(sid, arm="keyword")
    c1, c2, c3 = st.columns(3)
    c1.metric(L["posts_z"], s["z_posts"], "%d posts" % s["posts"])
    c2.metric(L["bull"], "%.0f%%" % (100 * s["bull_share"]), "z %s" % s["z_bull"])
    c3.metric(L["onset"], s["onset"][5:16])
    gold = {}
    gp = os.path.join(ROOT, "evals", "cause_labels.csv")
    if os.path.exists(gp):
        import csv
        gold = {r["spike_id"]: r["primary"] for r in csv.DictReader(open(gp, encoding="utf-8-sig"))}
    st.success("%s: **%s**%s" % (L["conclusion"], cause_label(rec.get("primary", "H")),
                                ("　·　%s %s" % ("人工标注" if lang == "zh" else "my label", cause_label(gold[sid])))
                                if gold.get(sid) else ""))
    posts = {p["post_id"]: p for p in store.load("posts")}
    with st.expander(L["top_posts"], expanded=False):
        for pid in s["sample_post_ids"][:12]:
            p = posts.get(pid)
            if p:
                st.write("`%s` %s" % (p["time"][5:16], p["title"]))
    inv = rec.get("investigation", {})
    hist = inv.get("history", [])
    if hist:
        st.subheader(L["steps"])
        frames = []
        for k, h in enumerate(hist):
            for c, v in h["posterior"].items():
                frames.append({"step": "%d %s" % (k, h["event"]), "cause": cause_label(c), "p": v})
        chart = alt.Chart(pd.DataFrame(frames)).mark_bar().encode(
            x=alt.X("p:Q", title=L["posterior"], stack="normalize"), y=alt.Y("step:N", sort=None, title=None),
            color=alt.Color("cause:N"), tooltip=["cause", "p"])
        st.altair_chart(chart, use_container_width=True)
        for c in inv.get("order", []):
            out = causes.CAUSE_TOOLS[c](sid)
            icon = {"PASS": "✅", "PARTIAL": "🟡", "FAIL": "❌"}[out["verdict"]]
            with st.expander("%s %s — %s" % (icon, cause_label(c), out["note"])):
                st.json({"metrics": out["metrics"], "timing": out["timing"]})
                if out["evidence"]:
                    st.dataframe(pd.DataFrame(out["evidence"]), use_container_width=True, hide_index=True)
        st.info("%s: %s" % (L["stop"], rec.get("reason", "")))
    st.subheader(L["history"])
    src = "gold" if os.path.exists(os.path.join(ROOT, "results", "cause_backtest_gold.json")) else "keyword"
    p = os.path.join(ROOT, "results", "cause_backtest_%s.json" % src)
    if os.path.exists(p):
        bt = json.load(open(p))["by_cause"].get(rec.get("primary", "H"), {}).get("all")
        if bt and bt["horizons"]:
            hdf = pd.DataFrame([{"h": k, "excess": v["mean_excess_pct"], "n": v["n"], "win": v["excess_win_rate"]}
                                for k, v in bt["horizons"].items()])
            st.altair_chart(alt.Chart(hdf).mark_bar().encode(x=alt.X("h:N", sort=None, title=None),
                                                             y=alt.Y("excess:Q", title=L["excess"] + " %"),
                                                             tooltip=["n", "win"]), use_container_width=True)
            st.caption("n = %d (%s)%s" % (bt["n"], src, " · ⚠ " + L["n_warn"] if bt["n"] < 5 else ""))
        else:
            st.write(L["no_hist"])

# ---------------------------------------------------------------- page 3
elif page == L["pages"][2]:
    def show(path, title):
        p = os.path.join(ROOT, "results", path)
        if os.path.exists(p):
            st.subheader(title)
            return json.load(open(p, encoding="utf-8"))
    d = show("sentiment_eval.json", "Forum sentiment (hand-labelled test set)")
    if d:
        st.dataframe(pd.DataFrame([{"method": k, "macro_f1": v["macro_f1"], "ci95": v.get("ci95"), "accuracy": v.get("accuracy")}
                                   for k, v in d["methods"].items()]), hide_index=True, use_container_width=True)
    d = show("judge_eval.json", "Filing judge: title rule vs LLM vs RAG (30 hand-labelled filings)")
    if d:
        st.dataframe(pd.DataFrame([{"method": k, "macro_f1": v["batch2_macro_f1"], "ci95": v["batch2_ci95"],
                                    "false_bullish": v["batch2_false_bullish"], "usd": v.get("usd_total")}
                                   for k, v in d["methods"].items()]), hide_index=True, use_container_width=True)
    res = load_results()
    if res:
        st.subheader("Attribution arms (hand-labelled spikes)")
        st.dataframe(pd.DataFrame([dict(arm=a, **{k: v for k, v in r["summary"].items()
                                                  if k in ("accuracy", "macro_f1", "always_H_baseline", "mean_cause_checks",
                                                           "mean_tokens", "total_cost_usd", "premature_stops",
                                                           "over_investigation_runs")})
                                   for a, r in res.items()]), hide_index=True, use_container_width=True)
        st.caption("always-%s baseline: accuracy %.0f%%, macro-F1 %.2f" % (
            next(iter(res.values()))["summary"].get("majority_class"),
            100 * (next(iter(res.values()))["summary"].get("majority_baseline_accuracy") or 0),
            next(iter(res.values()))["summary"].get("majority_baseline_macro_f1") or 0))
    p = os.path.join(ROOT, "results", "cause_backtest_gold.json")
    if os.path.exists(p):
        st.subheader("After the spike, by cause (my labels) — excess vs CSI 300, %")
        bt = json.load(open(p))["by_cause"]
        rows = []
        for c, g in bt.items():
            for part in ("all", "observe", "check", "bullish", "bearish"):
                if part in g and g[part]["horizons"]:
                    rows.append(dict(cause=c, group=part, n=g[part]["n"],
                                     **{k: v["mean_excess_pct"] for k, v in g[part]["horizons"].items()}))
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    d = show("guardrails.json", "Guardrail checklist")
    if d:
        st.dataframe(pd.DataFrame([{"id": r["id"], "catches": r["catches"], "passed": r["passed"]} for r in d]),
                     hide_index=True, use_container_width=True)

# ---------------------------------------------------------------- page 4
else:
    st.info(L["reserved"])
    code = st.selectbox(L["stock"], list(stocks), format_func=lambda c: "%s %s" % (c, stocks[c]["name"]))
    anns = [a for a in store.load("announcements") if a["stock"] == code and not a["procedural"]][-30:]
    jud = store.load("judgements")
    pick = st.selectbox("CNINFO", anns[::-1], format_func=lambda a: "%s %s 〔%s〕" % (a["time"][:10], a["title"][:40],
                                                                                    jud.get(a["ann_id"], {}).get("label", "-")))
    if st.button(L["gate"]) and pick:
        from core import paper_broker
        st.json(paper_broker.simulate_at(code, pick["time"]))
