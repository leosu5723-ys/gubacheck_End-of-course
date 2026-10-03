"""
GubaCheck - FRONT END (Streamlit, 中文 / English)
=========================================================================
    streamlit run app/streamlit_app.py

A user-facing product, not a data viewer. The user's path:

  雷达 Radar        cards for every watched stock: price move, forum heat
                    gauge, sentiment bar, spike badge -> open a stock
  个股 Stock        candlestick + forum heat, spikes marked -> pick a spike
                    -> "let the AI investigate"
  调查 Investigate  the agent works step by step on screen: reads the posts,
                    extracts clues, scores causes, tests them one by one,
                    watches the probabilities move, stops, concludes; then
                    the timeline and how this kind of spike behaved
                    afterwards. The user can (a) choose the mode, (b) run
                    the tests themselves ("investigate it yourself"),
                    (c) agree / disagree with the conclusion (saved), and
                    (d) send a paper order through a confirmation dialog.
  模拟 Paper        the paper positions confirmed at the gate
  表现 Performance  how well the system does (for evaluators)

Everything reads the frozen snapshot and results/: no key needed. With
OPENROUTER_API_KEY set, "live AI" runs the real agent; otherwise saved
agent runs are replayed.
=========================================================================
"""
import csv
import glob
import json
import os
import re
import sys
import time
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import causes, config, investigation, paper_broker, store  # noqa: E402

st.set_page_config(page_title="GubaCheck", page_icon="🔎", layout="wide", initial_sidebar_state="collapsed")

# ---------------------------------------------------------------- style
st.markdown("""
<style>
:root { --up:#e5484d; --down:#30a46c; --ink:#11181c; --muted:#687076; --card:#ffffff; --line:#e6e8eb; --brand:#3e63dd; }
.block-container { padding-top: 1.2rem; max-width: 1280px; }
.gc-hero { display:flex; justify-content:space-between; align-items:center; margin-bottom:.6rem; }
.gc-logo { font-size:1.6rem; font-weight:800; letter-spacing:-.02em; }
.gc-logo span { color: var(--brand); }
.gc-sub { color: var(--muted); font-size:.92rem; }
.gc-card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:14px 16px; margin-bottom:10px;
           box-shadow: 0 1px 2px rgba(0,0,0,.04); }
.gc-card h4 { margin:0; font-size:1.02rem; }
.gc-code { color:var(--muted); font-size:.8rem; }
.gc-up { color:var(--up); font-weight:700; } .gc-down { color:var(--down); font-weight:700; }
.gc-badge { display:inline-block; padding:2px 9px; border-radius:999px; font-size:.75rem; font-weight:600; }
.gc-hot { background:#ffefef; color:#ce2c31; } .gc-calm { background:#f1f3f5; color:#687076; }
.gc-pass { background:#e9f9ee; color:#18794e; } .gc-part { background:#fff7e6; color:#ad5700; } .gc-fail { background:#f1f3f5; color:#687076; }
.gc-bar { height:8px; border-radius:6px; background:#f1f3f5; overflow:hidden; display:flex; margin-top:6px; }
.gc-bar .b { background:var(--up); } .gc-bar .s { background:var(--down); }
.gc-gauge { font-size:.78rem; color:var(--muted); margin-top:6px; }
.gc-step { border-left:4px solid var(--line); padding:8px 12px; margin:6px 0; background:#fafbfc; border-radius:8px; }
.gc-step.pass { border-color:#30a46c; } .gc-step.part { border-color:#f5a623; } .gc-step.fail { border-color:#c1c8cd; }
.gc-verdict { font-size:1.35rem; font-weight:800; }
.gc-post { padding:6px 10px; border-radius:8px; background:#f8f9fa; margin:4px 0; font-size:.9rem; }
.gc-post mark { background:#fff1a8; padding:0 2px; border-radius:3px; }
.gc-kpi { font-size:1.6rem; font-weight:800; } .gc-kpil { color:var(--muted); font-size:.8rem; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- text
TXT = {
    "zh": {"tagline": "股吧突然炸了？让 AI 查清原因，并告诉你历史上这类情况之后怎么走",
           "nav": ["🛰️ 今日雷达", "📈 个股", "🔍 AI 调查", "🧪 回测实验室", "💼 模拟交易", "📊 系统表现"],
           "watched": "关注股票", "spikes_m": "近 30 天异动", "last": "最近一次异动", "open": "查看",
           "heat": "股吧热度", "bulls": "看多", "bears": "看空", "spike": "🔥 异动", "calm": "平静",
           "pick_spike": "选择一次异动", "investigate": "🔍 让 AI 调查这次异动", "mode": "调查模式",
           "modes": {"agent": "🧠 智能（AI 读帖子定方向，查到即停）", "keyword": "⚡ 快速（关键词规则）",
                     "exhaustive": "🔬 全面（7 项全部检验）", "manual": "🧪 我自己来查"},
           "start": "开始调查", "reading": "正在阅读 {n} 条帖子…", "clues": "AI 从帖子里找到的线索",
           "priors": "各原因的初始可能性", "testing": "正在检验：", "posterior": "可能性变化",
           "stop": "停止调查", "concl": "调查结论", "conf": "可信度", "timeline": "时间线",
           "history": "历史上同类异动之后（相对沪深300超额收益）", "agree": "你同意这个结论吗？",
           "yes": "👍 同意", "no": "👎 不同意", "your_cause": "你认为的原因", "thanks": "已记录你的反馈，谢谢！",
           "buy": "💼 模拟买入", "confirm": "确认模拟下单", "cancel": "取消", "evidence": "需要一份官方公告作为依据",
           "no_filing": "这次异动附近没有可作依据的官方公告，模拟下单不可用（这是有意的安全设计）。",
           "manual_hint": "点下面的按钮亲自检验一个原因。可能性会实时更新；满足停止条件时系统会提示你。",
           "stop_ok": "✅ 已满足停止条件：已有原因通过检验，且剩余未检验原因合计可能性 < 20%",
           "stop_cap": "⏹️ 已检验 5 项，达到上限", "reset": "重新开始", "n_small": "样本少于 5，仅供参考",
           "live": "实时 AI", "replay": "回放已保存的 AI 调查", "no_key": "未设置 API key：回放已保存的调查过程",
           "positions": "模拟持仓", "empty": "还没有模拟持仓。在调查结论页可以模拟买入。",
           "perf_note": "以下指标都来自 results/ 中的实测文件。", "back": "← 返回"},
    "en": {"tagline": "Forum exploding? Let the AI find out why — and see what happened after similar spikes",
           "nav": ["🛰️ Radar", "📈 Stock", "🔍 AI investigation", "🧪 Backtest lab", "💼 Paper trading", "📊 Performance"],
           "watched": "Watched stocks", "spikes_m": "Spikes, last 30 days", "last": "Latest spike", "open": "Open",
           "heat": "Forum heat", "bulls": "Bullish", "bears": "Bearish", "spike": "🔥 Spike", "calm": "Calm",
           "pick_spike": "Pick a spike", "investigate": "🔍 Let the AI investigate", "mode": "Mode",
           "modes": {"agent": "🧠 Smart (AI reads the posts, stops when sure)", "keyword": "⚡ Fast (keyword rules)",
                     "exhaustive": "🔬 Thorough (all 7 tests)", "manual": "🧪 Investigate it myself"},
           "start": "Start", "reading": "Reading {n} posts…", "clues": "Clues the AI found in the posts",
           "priors": "Starting likelihood of each cause", "testing": "Testing: ", "posterior": "Likelihood over the investigation",
           "stop": "Stop", "concl": "Conclusion", "conf": "Confidence", "timeline": "Timeline",
           "history": "After similar spikes (excess return vs CSI 300)", "agree": "Do you agree?",
           "yes": "👍 Agree", "no": "👎 Disagree", "your_cause": "Your cause", "thanks": "Feedback saved — thank you!",
           "buy": "💼 Paper buy", "confirm": "Confirm paper order", "cancel": "Cancel", "evidence": "Needs an official filing as evidence",
           "no_filing": "No official filing near this spike can back an order; paper buying is disabled (by design).",
           "manual_hint": "Click a cause to test it yourself. Likelihoods update live; you'll be told when the stop rule holds.",
           "stop_ok": "✅ Stop rule met: a cause passed and untested causes total < 20%",
           "stop_cap": "⏹️ 5 tests done: the cap", "reset": "Start over", "n_small": "fewer than 5 cases — indicative only",
           "live": "Live AI", "replay": "Replay a saved AI investigation", "no_key": "No API key: replaying a saved investigation",
           "positions": "Paper positions", "empty": "No paper positions yet. You can paper-buy from a conclusion.",
           "perf_note": "Every number below comes from a measured file in results/.", "back": "← Back"},
}
CAUSE = {"zh": {"A": ("公司官方", "📢"), "B": ("媒体/传闻", "📰"), "C": ("板块联动", "🧩"), "D": ("海外映射", "🌎"),
                "E": ("大盘行情", "📉"), "F": ("政策/宏观", "🏛️"), "G": ("资金/交易结构", "💰"), "H": ("无法解释", "❓")},
         "en": {"A": ("Company official", "📢"), "B": ("Media / rumour", "📰"), "C": ("Sector", "🧩"), "D": ("Overseas", "🌎"),
                "E": ("Market", "📉"), "F": ("Policy / macro", "🏛️"), "G": ("Money flow", "💰"), "H": ("Unexplained", "❓")}}
COLORS = {"A": "#3e63dd", "B": "#e5484d", "C": "#8e4ec6", "D": "#12a594", "E": "#f76b15", "F": "#ffc53d", "G": "#30a46c"}

ss = st.session_state
ss.setdefault("lang", "zh")
ss.setdefault("nav", 0)
ss.setdefault("stock", "688256")
ss.setdefault("spike", None)

top = st.columns([6, 1])
with top[1]:
    ss.lang = st.selectbox(" ", ["zh", "en"], index=["zh", "en"].index(ss.lang),
                           format_func=lambda x: "中文" if x == "zh" else "English", label_visibility="collapsed")
L, CN = TXT[ss.lang], CAUSE[ss.lang]
with top[0]:
    st.markdown('<div class="gc-hero"><div><div class="gc-logo">Guba<span>Check</span></div>'
                '<div class="gc-sub">%s</div></div></div>' % L["tagline"], unsafe_allow_html=True)

if "_goto" in ss:                       # navigation requested by a button on the previous run
    ss["nav"] = ss.pop("_goto")
page = st.radio(" ", range(6), horizontal=True, format_func=lambda i: L["nav"][i],
                label_visibility="collapsed", key="nav")

stocks = store.load("stocks")
spikes = [s for s in store.load("spikes") if not s.get("synthetic")]
daily = store.load("daily_stats")


def cname(c):
    return "%s %s" % (CN[c][1], CN[c][0])


def bars(code):
    return sorted(store.load("prices").get(code, []), key=lambda b: b["date"])


def go_to(p, **kw):
    ss["_goto"] = p
    for k, v in kw.items():
        ss[k] = v
    st.rerun()


def gold_labels():
    p = os.path.join(ROOT, "evals", "cause_labels.csv")
    if not os.path.exists(p):
        return {}
    return {r["spike_id"]: r["primary"] for r in csv.DictReader(open(p, encoding="utf-8-sig"))}


def saved_runs():
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "results", "results_*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if d.get("results") and d["results"][0]["record"].get("arm"):
            arm = d["results"][0]["record"]["arm"]
            if arm not in out or "live" in f:
                out[arm] = {r["case_id"]: r["record"] for r in d["results"]}
    return out


# ================================================================ RADAR
def page_radar():
    last_day = max(s["date"] for s in spikes)
    recent = [s for s in spikes if s["date"] >= (pd.Timestamp(last_day) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")]
    k = st.columns(3)
    for col, (v, lab) in zip(k, ((len(stocks), L["watched"]), (len(recent), L["spikes_m"]),
                                 ("%s %s" % (stocks[spikes[-1]["stock"]]["name"], spikes[-1]["date"][5:]), L["last"]))):
        col.markdown('<div class="gc-card"><div class="gc-kpi">%s</div><div class="gc-kpil">%s</div></div>' % (v, lab),
                     unsafe_allow_html=True)
    codes = list(stocks)
    for row in range(0, len(codes), 5):
        cols = st.columns(5)
        for col, code in zip(cols, codes[row:row + 5]):
            b = bars(code)
            last, prev = b[-1], b[-2]
            chg = 100 * (last["close"] / prev["close"] - 1)
            d = daily.get(code, [])[-1] if daily.get(code) else {}
            z = d.get("z_posts") or 0
            bull = d.get("bull_share") or 0.5
            hot = z >= config.Z_POSTS
            heat = max(0, min(100, int(50 + 15 * z)))
            with col:
                st.markdown(
                    '<div class="gc-card"><h4>%s</h4><div class="gc-code">%s</div>'
                    '<div style="margin-top:6px"><span class="%s">%.2f %s%.2f%%</span></div>'
                    '<div class="gc-gauge">%s %d / 100 &nbsp; <span class="gc-badge %s">%s</span></div>'
                    '<div class="gc-bar"><div class="b" style="width:%d%%"></div><div class="s" style="width:%d%%"></div></div>'
                    '<div class="gc-gauge">%s %d%% · %s %d%%</div></div>'
                    % (stocks[code]["name"], code, "gc-up" if chg >= 0 else "gc-down", last["close"],
                       "+" if chg >= 0 else "", chg, L["heat"], heat, "gc-hot" if hot else "gc-calm",
                       L["spike"] if hot else L["calm"], int(100 * bull), 100 - int(100 * bull),
                       L["bulls"], int(100 * bull), L["bears"], 100 - int(100 * bull)), unsafe_allow_html=True)
                if st.button(L["open"], key="open_" + code, use_container_width=True):
                    go_to(1, stock=code, spike=None)


# ================================================================ STOCK
def page_stock():
    code = st.selectbox(" ", list(stocks), index=list(stocks).index(ss.stock), label_visibility="collapsed",
                        format_func=lambda c: "%s  %s" % (stocks[c]["name"], c))
    ss.stock = code
    b = pd.DataFrame(bars(code))
    d = pd.DataFrame(daily.get(code, []))
    sp = [s for s in spikes if s["stock"] == code]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.65, 0.35], vertical_spacing=0.04)
    fig.add_trace(go.Candlestick(x=b["date"], open=b["open"], high=b["high"], low=b["low"], close=b["close"],
                                 increasing_line_color="#e5484d", decreasing_line_color="#30a46c", name="K"), 1, 1)
    if not d.empty:
        fig.add_trace(go.Bar(x=d["date"], y=d["posts"], marker_color="#c1c8cd", name=L["heat"]), 2, 1)
    if sp:
        px = {r["date"]: r["high"] for r in bars(code)}
        fig.add_trace(go.Scatter(x=[s["date"] for s in sp], y=[px.get(s["date"], None) for s in sp], mode="markers+text",
                                 text=["🔥"] * len(sp), textposition="top center", marker=dict(size=1, color="rgba(0,0,0,0)"),
                                 name=L["spike"], hovertext=["%s posts z=%.1f" % (s["posts"], s["z_posts"]) for s in sp]), 1, 1)
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=10, b=10), xaxis_rangeslider_visible=False,
                      showlegend=False, plot_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("#### " + L["pick_spike"])
    gold = gold_labels()
    cols = st.columns(4)
    for i, s in enumerate(reversed(sp)):
        with cols[i % 4]:
            st.markdown('<div class="gc-card"><b>🔥 %s</b><div class="gc-gauge">%d posts · z %.1f · %s %d%%</div></div>'
                        % (s["date"], s["posts"], s["z_posts"], L["bulls"], 100 * s["bull_share"]), unsafe_allow_html=True)
            if st.button(L["investigate"], key="inv_" + s["spike_id"], use_container_width=True):
                go_to(2, spike=s["spike_id"], run=None)


# ================================================================ INVESTIGATE
def highlight(title, words):
    for w in sorted(set(words), key=len, reverse=True):
        if w:
            title = title.replace(w, "<mark>%s</mark>" % w)
    return title


def clue_words(title):
    from pipeline.v4_scripts import KEYWORDS
    out = []
    for c, pat in KEYWORDS.items():
        out += [(m, c) for m in re.findall(pat, title)]
    return out


def posterior_chart(history, key):
    rows = []
    for k, h in enumerate(history):
        for c, v in h["posterior"].items():
            rows.append({"step": k, "cause": c, "p": v})
    df = pd.DataFrame(rows)
    fig = go.Figure()
    for c in config.CAUSES:
        sub = df[df.cause == c]
        fig.add_trace(go.Scatter(x=sub["step"], y=sub["p"], mode="lines+markers", name=cname(c),
                                 line=dict(color=COLORS[c], width=3)))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(range=[0, 1], tickformat=".0%"),
                      xaxis=dict(dtick=1, title=None), legend=dict(orientation="h", y=-0.25), plot_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True, key=key)


NOTE_ZH = {
    "official evidence in the spike's direction before the forum surge": "讨论激增之前已有与异动方向一致的官方公告或董秘回复",
    "filings exist but after onset, neutral, or against the move": "有公告，但发布在异动之后、内容中性或方向相反",
    "no filing or reply in [D-3, D]": "异动前 3 天内没有公告或董秘回复",
    "an abnormal burst of company-specific coverage around the spike": "异动前后，关于本公司的资讯数量异常激增",
    "company coverage exists but is ordinary": "有本公司资讯，但数量处于平常水平",
    "no company-specific article": "没有关于本公司的资讯",
    "most peers moved abnormally the same way": "多数同板块股票同向异常波动",
    "some peers moved abnormally": "部分同板块股票异常波动",
    "peers were normal": "同板块股票表现正常",
    "US peers moved abnormally overnight and the stock gapped the same way at the open": "隔夜美股同行异常波动，且该股开盘同向跳空",
    "US peers moved abnormally but the stock did not gap at the open": "隔夜美股同行异常，但该股开盘没有跳空",
    "no abnormal US peer move on the previous session": "前一个美股交易日，同行没有异常波动",
    "no US peer defined for this stock's product line": "该行业没有对应的美股同行",
    "the whole market moved abnormally": "大盘整体异常波动",
    "the market moved noticeably": "大盘波动较明显",
    "the market was normal": "大盘表现正常",
    "policy news preceded the surge and the move was broad": "异动前有政策消息，且板块或大盘同步波动",
    "policy news, but the move was not broad": "有政策消息，但波动范围不广",
    "no policy news before the surge": "异动前没有政策类消息",
    "on the top list with an extreme one-sided net buy/sell": "登上龙虎榜，且净买入/卖出极端",
    "on the top list, ordinary net flow": "登上龙虎榜，资金流向普通",
    "not on the top list": "没有登上龙虎榜",
}


def stop_text(inv, primary):
    tested = "、".join(CN[c][0] for c in inv.get("order", [])) if ss.lang == "zh" else ", ".join(CN[c][0] for c in inv.get("order", []))
    passed = [c for c, v in inv.get("tested", {}).items() if v == "PASS"]
    n = inv.get("calls", len(inv.get("order", [])))
    if ss.lang == "zh":
        why = ("已有原因通过检验（%s），剩余未检验原因合计可能性低于 20%%" % "、".join(CN[c][0] for c in passed)) if passed and n < 5 \
            else ("已检验 %d 项，达到上限" % n) if n >= 5 else "全部检验完毕"
        return "共检验 %d 项：%s。停止原因：%s。结论：%s" % (n, tested, why, cname(primary))
    why = ("a cause passed (%s) and untested causes total < 20%%" % ", ".join(CN[c][0] for c in passed)) if passed and n < 5 \
        else ("%d tests: the cap" % n) if n >= 5 else "all tested"
    return "%d tests: %s. Stopped because %s. Conclusion: %s" % (n, tested, why, cname(primary))


def step_card(c, out):
    cls = {"PASS": "pass", "PARTIAL": "part", "FAIL": "fail"}[out["verdict"]]
    badge = {"PASS": "gc-pass", "PARTIAL": "gc-part", "FAIL": "gc-fail"}[out["verdict"]]
    m = ", ".join("%s=%s" % (k, v) for k, v in out["metrics"].items() if v is not None)
    st.markdown('<div class="gc-step %s"><b>%s %s</b> &nbsp;<span class="gc-badge %s">%s</span>'
                '<div class="gc-gauge">%s</div><div class="gc-gauge">%s</div></div>'
                % (cls, L["testing"], cname(c), badge, out["verdict"],
                   NOTE_ZH.get(out["note"], out["note"]) if ss.lang == "zh" else out["note"], m), unsafe_allow_html=True)
    if out["evidence"]:
        with st.expander("📎 " + ("证据" if ss.lang == "zh" else "evidence"), expanded=False):
            st.dataframe(pd.DataFrame(out["evidence"]).head(6), hide_index=True, use_container_width=True)


def history_chart(cause):
    p = os.path.join(ROOT, "results", "cause_backtest_gold.json")
    if not os.path.exists(p):
        return
    g = json.load(open(p))["by_cause"].get(cause, {}).get("all")
    if not g or not g["horizons"]:
        st.caption("—")
        return
    h = g["horizons"]
    xs, ys = list(h), [v["mean_excess_pct"] for v in h.values()]
    fig = go.Figure(go.Bar(x=xs, y=ys, marker_color=["#e5484d" if y >= 0 else "#30a46c" for y in ys],
                           text=["%+.1f%%" % y for y in ys], textposition="outside"))
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor="white", yaxis_title="%")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("n = %d%s" % (g["n"], "　⚠️ " + L["n_small"] if g["n"] < 5 else ""))


def timeline(s, outs):
    pts = [("异动开始" if ss.lang == "zh" else "onset", s["onset"], "#e5484d")]
    for c, o in outs:
        for e in o["evidence"][:3]:
            t = e.get("time") or e.get("us_date")
            if t and re.match(r"\d{4}-\d{2}-\d{2}", str(t)):
                pts.append(("%s %s" % (CN[c][1], str(e.get("title", e.get("id", "")))[:18]), str(t)[:16], COLORS.get(c, "#888")))
    df = pd.DataFrame(pts, columns=["label", "t", "c"])
    df["t"] = pd.to_datetime(df["t"].str.slice(0, 16), errors="coerce", format="mixed")
    df = df.dropna()
    if len(df) <= 1:
        st.caption("—")
        return
    fig = go.Figure(go.Scatter(x=df["t"], y=[0] * len(df), mode="markers+text", text=df["label"],
                               textposition="top center", marker=dict(size=14, color=df["c"])))
    fig.update_layout(height=200, margin=dict(l=10, r=10, t=30, b=10), yaxis=dict(visible=False), plot_bgcolor="white")
    st.plotly_chart(fig, use_container_width=True)


def save_feedback(sid, agree, cause, concluded):
    with open(os.path.join(ROOT, "results", "user_feedback.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"spike_id": sid, "agree": agree, "user_cause": cause, "system_cause": concluded,
                             "time": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")


@st.dialog("💼 模拟下单 / Paper order")
def order_dialog(s, filing):
    st.write("**%s %s**" % (stocks[s["stock"]]["name"], s["stock"]))
    st.write("%s：%s（%s）" % (L["evidence"], filing["title"], filing["time"][:16]))
    st.caption("人工确认 gate：只有你点确认才会下单。/ Human gate: nothing happens until you confirm.")
    c1, c2 = st.columns(2)
    if c1.button(L["confirm"], type="primary", use_container_width=True):
        fill = paper_broker.simulate_at(s["stock"], filing["time"])
        fill.update(spike_id=s["spike_id"], evidence_id=filing["ann_id"], name=stocks[s["stock"]]["name"])
        with open(os.path.join(ROOT, "results", "paper_ledger.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(fill, ensure_ascii=False) + "\n")
        st.success("已提交 / submitted: %s" % fill.get("status"))
        st.json(fill)
    if c2.button(L["cancel"], use_container_width=True):
        st.rerun()


def conclusion_block(s, primary, posterior, outs):
    conf = posterior.get(primary, 0) if primary != "H" else 1 - max(posterior.values() or [0])
    gold = gold_labels().get(s["spike_id"])
    c1, c2 = st.columns([2, 3])
    with c1:
        st.markdown('<div class="gc-card"><div class="gc-kpil">%s</div><div class="gc-verdict">%s</div>'
                    '<div class="gc-gauge">%s %.0f%%</div>%s</div>'
                    % (L["concl"], cname(primary), L["conf"], 100 * conf,
                       ('<div class="gc-gauge">%s: %s</div>' % ("人工标注" if ss.lang == "zh" else "my label", cname(gold))) if gold else ""),
                    unsafe_allow_html=True)
        st.markdown("**%s**" % L["agree"])
        a, b = st.columns(2)
        if a.button(L["yes"], key="fb_y", use_container_width=True):
            save_feedback(s["spike_id"], True, primary, primary)
            st.toast(L["thanks"])
        with b.popover(L["no"], use_container_width=True):
            pick = st.radio(L["your_cause"], list(CN), format_func=cname, key="fb_pick")
            if st.button("OK", key="fb_ok"):
                save_feedback(s["spike_id"], False, pick, primary)
                st.toast(L["thanks"])
        filings = [a for a in store.load("announcements") if a["stock"] == s["stock"] and not a["procedural"]
                   and a["time"][:10] <= s["date"] and a["time"][:10] >= (pd.Timestamp(s["date"]) - pd.Timedelta(days=3)).strftime("%Y-%m-%d")
                   and a["type"] not in config.NEVER_BULLISH_TYPES]
        if filings:
            if st.button(L["buy"], use_container_width=True):
                order_dialog(s, filings[-1])
        else:
            st.caption(L["no_filing"])
    with c2:
        st.markdown("**%s**" % L["history"])
        history_chart(primary)
    st.markdown("**%s**" % L["timeline"])
    timeline(s, outs)


def page_investigate():
    sid = ss.spike or spikes[-1]["spike_id"]
    opts = [x["spike_id"] for x in spikes]
    sid = st.selectbox(" ", opts, index=opts.index(sid), label_visibility="collapsed",
                       format_func=lambda i: "🔥 %s  %s  %s" % (stocks[i[4:10]]["name"], i[4:10], i[-8:]))
    if sid != ss.spike:
        ss.spike, ss.run = sid, None
    s = store.spike(sid)
    posts = {p["post_id"]: p for p in store.load("posts")}
    top = [posts[i] for i in s["sample_post_ids"] if i in posts][:10]
    k = st.columns(4)
    for col, (v, lab) in zip(k, (("%d" % s["posts"], "帖子 / posts"), ("z %.1f" % s["z_posts"], L["heat"]),
                                 ("%d%%" % (100 * s["bull_share"]), L["bulls"]), (s["onset"][5:16], "onset"))):
        col.markdown('<div class="gc-card"><div class="gc-kpi">%s</div><div class="gc-kpil">%s</div></div>' % (v, lab),
                     unsafe_allow_html=True)
    mode = st.radio(L["mode"], list(L["modes"]), format_func=lambda m: L["modes"][m], horizontal=True, key="mode")
    if mode == "manual":
        return manual_mode(s, top)
    runs = saved_runs()
    live_ok = bool(os.environ.get("OPENROUTER_API_KEY"))
    if mode == "agent" and not live_ok:
        st.caption("🛈 " + L["no_key"])
    if st.button("▶ " + L["start"], type="primary"):
        ss.run = {"mode": mode, "sid": sid}
    if not ss.get("run") or ss.run.get("sid") != sid or ss.run.get("mode") != mode:
        return
    # ---- obtain the record (live, saved, or scripted)
    rec = None
    if mode == "agent" and live_ok and os.environ.get("GUBACHECK_BACKEND") == "live":
        from core.agent import run_case
        with st.spinner(L["live"] + "…"):
            rec = run_case(sid, arm="agent")
    elif mode in runs and sid in runs[mode]:
        rec = runs[mode][sid]
    if rec is None:
        from core.agent import run_case
        rec = run_case(sid, arm="keyword" if mode == "agent" else mode)
    inv = rec.get("investigation", {})
    animate = not ss.run.get("shown")
    pause = (lambda t: time.sleep(t)) if animate else (lambda t: None)
    # ---- step 1: read posts, clues
    with st.status(L["reading"].format(n=s["posts"]), expanded=True) as status:
        pause(0.8)
        st.markdown("**%s**" % L["clues"])
        for p in top[:6]:
            words = [w for w, _ in clue_words(p["title"])]
            st.markdown('<div class="gc-post">%s %s</div>' % ("📰" if p.get("post_type") == 20 else "💬",
                                                              highlight(p["title"], words)), unsafe_allow_html=True)
            pause(0.15)
        status.update(state="complete")
    hist = inv.get("history", [])
    if hist:
        pri = hist[0]["posterior"]
        st.markdown("**%s**" % L["priors"])
        fig = go.Figure(go.Bar(y=[cname(c) for c in pri], x=list(pri.values()), orientation="h",
                               marker_color=[COLORS[c] for c in pri], text=["%.0f%%" % (100 * v) for v in pri.values()],
                               textposition="outside"))
        fig.update_layout(height=260, margin=dict(l=10, r=40, t=10, b=10), xaxis=dict(tickformat=".0%", range=[0, 1]),
                          plot_bgcolor="white")
        st.plotly_chart(fig, use_container_width=True)
    # ---- step 2: tests, one by one
    outs = []
    chart = st.empty()
    for n, c in enumerate(inv.get("order", []), 1):
        with st.spinner(L["testing"] + cname(c)):
            pause(0.7)
            out = causes.CAUSE_TOOLS[c](sid)
        outs.append((c, out))
        step_card(c, out)
        with chart.container():
            st.markdown("**%s**" % L["posterior"])
            posterior_chart(hist[:n + 1], key="pc_%d" % n)
    primary = rec.get("primary") or "H"
    st.info("⏹️ " + stop_text(inv, primary))
    ss.run["shown"] = True
    conclusion_block(s, primary, inv.get("posterior", {}), outs)


def manual_mode(s, top):
    st.caption(L["manual_hint"])
    key = "manual_" + s["spike_id"]
    if key not in ss or st.button(L["reset"]):
        inv = investigation.Investigation("agent")
        from pipeline.v4_scripts import keyword_scores
        inv.set_scores(keyword_scores({"top_posts": top}))
        ss[key] = {"inv": inv, "outs": []}
    state = ss[key]
    inv = state["inv"]
    for row in (config.CAUSES[:4], config.CAUSES[4:]):
        cols = st.columns(4)
        for col, c in zip(cols, row):
            p = inv.posterior()[c]
            done = c in inv.tested
            verdict = inv.tested.get(c)
            col.markdown('<div class="gc-card" style="margin-bottom:4px"><b>%s</b><div class="gc-kpi" style="font-size:1.2rem">%.0f%%</div>%s</div>'
                         % (cname(c), 100 * p, ('<span class="gc-badge %s">%s</span>' % (
                             {"PASS": "gc-pass", "PARTIAL": "gc-part", "FAIL": "gc-fail"}[verdict], verdict)) if verdict else ""),
                         unsafe_allow_html=True)
            if col.button(("✓ " if done else "🔍 ") + ("已检验" if done and ss.lang == "zh" else "done" if done else
                                                     "检验" if ss.lang == "zh" else "test"),
                          key="m_" + c, disabled=done or inv.should_stop(), use_container_width=True):
                out = causes.CAUSE_TOOLS[c](s["spike_id"])
                inv.apply(c, out["verdict"])
                state["outs"].append((c, out))
                st.rerun()
    for c, out in state["outs"]:
        step_card(c, out)
    if len(inv.history) > 1:
        posterior_chart(inv.history, key="manual_chart")
    if inv.should_stop():
        st.success(L["stop_ok"] if any(v == "PASS" for v in inv.tested.values()) else L["stop_cap"])
        res = inv.result()
        conclusion_block(s, res["primary"], res["posterior"], state["outs"])
    else:
        st.caption("未检验原因合计可能性 / untested mass: %.0f%%" % (100 * inv.untested_mass()))


# ================================================================ PAPER
def page_paper():
    p = os.path.join(ROOT, "results", "paper_ledger.jsonl")
    rows = [json.loads(l) for l in open(p, encoding="utf-8")] if os.path.exists(p) else []
    st.markdown("#### " + L["positions"])
    if not rows:
        st.info(L["empty"])
        return
    for r in rows[::-1]:
        st.markdown('<div class="gc-card"><b>%s %s</b> · %s<div class="gc-gauge">entry %s @ %s · %s shares · %s</div></div>'
                    % (r.get("name", ""), r.get("code", ""), r.get("status"), r.get("entry_date"), r.get("entry_price"),
                       r.get("shares"), ("return %s%%" % r.get("return_pct")) if r.get("return_pct") is not None else r.get("reason", "")),
                    unsafe_allow_html=True)


# ================================================================ PERFORMANCE
def page_perf():
    st.caption(L["perf_note"])
    runs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "results", "results_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        if d.get("summary", {}).get("arm") and d["summary"].get("macro_f1") is not None:
            runs.append(d["summary"])
    if runs:
        df = pd.DataFrame(runs)
        c1, c2 = st.columns(2)
        with c1:
            fig = go.Figure(go.Bar(x=df["arm"], y=df["macro_f1"], marker_color="#3e63dd",
                                   text=["%.2f" % v for v in df["macro_f1"]], textposition="outside"))
            fig.add_hline(y=runs[0]["majority_baseline_macro_f1"], line_dash="dash",
                          annotation_text="always-%s" % runs[0]["majority_class"])
            fig.update_layout(title="Attribution macro-F1", height=320, plot_bgcolor="white", margin=dict(t=40))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = go.Figure(go.Bar(x=df["arm"], y=df["mean_cause_checks"], marker_color="#8e4ec6",
                                   text=["%.1f" % v for v in df["mean_cause_checks"]], textposition="outside"))
            fig.update_layout(title="Cause tests per spike", height=320, plot_bgcolor="white", margin=dict(t=40))
            st.plotly_chart(fig, use_container_width=True)
    j = os.path.join(ROOT, "results", "judge_eval.json")
    s_ = os.path.join(ROOT, "results", "sentiment_eval.json")
    c1, c2 = st.columns(2)
    if os.path.exists(s_):
        d = json.load(open(s_))["methods"]
        fig = go.Figure(go.Bar(x=list(d), y=[v["macro_f1"] for v in d.values()], marker_color="#12a594",
                               text=["%.2f" % v["macro_f1"] for v in d.values()], textposition="outside"))
        fig.update_layout(title="Forum sentiment macro-F1", height=320, plot_bgcolor="white", margin=dict(t=40))
        c1.plotly_chart(fig, use_container_width=True)
    if os.path.exists(j):
        d = json.load(open(j))["methods"]
        fig = go.Figure(go.Bar(x=list(d), y=[v["batch2_macro_f1"] for v in d.values()], marker_color="#f76b15",
                               text=["%.2f" % v["batch2_macro_f1"] for v in d.values()], textposition="outside"))
        fig.update_layout(title="Filing judge macro-F1 (RAG ablation)", height=320, plot_bgcolor="white", margin=dict(t=40))
        c2.plotly_chart(fig, use_container_width=True)
    g = os.path.join(ROOT, "results", "guardrails.json")
    if os.path.exists(g):
        d = json.load(open(g))
        st.markdown("**Guardrails %d / %d**" % (sum(r["passed"] for r in d), len(d)))
        st.dataframe(pd.DataFrame([{"id": r["id"], "catches": r["catches"], "passed": "✅" if r["passed"] else "❌"} for r in d]),
                     hide_index=True, use_container_width=True)


# ================================================================ BACKTEST LAB
def page_backtest():
    zh = ss.lang == "zh"
    p = os.path.join(ROOT, "results", "cause_backtest_rows_gold.json")
    if not os.path.exists(p):
        st.info("—")
        return
    rows = json.load(open(p))
    st.markdown("#### " + ("如果每次股吧异动后买入，会怎样？" if zh else "What if I bought after every forum spike?"))
    st.caption("在异动日的下一个交易日开盘买入，持有 N 个交易日后收盘卖出；已扣除佣金、过户费和印花税；超额收益 = 个股 − 沪深300。"
               "异动原因用的是人工标注。" if zh else
               "Buy at the next open after the spike day, sell at the close N trading days later; net of fees; "
               "excess = stock − CSI 300. Causes are my hand labels.")
    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
    present = sorted({r["cause"] for r in rows})
    pick = c1.multiselect("异动原因" if zh else "Cause", present, default=present, format_func=cname)
    direction = c2.selectbox("讨论方向" if zh else "Direction", ["all", "bullish", "bearish"],
                             format_func=lambda x: {"all": "全部" if zh else "all", "bullish": "偏多" if zh else "bullish",
                                                    "bearish": "偏空" if zh else "bearish"}[x])
    period = c3.selectbox("时期" if zh else "Period", ["all", "observe", "check"],
                          format_func=lambda x: {"all": "全部" if zh else "all", "observe": "观察期（4 月前）" if zh else "observe (< Apr)",
                                                 "check": "检验期（4 月起）" if zh else "check (≥ Apr)"}[x])
    hold = c4.select_slider("持有天数" if zh else "Hold (days)", options=[1, 2, 3, 5, 10, 15, 20], value=5)
    sel = [r for r in rows if r["cause"] in pick and (direction == "all" or r["direction"] == direction)
           and (period == "all" or r["period"] == period) and str(hold) in r["excess"]]
    if not sel:
        st.warning("没有符合条件的异动" if zh else "No spike matches")
        return
    ex = [r["excess"][str(hold)] for r in sel]
    net = [r["returns"][str(hold)] for r in sel]
    k = st.columns(4)
    for col, (v, lab) in zip(k, (("%d" % len(sel), "交易次数" if zh else "trades"),
                                 ("%+.2f%%" % (sum(net) / len(net)), "平均收益（扣费）" if zh else "mean net return"),
                                 ("%+.2f%%" % (sum(ex) / len(ex)), "平均超额收益" if zh else "mean excess"),
                                 ("%.0f%%" % (100 * sum(x > 0 for x in ex) / len(ex)), "跑赢大盘的比例" if zh else "beat the index"))):
        col.markdown('<div class="gc-card"><div class="gc-kpi">%s</div><div class="gc-kpil">%s</div></div>' % (v, lab),
                     unsafe_allow_html=True)
    if len(sel) < 5:
        st.warning("⚠️ " + L["n_small"])
    left, right = st.columns([3, 2])
    with left:
        st.markdown("**%s**" % ("各持有期的平均超额收益" if zh else "Mean excess return by holding period"))
        hs = ["1", "2", "3", "5", "10", "15", "20"]
        fig = go.Figure()
        for c in pick:
            sub = [r for r in sel if r["cause"] == c]
            if sub:
                ys = [sum(r["excess"].get(h, 0) for r in sub) / len(sub) for h in hs]
                fig.add_trace(go.Scatter(x=["D+" + h for h in hs], y=ys, mode="lines+markers",
                                         name="%s (n=%d)" % (cname(c), len(sub)), line=dict(color=COLORS.get(c, "#888"), width=3)))
        ys = [sum(r["excess"].get(h, 0) for r in sel) / len(sel) for h in hs]
        fig.add_trace(go.Scatter(x=["D+" + h for h in hs], y=ys, mode="lines", name=("全部所选" if zh else "all selected"),
                                 line=dict(color="#11181c", width=4, dash="dash")))
        fig.add_hline(y=0, line_color="#c1c8cd")
        fig.update_layout(height=360, plot_bgcolor="white", yaxis_title="%", margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.markdown("**%s**" % ("逐笔超额收益（持有 %d 天，按时间）" % hold if zh else "Excess return per trade (hold %d d, by date)" % hold))
        sel_sorted = sorted(sel, key=lambda r: (r["spike_id"][-8:], r["spike_id"]))
        xs = list(range(1, len(sel_sorted) + 1))
        ys = [r["excess"][str(hold)] for r in sel_sorted]
        cum, acc = [], 0.0
        for y in ys:
            acc += y
            cum.append(acc / (len(cum) + 1))
        hover = ["%s %s<br>%s" % (stocks[r["spike_id"][4:10]]["name"], r["spike_id"][-8:], cname(r["cause"])) for r in sel_sorted]
        fig = go.Figure([go.Bar(x=xs, y=ys, marker_color=["#e5484d" if y >= 0 else "#30a46c" for y in ys],
                                hovertext=hover, name="每笔" if zh else "per trade"),
                         go.Scatter(x=xs, y=cum, mode="lines", line=dict(color="#11181c", width=3),
                                    name="累计平均" if zh else "running mean")])
        fig.add_hline(y=0, line_color="#c1c8cd")
        fig.update_layout(height=360, plot_bgcolor="white", yaxis_title="%", margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=-0.2), xaxis_title=("第几笔" if zh else "trade #"))
        st.plotly_chart(fig, use_container_width=True)
    with st.expander("逐笔明细" if zh else "Trade list"):
        st.dataframe(pd.DataFrame([{"spike": r["spike_id"], "cause": cname(r["cause"]), "direction": r["direction"],
                                    "net %": r["returns"][str(hold)], "excess %": r["excess"][str(hold)]} for r in sel_sorted]),
                     hide_index=True, use_container_width=True)
    st.markdown("---")
    st.markdown("#### " + ("早期方案：出现官方利好公告就买入" if zh else "Earlier design: buy on the first bullish filing"))
    b = os.path.join(ROOT, "results", "backtest_rag.json")
    if os.path.exists(b):
        d = json.load(open(b))["strategies"]
        names = {"S0_naive_chase": "S0 异动后直接追" if zh else "S0 chase every spike",
                 "S1_gubacheck": "S1 异动后等官方利好再买" if zh else "S1 spike, then first bullish filing",
                 "S2_announcements_only": "S2 所有利好公告都买" if zh else "S2 every bullish filing"}
        fig = go.Figure()
        for k_, v in d.items():
            hz = v["horizons"]
            fig.add_trace(go.Bar(x=["D" + h for h in hz], y=[x["mean_excess_pct"] for x in hz.values()],
                                 name="%s (n=%d)" % (names.get(k_, k_), v["filled"])))
        fig.update_layout(barmode="group", height=320, plot_bgcolor="white", yaxis_title="%", xaxis_type="category",
                          margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("结论：在股吧狂热之后，等到官方利好再买入，平均反而跑输大盘（利好兑现）。这是产品从“买入信号”转向“异动归因”的原因。"
                   if zh else "Finding: buying official good news after a forum frenzy underperformed on average — why the product "
                   "moved from buy signals to attribution.")


[page_radar, page_stock, page_investigate, page_backtest, page_paper, page_perf][page]()
