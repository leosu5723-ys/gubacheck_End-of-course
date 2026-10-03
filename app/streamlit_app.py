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
                    this stock's earlier spikes with the same
                    cause (D+N returns table) and a suggestion (rule-based,
                    or written by the model with RAG over the company's
                    filings). The user can (a) choose the mode, (b) run the
                    tests themselves ("investigate it yourself"), and
                    (c) agree / disagree with the conclusion (saved).

Evaluation results live in results/ and evals/EVALS.md, not in the app.
Everything reads the frozen snapshot and results/: no key needed. With an
OpenRouter key (⚙️ API, or OPENROUTER_API_KEY) the agent runs live;
otherwise saved agent runs are replayed.
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

from core import causes, config, investigation, store  # noqa: E402

st.set_page_config(page_title="GubaCheck", page_icon="🔎", layout="wide", initial_sidebar_state="collapsed")

# ---------------------------------------------------------------- style
st.markdown("""
<style>
:root { --up:#e5484d; --down:#30a46c; --ink:#11181c; --muted:#687076; --card:#ffffff; --line:#e6e8eb; --brand:#3e63dd; }
header[data-testid="stHeader"] { display:none; }
.gc-name { font-size:1.05rem; font-weight:700; margin-bottom:2px; }
.gc-tip { position:relative; cursor:help; border-bottom:1px dotted #9ba1a6; }
.gc-tipbox { visibility:hidden; opacity:0; position:absolute; z-index:9999; left:0; top:130%; width:340px;
  background:#11181c; color:#f1f3f5; padding:10px 12px; border-radius:10px; font-size:12px; line-height:1.55;
  font-weight:400; letter-spacing:0; box-shadow:0 8px 24px rgba(0,0,0,.25); transition:opacity .15s; white-space:normal; }
.gc-tipbox hr { border:none; border-top:1px solid #3a3f44; margin:6px 0; }
.gc-tipbox .gc-tipg { color:#9ba1a6; font-weight:400; }
.gc-tipr { left:auto; right:0; }
.gc-tip:hover .gc-tipbox { visibility:visible; opacity:1; }
.gc-en { color:#687076; font-size:.82rem; margin-top:2px; }
div[data-testid="stColumn"]:hover { z-index:50; }
.st-key-gc-tick button { animation: gcIn .45s cubic-bezier(.2,.8,.2,1), gcOut .45s ease-in 3.5s forwards;
  border-color:#f3c0c2; background:#fff5f5; color:#c62a2f; font-weight:600; }
@keyframes gcIn { from { opacity:0; transform:translateY(-14px) scale(.96); } to { opacity:1; transform:none; } }
@keyframes gcOut { to { opacity:0; transform:translateY(10px); } }   /* Streamlit's toolbar covered the logo */
.block-container { padding-top: 1.2rem; max-width: 1280px; }
.gc-hero { display:flex; justify-content:space-between; align-items:center; margin-bottom:.6rem; }
.gc-logo { font-size:1.6rem; font-weight:800; letter-spacing:-.02em; }
.gc-logo span { color: var(--brand); }
.gc-sub { color: var(--muted); font-size:.85rem; white-space:nowrap; }
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
           "nav": ["🛰️ 今日雷达", "📈 个股", "🔍 AI 调查"],
           "watched": "关注股票", "spikes_m": "近 30 天异动", "last": "最近一次异动", "open": "查看",
           "heat": "股吧热度", "bulls": "看多", "bears": "看空", "spike": "🔥 异动", "calm": "平静",
           "pick_spike": "选择一次异动", "investigate": "🔍 让 AI 调查这次异动", "mode": "调查模式",
           "modes": {"agent": "🧠 智能（AI 读帖子定方向，查到即停）", "routing": "🧭 路由（AI 只排一次序）", "keyword": "⚡ 快速（关键词规则）",
                     "exhaustive": "🔬 全面（7 项全部检验）", "manual": "🧪 我自己来查"},
           "start": "开始调查", "reading": "正在阅读 {n} 条帖子…", "clues": "AI 从帖子里找到的线索",
           "priors": "各原因的初始可能性", "testing": "正在检验：", "posterior": "可能性变化",
           "stop": "停止调查", "concl": "调查结论", "conf": "可信度",
           "history": "历史上同类异动之后（相对沪深300超额收益）", "agree": "你同意这个结论吗？",
           "yes": "👍 同意", "no": "👎 不同意", "your_cause": "你认为的原因", "thanks": "已记录你的反馈，谢谢！",
           "manual_hint": "点下面的按钮亲自检验一个原因。可能性会实时更新；满足停止条件时系统会提示你。",
           "stop_ok": "✅ 已满足停止条件：已有原因通过检验，且剩余未检验原因合计可能性 < 20%",
           "stop_cap": "⏹️ 已检验 5 项，达到上限", "reset": "重新开始", "n_small": "样本少于 5，仅供参考",
           "live": "实时 AI", "replay": "回放已保存的 AI 调查", "no_key": "未设置 API key：回放已保存的调查过程",
           "back": "← 返回"},
    "en": {"tagline": "Forum exploding? Let the AI find out why — and see what happened after similar spikes",
           "nav": ["🛰️ Radar", "📈 Stock", "🔍 AI investigation"],
           "watched": "Watched stocks", "spikes_m": "Spikes, last 30 days", "last": "Latest spike", "open": "Open",
           "heat": "Forum heat", "bulls": "Bullish", "bears": "Bearish", "spike": "🔥 Spike", "calm": "Calm",
           "pick_spike": "Pick a spike", "investigate": "🔍 Let the AI investigate", "mode": "Mode",
           "modes": {"agent": "🧠 Smart (AI reads the posts, stops when sure)", "routing": "🧭 Routing (AI ranks once)", "keyword": "⚡ Fast (keyword rules)",
                     "exhaustive": "🔬 Thorough (all 7 tests)", "manual": "🧪 Investigate it myself"},
           "start": "Start", "reading": "Reading {n} posts…", "clues": "Clues the AI found in the posts",
           "priors": "Starting likelihood of each cause", "testing": "Testing: ", "posterior": "Likelihood over the investigation",
           "stop": "Stop", "concl": "Conclusion", "conf": "Confidence",
           "history": "After similar spikes (excess return vs CSI 300)", "agree": "Do you agree?",
           "yes": "👍 Agree", "no": "👎 Disagree", "your_cause": "Your cause", "thanks": "Feedback saved — thank you!",
           "manual_hint": "Click a cause to test it yourself. Likelihoods update live; you'll be told when the stop rule holds.",
           "stop_ok": "✅ Stop rule met: a cause passed and untested causes total < 20%",
           "stop_cap": "⏹️ 5 tests done: the cap", "reset": "Start over", "n_small": "fewer than 5 cases — indicative only",
           "live": "Live AI", "replay": "Replay a saved AI investigation", "no_key": "No API key: replaying a saved investigation",
           "back": "← Back"},
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

ss.setdefault("api", {"key": os.environ.get("OPENROUTER_API_KEY", ""), "model": config.MODEL if config.MODEL != "openai/gpt-4o-mini"
                       else "deepseek/deepseek-v4.1-flash", "pin": config.PRICE_IN, "pout": config.PRICE_OUT, "ok": None})
@st.cache_data(ttl=3600, show_spinner=False)
def model_catalogue():
    from core import pricing
    return pricing.models()


top = st.columns([3.2, 3.2, 1.1, 0.9], vertical_alignment="center")
alert_slot = top[1].container()
with top[3]:
    ss.lang = st.selectbox(" ", ["zh", "en"], index=["zh", "en"].index(ss.lang),
                           format_func=lambda x: "中文" if x == "zh" else "English", label_visibility="collapsed")
with top[2]:
    api = ss.api
    badge = "🟢" if api["key"] and api["ok"] else ("🟡" if api["key"] else "⚪")
    with st.popover("%s ⚙️ API" % badge, width="stretch"):
        st.markdown("**OpenRouter**")
        api["key"] = st.text_input("API key", value=api["key"], type="password",
                                   help="只保存在本次浏览器会话中，不写入任何文件 / kept in this session only, never written to disk")
        cat = model_catalogue()
        if cat:
            ids = [m["id"] for m in cat]
            if api["model"] not in ids:
                ids.insert(0, api["model"])
            fmt = {m["id"]: "%s · $%.2f / $%.2f" % (m["id"], m["pin"], m["pout"]) for m in cat}
            api["model"] = st.selectbox("Model（可输入搜索 / type to search）", ids, index=ids.index(api["model"]),
                                        format_func=lambda i: fmt.get(i, i),
                                        help="只列出支持工具调用的模型 / tool-calling models only")
            price = next(((m["pin"], m["pout"]) for m in cat if m["id"] == api["model"]), None)
        else:
            api["model"] = st.text_input("Model", value=api["model"])
            price = None
        if price:
            api["pin"], api["pout"] = price
            st.caption("💲 %s：输入 $%.2f / 输出 $%.2f 每百万 tokens（OpenRouter 实时价格）；每次运行显示实际扣费。"
                       % (api["model"], price[0], price[1]) if ss.lang == "zh" else
                       "💲 %s: $%.2f in / $%.2f out per 1M tokens (live OpenRouter prices); each run shows the billed cost."
                       % (api["model"], price[0], price[1]))
        else:
            st.caption("⚠️ 无法获取价格（离线？），花费按 token 估算" if ss.lang == "zh" else "⚠️ Prices unavailable (offline?); cost estimated from tokens")
        if st.button("测试连接 / Test", width="stretch", disabled=not api["key"]):
            from core import backends
            saved = (config.API_KEY, config.MODEL)
            config.API_KEY, config.MODEL = api["key"], api["model"]
            try:
                txt, use = backends._live_call([{"role": "user", "content": "Reply with the single word OK."}], retries=2)
                api["ok"] = True
                st.success("✅ %s · %s tokens" % (txt.strip()[:20], use.get("prompt_tokens", 0) + use.get("completion_tokens", 0)))
            except Exception as e:
                api["ok"] = False
                st.error("❌ %s" % str(e)[:160])
            finally:
                config.API_KEY, config.MODEL = saved
        st.caption("设置后，“智能 / 路由”模式会实时调用模型；未设置时回放已保存的调查。")
L, CN = TXT[ss.lang], CAUSE[ss.lang]
with top[0]:
    st.markdown('<div class="gc-hero"><div><div class="gc-logo">Guba<span>Check</span></div>'
                '<div class="gc-sub">%s</div></div></div>' % L["tagline"], unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def data_sources():
    """Latest timestamp and size of every data source the tools read (frozen snapshot)."""
    def newest(rows, key):
        v = [str(r[key]) for r in rows if r.get(key)]
        return max(v) if v else None
    ds = store.load("daily_stats")
    posts_days = [r["date"] for v in ds.values() for r in v]
    n_posts = sum(r["posts"] for v in ds.values() for r in v)
    arts = store.load("articles")
    pr = store.load("prices")
    us = store.load("us_prices")
    ix = store.load("indices")
    anns = store.load("announcements")
    tl = store.load("toplist")
    tl = tl.get("rows", []) if isinstance(tl, dict) else tl
    jud = store.load("judgements")
    meta_p = os.path.join(config.DATA_DIR, "meta.json")
    meta = json.load(open(meta_p, encoding="utf-8")) if os.path.exists(meta_p) else {}
    newest_post = (meta.get("guba_latest_post") or "")[:16]
    return [
        ("💬", "股吧帖子（东方财富）", "Forum posts (Eastmoney Guba)",
         "最新帖 %s · 统计至 %s · %.1f 万帖" % (newest_post or "—", max(posts_days), n_posts / 1e4),
         "newest %s · stats to %s · %.2fM posts" % (newest_post or "—", max(posts_days), n_posts / 1e6)),
        ("📰", "股吧资讯文章", "Forum news articles", "%s · %d 篇" % (newest(arts, "time")[:16], len(arts)),
         "%s (%d)" % (newest(arts, "time")[:16], len(arts))),
        ("📈", "A 股日线（AKShare）", "A-share daily bars (AKShare)",
         "%s 收盘 · %d 只" % (max(b["date"] for v in pr.values() for b in v), len(pr)),
         "%s close (%d stocks incl. peers)" % (max(b["date"] for v in pr.values() for b in v), len(pr))),
        ("📊", "指数（沪深300 / 创业板指）", "Indices (CSI 300 / ChiNext)",
         "%s 收盘" % max(v[-1]["date"] for v in ix.values()), "%s close" % max(v[-1]["date"] for v in ix.values())),
        ("🌐", "美股同行（%s）" % "/".join(us), "US peers (%s)" % "/".join(us),
         "%s 美东收盘" % max(b["date"] for v in us.values() for b in v), "%s US close" % max(b["date"] for v in us.values() for b in v)),
        ("📄", "巨潮公告（CNINFO）", "Filings (CNINFO)", "%s · %d 条" % (newest(anns, "time")[:16], len(anns)),
         "%s (%d)" % (newest(anns, "time")[:16], len(anns))),
        ("🧾", "公告判断（LLM + RAG）", "Filing judgements (LLM + RAG)", "%d 条" % len(jud), "%d" % len(jud)),
        ("💰", "龙虎榜", "Exchange top list", "%s · %d 条" % (newest(tl, "date"), len(tl)), "%s (%d)" % (newest(tl, "date"), len(tl))),
    ]


def source_bar():
    zh = ss.lang == "zh"
    chips = "".join('<div class="gcs-c"><div class="gcs-n">%s %s</div><div class="gcs-v">%s</div></div>'
                    % (ic, nz if zh else ne, vz if zh else ve) for ic, nz, ne, vz, ve in data_sources())
    st.html("""
<style>
 .gcs{border:1px solid #e6e8eb;border-radius:12px;padding:8px 12px;background:#fbfcfd;margin-bottom:4px}
 .gcs-t{font-size:13px;margin-bottom:6px;color:#11181c} .gcs-t b{font-variant-numeric:tabular-nums;font-size:14px}
 .gcs-g{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:6px 12px}
 .gcs-c{font-size:12px;line-height:1.35} .gcs-n{color:#687076} .gcs-v{font-weight:600;color:#11181c}
</style>
<div class="gcs"><div class="gcs-t">🕒 %s <b id="gcs-clk">—</b> &nbsp;·&nbsp; %s</div><div class="gcs-g">%s</div></div>
<script>
 (function(){function t(){var e=document.getElementById('gcs-clk'); if(!e) return;
   e.textContent=new Date().toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false,year:'numeric',month:'2-digit',
   day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'});}
  t(); if(window.__gcsClock) clearInterval(window.__gcsClock); window.__gcsClock=setInterval(t,1000);})();
</script>""" % ("北京时间" if zh else "Beijing time", "已加载的数据（冻结快照）：" if zh else "Loaded data (frozen snapshot):", chips),
            unsafe_allow_javascript=True)



@st.cache_resource
def refresh_state():
    """One refresh at a time for the whole server; the worker thread writes here, the page reads."""
    return {"running": False, "steps": {}, "log": [], "done_at": None, "result": None}


def start_refresh():
    import threading
    from pipeline import refresh
    R = refresh_state()
    R.update(running=True, steps={k: (lab, "pending", "") for k, lab, _ in refresh.STEPS}, log=[], result=None)
    key, model = ss.api.get("key"), ss.api.get("model")

    def work():
        saved = (config.API_KEY, config.MODEL)
        if key:                                  # the judge step uses the user's key, never a stored one
            config.API_KEY, config.MODEL = key, model
        try:
            R["result"] = refresh.run(log=lambda m: R["log"].append(m),
                                      on_step=lambda k, lab, st_, msg: R["steps"].__setitem__(k, (lab, st_, msg)))
        finally:
            config.API_KEY, config.MODEL = saved
            store.reset()
            R.update(running=False, done_at=datetime.now().strftime("%H:%M:%S"))
    threading.Thread(target=work, daemon=True).start()


@st.fragment(run_every=2)
def refresh_panel():
    from pipeline import refresh
    R = refresh_state()
    zh = ss.lang == "zh"
    ok, why = refresh.ready()
    if st.button("🔄 " + ("更新数据" if zh else "Update data"), width="stretch", disabled=R["running"] or not ok,
                 help=(why if not ok else ("增量抓取各数据源并重算异动（约 10–30 分钟，后台运行）" if zh
                                         else "Incremental fetch of every source, then rebuild (10-30 min, in the background)"))):
        start_refresh()
        st.rerun(scope="fragment")
    if R["steps"] and (R["running"] or R["done_at"]):
        icon = {"pending": "⏳", "running": "🔄", "ok": "✅", "skipped": "⏭️", "failed": "❌"}
        with st.popover(("🔄 更新中…" if zh else "🔄 Updating…") if R["running"] else
                        ("✅ 已更新 %s" % R["done_at"] if zh else "✅ Updated %s" % R["done_at"]), width="stretch"):
            for lab, st_, msg in R["steps"].values():
                st.markdown("%s **%s** %s" % (icon.get(st_, "•"), lab, msg))
    if not R["running"] and R["done_at"] and ss.get("_refresh_seen") != R["done_at"]:
        ss["_refresh_seen"] = R["done_at"]
        st.cache_data.clear()
        st.rerun(scope="app")                   # reload every page with the new snapshot


bar_l, bar_r = st.columns([9, 1.4], vertical_alignment="center")
with bar_l:
    source_bar()
with bar_r:
    refresh_panel()
if "_goto" in ss:                       # navigation requested by a button on the previous run
    ss["nav"] = ss.pop("_goto")
ss.setdefault("hist", [])               # where the user has been: (page, stock, spike)


def remember_view(p):
    """Push the previous view when the view changed (not when it changed because of Back)."""
    where = (p, ss.get("stock"), ss.get("spike") if p == 2 else None)
    if p == 2 and not where[2]:
        return False                    # investigation page before it has picked a spike: not a view yet
    pushed = False
    if ss.get("_where") and where != ss["_where"] and not ss.get("_back"):
        ss.hist = (ss.hist + [ss["_where"]])[-20:]
        pushed = True
    ss["_back"] = False
    ss["_where"] = where
    return pushed


remember_view(ss.get("nav", 0))
nav_back, nav_bar = st.columns([1, 9], vertical_alignment="center")
with nav_bar:
    page = st.radio(" ", range(3), horizontal=True, format_func=lambda i: L["nav"][i],
                    label_visibility="collapsed", key="nav")
with nav_back:
    if st.button(L["back"], disabled=not ss.hist, width="stretch", key="back_btn"):
        prev = ss.hist.pop()
        ss["_goto"], ss["stock"], ss["spike"], ss["run"] = prev[0], prev[1], prev[2], None
        ss["_back"] = True
        st.rerun()

stocks = store.load("stocks")
PROFILES = json.load(open(os.path.join(ROOT, "data", "stock_profiles.json"), encoding="utf-8"))
TITLES_EN = json.load(open(os.path.join(ROOT, "data", "post_titles_en.json"), encoding="utf-8"))


def sname(code, lang=None):
    """Stock name in the UI language (English names for the English UI)."""
    lang = lang or ss.lang
    return PROFILES.get(code, {}).get("en", stocks[code]["name"]) if lang == "en" else stocks[code]["name"]


def name_tip(code, right=False):
    """Stock name with a bilingual hover card: position, market cap, data in this project, peers."""
    pr = PROFILES.get(code)
    if not pr:
        return sname(code)
    return ('<span class="gc-tip">%s<span class="gc-tipbox%s"><b>%s · %s</b> <span class="gc-tipg">%s / %s</span>'
            '<br>%s<hr>%s</span></span>' % (sname(code), " gc-tipr" if right else "", stocks[code]["name"], pr["en"],
                                            pr["group_zh"], pr["group_en"], pr["zh"], pr["en_text"]))
spikes = sorted((s for s in store.load("spikes") if not s.get("synthetic")),
                key=lambda s: (s["date"], s["spike_id"]))      # by date: spikes[-1] is the latest
daily = store.load("daily_stats")


def spike_label(x):
    return "🔥 %s %s · z %.1f" % (sname(x["stock"]), x["date"][5:], x["z_posts"])


def open_spike(sid):
    ss["_goto"], ss["spike"], ss["stock"], ss["run"] = 2, sid, sid[4:10], None
    st.rerun(scope="app")


def alerts():
    zh = ss.lang == "zh"
    last_day = max(x["date"] for x in spikes)
    recent = [x for x in spikes if x["date"] >= (pd.Timestamp(last_day) - pd.Timedelta(days=30)).strftime("%Y-%m-%d")][::-1]
    # toast: spikes this session has not seen yet (first visit: the latest day's spikes)
    if "seen_spikes" not in ss:
        ss.seen_spikes = {x["spike_id"] for x in spikes if x["date"] != last_day}
    for x in [x for x in spikes if x["spike_id"] not in ss.seen_spikes][-5:]:
        st.toast("%s %s%s" % ("新异动" if zh else "New spike", spike_label(x),
                               "（点右上角提醒查看）" if zh else " (open it from the alert, top right)"),
                 icon="🚨", duration="long")
    ss.seen_spikes |= {x["spike_id"] for x in spikes}
    c1, c2 = st.columns([1.25, 3], vertical_alignment="center")
    with c1.popover("🔔 %d" % len(recent), width="stretch"):
        st.caption("近 30 天异动（最新在上）" if zh else "Spikes, last 30 days (newest first)")
        for x in recent:
            if st.button(spike_label(x), key="bell_" + x["spike_id"], width="stretch"):
                open_spike(x["spike_id"])
    with c2:
        ticker(recent)


@st.fragment(run_every=4)
def ticker(recent):
    if not recent:
        return
    x = recent[int(time.time() // 4) % len(recent)]
    with st.container(key="gc-tick"):
        if st.button(spike_label(x), key="tick_" + x["spike_id"], width="stretch",
                     help="点击进入 AI 调查" if ss.lang == "zh" else "Open the AI investigation"):
            open_spike(x["spike_id"])


with alert_slot:
    alerts()


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
    latest = [x for x in spikes if x["date"] == last_day]
    for col, (v, lab) in zip(k, ((len(stocks), L["watched"]), (len(recent), L["spikes_m"]),
                                 ("%s %s" % (("、" if ss.lang == "zh" else ", ").join(sname(x["stock"]) for x in latest), last_day[5:]), L["last"]))):
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
                    '<div class="gc-card"><div class="gc-name">%s</div><div class="gc-code">%s</div>'
                    '<div style="margin-top:6px"><span class="%s">%.2f %s%.2f%%</span></div>'
                    '<div class="gc-gauge">%s %d / 100 &nbsp; <span class="gc-badge %s">%s</span></div>'
                    '<div class="gc-bar"><div class="b" style="width:%d%%"></div><div class="s" style="width:%d%%"></div></div>'
                    '<div class="gc-gauge">%s %d%% · %s %d%%</div></div>'
                    % (name_tip(code, right=code in codes[row + 3:row + 5]), code, "gc-up" if chg >= 0 else "gc-down", last["close"],
                       "+" if chg >= 0 else "", chg, L["heat"], heat, "gc-hot" if hot else "gc-calm",
                       L["spike"] if hot else L["calm"], int(100 * bull), 100 - int(100 * bull),
                       L["bulls"], int(100 * bull), L["bears"], 100 - int(100 * bull)), unsafe_allow_html=True)
                if st.button(L["open"], key="open_" + code, width="stretch"):
                    go_to(1, stock=code, spike=None)


# ================================================================ STOCK
def page_stock():
    code = st.selectbox(" ", list(stocks), index=list(stocks).index(ss.stock), label_visibility="collapsed",
                        format_func=lambda c, lg=ss.lang: "%s  %s" % (sname(c, lg), c))
    ss.stock = code
    if code in PROFILES:
        st.markdown('<div class="gc-gauge">ⓘ %s · %s</div>' % (name_tip(code), PROFILES[code]["group_en" if ss.lang == "en" else "group_zh"]),
                    unsafe_allow_html=True)
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
    st.plotly_chart(fig, width="stretch")
    st.markdown("#### " + L["pick_spike"])
    gold = gold_labels()
    cols = st.columns(4)
    for i, s in enumerate(reversed(sp)):
        with cols[i % 4]:
            st.markdown('<div class="gc-card"><b>🔥 %s</b><div class="gc-gauge">%d posts · z %.1f · %s %d%%</div></div>'
                        % (s["date"], s["posts"], s["z_posts"], L["bulls"], 100 * s["bull_share"]), unsafe_allow_html=True)
            if st.button(L["investigate"], key="inv_" + s["spike_id"], width="stretch"):
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
    st.plotly_chart(fig, width="stretch", key=key)


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


def stop_text(inv, primary, rec=None):
    if rec is not None and (rec.get("error") or (not inv.get("order") and not rec.get("tool_calls"))):
        why = rec.get("error") or rec.get("reason") or ""
        return ("⚠️ AI 未能完成调查：%s" % why[:200]) if ss.lang == "zh" else ("⚠️ The AI did not complete the investigation: %s" % why[:200])
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
            st.dataframe(pd.DataFrame(out["evidence"]).head(6), hide_index=True, width="stretch")


HZ = ["1", "2", "3", "5", "10", "20"]


def past_rows(s, cause):
    """Earlier spikes (strictly before this one) with the same cause: same stock, and all stocks."""
    p = os.path.join(ROOT, "results", "cause_backtest_rows_gold.json")
    rows = json.load(open(p)) if os.path.exists(p) else []
    earlier = [r for r in rows if r["spike_id"][-8:] < s["date"].replace("-", "") and r["cause"] == cause]
    return [r for r in earlier if r["spike_id"][4:10] == s["stock"]], earlier


def suggestion(same, allc):
    """Rule-based stance from history: needs >= 3 cases; uses D+5 excess."""
    zh = ss.lang == "zh"
    base, scope = (same, "本股" if zh else "this stock") if len(same) >= 3 else (allc, "全部股票" if zh else "all stocks")
    if len(base) < 3:
        return "⚪", ("观望：同类历史异动不足 3 次，无法给出有依据的建议" if zh else "Wait: fewer than 3 similar past spikes"), base, scope
    x = [r["excess"]["5"] for r in base if "5" in r["excess"]]
    m, w = sum(x) / len(x), sum(v > 0 for v in x) / len(x)
    if m > 1 and w >= 0.6:
        return "🔴", ("偏多关注：%s同类异动后 5 日平均超额 %+.1f%%，胜率 %.0f%%（n=%d）" if zh else
                     "Lean positive: %s similar spikes, D+5 mean excess %+.1f%%, win %.0f%% (n=%d)") % (scope, m, 100 * w, len(x)), base, scope
    if m < -1 and w <= 0.4:
        return "🟢", ("回避 / 减仓：%s同类异动后 5 日平均超额 %+.1f%%，胜率 %.0f%%（n=%d）" if zh else
                     "Avoid / reduce: %s similar spikes, D+5 mean excess %+.1f%%, win %.0f%% (n=%d)") % (scope, m, 100 * w, len(x)), base, scope
    return "⚪", ("观望：%s同类异动后 5 日平均超额 %+.1f%%，胜率 %.0f%%（n=%d），方向不明确" if zh else
                 "Wait: %s similar spikes, D+5 mean excess %+.1f%%, win %.0f%% (n=%d), no clear edge") % (scope, m, 100 * w, len(x)), base, scope


def history_table(s, cause):
    zh = ss.lang == "zh"
    same, allc = past_rows(s, cause)
    st.markdown("**%s**" % ("📜 %s 过去的同类异动（原因：%s）——如果当时次日开盘买入" % (sname(s["stock"]), cname(cause)) if zh
                            else "📜 Earlier spikes of %s with the same cause (%s) — bought at the next open" % (sname(s["stock"]), cname(cause))))
    def table(rows, with_stock):
        out = []
        for r in rows:
            d = {"异动日期" if zh else "spike": r["spike_id"][-8:-4] + "-" + r["spike_id"][-4:-2] + "-" + r["spike_id"][-2:]}
            if with_stock:
                d["股票" if zh else "stock"] = sname(r["spike_id"][4:10])
            for h in HZ:
                d["D+" + h] = r["returns"].get(h)
            out.append(d)
        df = pd.DataFrame(out)
        if not df.empty:
            df = df.sort_values(df.columns[0], ignore_index=True)
            ex = pd.DataFrame([{"D+" + h: r["excess"].get(h) for h in HZ} for r in rows])
            avg = {c: round(df[c].mean(), 2) for c in df.columns if c.startswith("D+")}
            exm = {c: round(ex[c].mean(), 2) for c in ex.columns}
            win = {c: "%.0f%%" % (100 * (df[c] > 0).mean()) for c in df.columns if c.startswith("D+")}
            first = df.columns[0]
            df = pd.concat([df, pd.DataFrame([dict({first: "平均收益 %" if zh else "mean %"}, **avg),
                                              dict({first: "平均超额 %（vs 沪深300）" if zh else "mean excess % (vs CSI 300)"}, **exm),
                                              dict({first: "胜率" if zh else "win rate"}, **win)])], ignore_index=True)
            df = df.map(lambda v: "" if v is None or v != v else ("%+.2f" % v if isinstance(v, float) else str(v)))
        return df
    if same:
        st.dataframe(table(same, False), hide_index=True, width="stretch")
    else:
        st.caption("本股在此之前没有同类异动" if zh else "No earlier spike of this stock with this cause")
    with st.expander(("所有股票的同类异动（n=%d）" if zh else "Same cause, all stocks (n=%d)") % len(allc), expanded=not same):
        if allc:
            st.dataframe(table(allc, True), hide_index=True, width="stretch")
    st.caption("收益已扣除佣金、过户费和印花税；只使用本次异动之前的数据；历史异动的原因来自人工标注。" if zh else
               "Net of fees; only spikes before this one; causes of earlier spikes are my hand labels.")
    icon, text, base, scope = suggestion(same, allc)
    st.markdown('<div class="gc-card"><div class="gc-kpil">%s</div><div class="gc-verdict" style="font-size:1.1rem">%s %s</div>'
                '<div class="gc-gauge">%s</div></div>' % ("规则建议" if zh else "Rule-based suggestion", icon, text,
                                                          "基于历史统计的研究参考，不构成投资建议" if zh else "Research reference from history, not investment advice"),
                unsafe_allow_html=True)
    return same, allc


def llm_advice(s, primary, outs, same, allc):
    """API + RAG: the model writes a suggestion from the cause, evidence, history table and retrieved filings."""
    from core import backends
    from pipeline import judge, rag
    zh = ss.lang == "zh"
    anns = [a for a in judge.load_announcements() if a["stock"] == s["stock"] and a["time"] < s["onset"] and not a["procedural"]]
    rag_txt = ""
    if anns:
        latest = max(anns, key=lambda a: a["time"])
        forced, top = rag.retrieve(dict(latest, time=s["onset"]), judge.text_of(latest["ann_id"]))
        rag_txt = "\n".join(["[%s] %s：%s" % (d["time"][:10], d["title"], rag.clean(judge.text_of(d["ann_id"], 600))[:400]) for _, d in forced]
                            + ["[%s] %s：%s" % (c["time"][:10], c["title"], c["text"][:300]) for c in top[:3]])
    ev = "\n".join("%s %s：%s" % (c, o["verdict"], o["note"]) for c, o in outs)
    hist = lambda rows: "; ".join("%s D+5 %s%%" % (r["spike_id"][-8:], r["returns"].get("5")) for r in rows[-8:]) or "none"
    prompt = ("你是A股研究助手。根据下面的信息，为个人投资者写一段简短的研究参考（不超过200字）："
              "1) 这次股吧异动的主要原因；2) 历史上同类异动之后的走势说明了什么（注意样本量）；"
              "3) 偏多关注 / 观望 / 回避 三选一，并说明理由；4) 主要风险。只依据给出的信息，不要编造。最后注明“不构成投资建议”。\n\n"
              "股票：%s %s，异动日 %s，帖子 %d（z=%.1f），看多比例 %.0f%%\n主要原因：%s\n检验结果：\n%s\n"
              "本股同类历史异动：%s\n全部股票同类历史异动：%s\n公司历史资料（RAG，均早于本次异动）：\n%s"
              % (stocks[s["stock"]]["name"], s["stock"], s["date"], s["posts"], s["z_posts"], 100 * s["bull_share"],
                 cname(primary), ev, hist(same), hist(allc), rag_txt or "无"))
    if not zh:
        prompt += "\n\nAnswer in English."
    api = ss.api
    saved = (config.API_KEY, config.MODEL)
    config.API_KEY, config.MODEL = api["key"], api["model"]
    try:
        text, use = backends._live_call([{"role": "user", "content": prompt}], retries=3)
    finally:
        config.API_KEY, config.MODEL = saved
    cost = use["cost"] if use.get("cost") is not None else \
        use.get("prompt_tokens", 0) / 1e6 * api["pin"] + use.get("completion_tokens", 0) / 1e6 * api["pout"]
    return text, cost


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
    st.plotly_chart(fig, width="stretch")
    st.caption("n = %d%s" % (g["n"], "　⚠️ " + L["n_small"] if g["n"] < 5 else ""))


def save_feedback(sid, agree, cause, concluded):
    with open(os.path.join(ROOT, "results", "user_feedback.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"spike_id": sid, "agree": agree, "user_cause": cause, "system_cause": concluded,
                             "time": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")


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
        if a.button(L["yes"], key="fb_y", width="stretch"):
            save_feedback(s["spike_id"], True, primary, primary)
            st.toast(L["thanks"])
        with b.popover(L["no"], width="stretch"):
            pick = st.radio(L["your_cause"], list(CN), format_func=cname, key="fb_pick")
            if st.button("OK", key="fb_ok"):
                save_feedback(s["spike_id"], False, pick, primary)
                st.toast(L["thanks"])
    with c2:
        same, allc = history_table(s, primary)
        if ss.api.get("key"):
            if st.button("🧠 " + ("让 AI 结合历史和公司公告（RAG）写建议" if ss.lang == "zh" else "Ask the AI for a suggestion (history + RAG)"),
                         width="stretch", key="advice_" + s["spike_id"]):
                with st.spinner("🧠 …"):
                    try:
                        text, cost = llm_advice(s, primary, outs, same, allc)
                        ss["advtxt_" + s["spike_id"]] = (text, cost)
                    except Exception as e:
                        st.error(str(e)[:200])
            if ss.get("advtxt_" + s["spike_id"]):
                text, cost = ss["advtxt_" + s["spike_id"]]
                st.info(text)
                st.caption("US$%.5f" % cost)
        else:
            st.caption("在右上角 ⚙️ API 设置 key 后，可让 AI 结合公司公告（RAG）写建议" if ss.lang == "zh"
                       else "Set a key in ⚙️ API (top right) to get an AI-written suggestion with RAG")


def recommended(runs, gold):
    """Spikes a saved run explains and that match my label (for quick demos)."""
    for arm in ("agent", "routing", "keyword", "exhaustive"):
        if arm in runs:
            good = [sid for sid, r in runs[arm].items() if r.get("primary") not in (None, "H") and r.get("primary") == gold.get(sid)]
            if good:
                return arm, sorted(good, key=lambda i: runs[arm][i]["investigation"].get("calls", 9))[:8]
    return None, []


def live_investigation(sid, arm, area):
    """Run the real agent now, drawing each step as it happens."""
    from core.agent import run_case
    api = ss.api
    saved = (config.BACKEND, config.API_KEY, config.MODEL, config.PRICE_IN, config.PRICE_OUT)
    config.BACKEND, config.API_KEY, config.MODEL, config.PRICE_IN, config.PRICE_OUT = \
        "live", api["key"], api["model"], api["pin"], api["pout"]
    n = {"step": 0}

    def on_event(kind, data):
        with area:
            if kind == "move":
                n["step"] += 1
                if data.get("thought"):
                    st.markdown('<div class="gc-post">💭 <b>%s %d</b>　%s</div>' % ("第" if ss.lang == "zh" else "Step", n["step"],
                                                                                 str(data["thought"])[:300]), unsafe_allow_html=True)
            elif kind == "result":
                t, r = data["tool"], data["result"]
                if t == "get_spike":
                    st.caption("📥 " + L["reading"].format(n=r.get("posts", "?")))
                elif t == "score_causes":
                    pri = r.get("posterior", {})
                    st.markdown("**%s**" % L["priors"])
                    fig = go.Figure(go.Bar(y=[cname(c) for c in pri], x=list(pri.values()), orientation="h",
                                           marker_color=[COLORS[c] for c in pri],
                                           text=["%.0f%%" % (100 * v) for v in pri.values()], textposition="outside"))
                    fig.update_layout(height=240, margin=dict(l=10, r=40, t=10, b=10), plot_bgcolor="white",
                                      xaxis=dict(tickformat=".0%", range=[0, 1]))
                    st.plotly_chart(fig, width="stretch", key="live_pri_%d" % n["step"])
                elif t.startswith("check_"):
                    step_card(t[-1], r)
                elif t == "revise_scores":
                    st.info("🔄 %s：%s" % ("AI 根据新证据调整了判断" if ss.lang == "zh" else "The AI revised its view",
                                          data["args"].get("reason", "")))
    try:
        with st.spinner("🧠 " + (L["live"] + " · " + api["model"])):
            rec = run_case(sid, arm=arm, on_event=on_event)
    finally:
        config.BACKEND, config.API_KEY, config.MODEL, config.PRICE_IN, config.PRICE_OUT = saved
    return rec


def page_investigate():
    runs = saved_runs()
    gold = gold_labels()
    rec_arm, rec_ids = recommended(runs, gold)
    if rec_ids:
        st.markdown("**⭐ %s**" % ("推荐案例（系统能解释、且与人工标注一致）" if ss.lang == "zh" else "Suggested cases (explained, matching my label)"))
        cols = st.columns(4)
        for i, rid in enumerate(rec_ids):
            if cols[i % 4].button("%s %s · %s" % (sname(rid[4:10]), rid[-4:], CN[gold[rid]][1] + CN[gold[rid]][0]),
                                  key="rec_" + rid, width="stretch"):
                ss.spike, ss.run = rid, None
                st.rerun()
    sid = ss.spike or spikes[-1]["spike_id"]
    opts = [x["spike_id"] for x in spikes]
    sid = st.selectbox(" ", opts, index=opts.index(sid), label_visibility="collapsed",
                       format_func=lambda i, lg=ss.lang: "🔥 %s  %s  %s" % (sname(i[4:10], lg), i[4:10], i[-8:]))
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
    live_ok = bool(ss.api["key"]) and mode in ("agent", "routing")
    if mode in ("agent", "routing"):
        if live_ok:
            st.caption("🟢 %s：%s" % ("将实时调用" if ss.lang == "zh" else "Live call to", ss.api["model"]))
        else:
            st.caption("⚪ %s" % ("未设置 API key（右上角 ⚙️ API）：回放已保存的调查过程" if ss.lang == "zh"
                                  else "No API key (⚙️ API, top right): replaying a saved investigation"))
    if st.button("▶ " + L["start"], type="primary"):
        ss.run = {"mode": mode, "sid": sid, "live": live_ok}
    if not ss.get("run") or ss.run.get("sid") != sid or ss.run.get("mode") != mode:
        return
    st.markdown("**%s**" % L["clues"])
    for p in top[:6]:
        words = [w for w, _ in clue_words(p["title"])]
        en = TITLES_EN.get(str(p["post_id"])) if ss.lang == "en" else None
        st.markdown('<div class="gc-post">%s %s%s</div>' % ("📰" if p.get("post_type") == 20 else "💬",
                                                            highlight(p["title"], words),
                                                            '<div class="gc-en">%s</div>' % en if en else ""),
                    unsafe_allow_html=True)
    # ---- live run (once per click), saved replay, or scripted
    if ss.run.get("live") and not ss.run.get("rec"):
        area = st.container()
        try:
            ss.run["rec"] = live_investigation(sid, mode, area)
            ss.run["shown"] = True
        except Exception as e:
            st.error("❌ %s" % str(e)[:300])
            return
        rec = ss.run["rec"]
        outs = [(c, causes.CAUSE_TOOLS[c](sid)) for c in rec.get("investigation", {}).get("order", [])]
        inv = rec.get("investigation", {})
        if inv.get("history"):
            st.markdown("**%s**" % L["posterior"])
            posterior_chart(inv["history"], key="pc_live")
        st.success("💰 %s %d tokens · US$%.5f · %d %s" % ("本次调用" if ss.lang == "zh" else "This run", rec["tokens_in"] + rec["tokens_out"],
                                                       rec["cost_usd"], inv.get("calls", 0), "项检验" if ss.lang == "zh" else "tests"))
        st.info("⏹️ " + stop_text(inv, rec.get("primary") or "H", rec))
        if rec.get("raw_trace"):
            with st.expander("🧾 " + ("模型原始回复（排查用）" if ss.lang == "zh" else "raw model replies (diagnostics)")):
                st.json(rec["raw_trace"])
        conclusion_block(s, rec.get("primary") or "H", inv.get("posterior", {}), outs)
        return
    rec = ss.run.get("rec")
    if rec is None:
        if mode in runs and sid in runs[mode]:
            rec = runs[mode][sid]
        else:
            from core.agent import run_case
            rec = run_case(sid, arm="keyword" if mode in ("agent", "routing") else mode)
            if mode in ("agent", "routing"):
                st.caption("🛈 %s" % ("没有已保存的 AI 调查，显示关键词规则的结果" if ss.lang == "zh" else "No saved AI run: showing the keyword arm"))
    inv = rec.get("investigation", {})
    animate = not ss.run.get("shown")
    pause = (lambda t: time.sleep(t)) if animate else (lambda t: None)
    hist = inv.get("history", [])
    if hist:
        pri = hist[0]["posterior"]
        st.markdown("**%s**" % L["priors"])
        fig = go.Figure(go.Bar(y=[cname(c) for c in pri], x=list(pri.values()), orientation="h",
                               marker_color=[COLORS[c] for c in pri], text=["%.0f%%" % (100 * v) for v in pri.values()],
                               textposition="outside"))
        fig.update_layout(height=260, margin=dict(l=10, r=40, t=10, b=10), xaxis=dict(tickformat=".0%", range=[0, 1]),
                          plot_bgcolor="white")
        st.plotly_chart(fig, width="stretch")
    outs = []
    chart = st.empty()
    for n, c in enumerate(inv.get("order", []), 1):
        with st.spinner(L["testing"] + cname(c)):
            pause(0.6)
            out = causes.CAUSE_TOOLS[c](sid)
        outs.append((c, out))
        step_card(c, out)
        with chart.container():
            st.markdown("**%s**" % L["posterior"])
            posterior_chart(hist[:n + 1], key="pc_%d" % n)
    primary = rec.get("primary") or "H"
    st.info("⏹️ " + stop_text(inv, primary, rec))
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
                          key="m_" + c, disabled=done or inv.should_stop(), width="stretch"):
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


[page_radar, page_stock, page_investigate][page]()

if remember_view(page):                 # the page itself changed the view (e.g. picked another spike)
    st.rerun()                          # redraw so the back button is enabled
