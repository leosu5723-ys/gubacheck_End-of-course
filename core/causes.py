"""
GubaCheck - THE SEVEN CAUSE TOOLS (fixed interfaces, RULES.md 0.2)
=========================================================================
Every tool: input spike_id; output
    {cause, verdict: PASS|PARTIAL|FAIL, metrics, evidence[], timing, cost, note}
The verdict is computed HERE, by code, from z-scores and timestamps; the
model never decides whether a test passed. All abnormality tests use
z-scores against the series' own previous 120 trading days.

  A company official   filings (and board-secretary replies) in [D-3, onset)
  B media / rumour     company-specific articles in [onset-72h, onset): count z >= 2
                       against the stock's own rolling 3-day counts
  C sector             peer returns on D: share of peers with |z| >= 2, same sign
  D overseas           US peers on the last US session before D's open, AND the
                       stock's own opening gap z on D (timing: US first)
  E market             CSI 300 / ChiNext return z on D
  F policy / macro     policy-keyword articles before onset AND (C or E >= PARTIAL)
  G money / structure  top list (龙虎榜) on D; |net buy| / turnover vs the
                       market-wide 95th percentile (exempt from timing)
=========================================================================
"""
import re
import statistics
from datetime import date, datetime, timedelta

from core import config, store

POLICY = re.compile(r"政策|国务院|证监会|发改委|工信部|央行|人民银行|降准|降息|规划|关税|补贴|部委|印发|"
                    r"条例|监管|国常会|政治局|十五五|指导意见|通知")
MARKET_WRAP = re.compile(r"资金流向|主力|龙虎榜|融资|复盘|收评|午评|早盘|盘前|涨停|跌停|净流入|净流出|大宗交易|"
                         r"成交额|成交量|排行|日报|榜单|异动|个股")
_CACHE = {}


def _z(hist, value):
    h = [x for x in hist if x is not None][-config.Z_WINDOW:]
    if len(h) < config.Z_MIN_OBS or value is None:
        return None
    sd = statistics.pstdev(h)
    return round((value - statistics.mean(h)) / sd, 2) if sd > 0 else None


def _bars(code):
    if code not in _CACHE:
        _CACHE[code] = sorted(store.load("prices").get(code, []), key=lambda b: b["date"])
    return _CACHE[code]


def _ret_z(code, day, field="ret"):
    """z of the stock's daily return (field='ret') or opening gap ('gap') on day."""
    bars = _bars(code)
    idx = next((i for i, b in enumerate(bars) if b["date"] == day), None)
    if idx is None:
        return None, None

    def val(b):
        if not b.get("prev_close"):
            return None
        return 100 * ((b["close"] if field == "ret" else b["open"]) / b["prev_close"] - 1)
    v = val(bars[idx])
    return _z([val(b) for b in bars[max(0, idx - config.Z_WINDOW):idx]], v), (round(v, 2) if v is not None else None)


def _spike(spike_id):
    s = store.spike(spike_id)
    if s is None:
        raise KeyError("no spike %s" % spike_id)
    return s


def _name_terms(code):
    meta = store.stock(code) or {}
    return [meta.get("name", "")] + meta.get("aliases", [])


def _out(cause, verdict, metrics, evidence, timing, note, cost_tokens=0):
    return {"cause": cause, "verdict": verdict, "metrics": metrics, "evidence": evidence[:5],
            "timing": timing, "cost": {"llm_tokens": cost_tokens}, "note": note}


def _direction(s):
    """+1 if the spike day's own return was up, -1 if down (None if unknown)."""
    z, v = _ret_z(s["stock"], s["date"])
    return None if v is None else (1 if v >= 0 else -1)


# ---------------------------------------------------------------------- A
def check_A(spike_id):
    s = _spike(spike_id)
    lo = (date.fromisoformat(s["date"]) - timedelta(days=3)).isoformat()
    jud = store.load("judgements")
    sign = _direction(s)
    before, after = [], []
    for a in store.load("announcements"):
        if a["stock"] != s["stock"] or a["procedural"] or not (lo <= a["time"][:10] <= s["date"]):
            continue
        j = jud.get(a["ann_id"], {"label": "neutral", "reason": ""})
        item = {"id": a["ann_id"], "time": a["time"], "title": a["title"], "label": j["label"],
                "reason": j.get("reason", "")[:120]}
        (before if a["time"] < s["onset"] else after).append(item)
    for q in store.load("irm"):
        if q.get("stock") != s["stock"]:
            continue
        t = q.get("a_time") or ""
        if lo <= t[:10] <= s["date"]:
            item = {"id": "irm", "time": t, "title": "董秘回复: " + q.get("question", "")[:40],
                    "label": "reply", "reason": q.get("answer", "")[:120]}
            (before if t < s["onset"] else after).append(item)
    want = {1: "bullish", -1: "bearish"}.get(sign)
    directional = [e for e in before if e["label"] in ("bullish", "bearish")]
    if any(e["label"] == want for e in directional):
        verdict = "PASS"
    elif before or after:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    return _out("A", verdict, {"filings_before_onset": len(before), "filings_after_onset": len(after),
                               "spike_day_direction": sign},
                [e for e in directional if e["label"] == want] + before + after,
                {"onset": s["onset"], "rule": "evidence time < onset"},
                "official evidence in the spike's direction before the forum surge" if verdict == "PASS" else
                "filings exist but after onset, neutral, or against the move" if verdict == "PARTIAL" else
                "no filing or reply in [D-3, D]")


# ---------------------------------------------------------------------- B
def check_B(spike_id):
    """PASS when company-specific articles in the 72 h before onset are abnormal
    (z >= 2) against the same stock's rolling 3-day article counts over the
    previous 120 days; PARTIAL when articles exist but are not abnormal, or only
    appear after onset; FAIL when there are none."""
    s = _spike(spike_id)
    start = (datetime.fromisoformat(s["onset"]) - timedelta(hours=72)).isoformat(sep=" ")
    names = _name_terms(s["stock"])
    rel = [a for a in store.load("articles") if a["stock"] == s["stock"] and any(n and n in a["title"] for n in names)
           and not MARKET_WRAP.search(a["title"]) and not POLICY.search(a["title"])]
    before = [a for a in rel if start <= a["time"] < s["onset"]]
    after = [a for a in rel if s["onset"] <= a["time"] <= s["date"] + " 23:59:59"]
    daily = store.load("article_daily_counts").get(s["stock"], {})
    d0 = date.fromisoformat(s["onset"][:10])
    hist = []
    for k in range(4, 4 + config.Z_WINDOW):         # rolling 3-day sums ending before the window
        end = d0 - timedelta(days=k)
        hist.append(sum(daily.get((end - timedelta(days=j)).isoformat(), 0) for j in range(3)))
    z = _z(hist, len(before))
    if before and z is not None and z >= config.Z_ABNORMAL:
        verdict = "PASS"
    elif before or after:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    ev = [{"id": a["post_id"], "time": a["time"], "title": a["title"], "reads": a["reads"]}
          for a in sorted(before, key=lambda a: -a["reads"]) + after]
    return _out("B", verdict, {"articles_before_onset": len(before), "articles_after_onset": len(after),
                               "article_count_z": z}, ev,
                {"onset": s["onset"], "window_start": start, "rule": "article time < onset"},
                "an abnormal burst of company-specific coverage preceded the surge" if verdict == "PASS" else
                "coverage exists but is ordinary, or came after the surge began" if verdict == "PARTIAL"
                else "no company-specific media article")


# ---------------------------------------------------------------------- C
def check_C(spike_id):
    s = _spike(spike_id)
    group = next((g for g in store.load("peers").values() if s["stock"] in g["members"]), None)
    peers = [c for c in (group["members"] + group["extra_peers"]) if c != s["stock"]] if group else []
    own_z, own_v = _ret_z(s["stock"], s["date"])
    sign = 1 if (own_v or 0) >= 0 else -1
    rows = []
    for p in peers:
        z, v = _ret_z(p, s["date"])
        rows.append({"id": p, "z": z, "ret_pct": v})
    valid = [r for r in rows if r["z"] is not None]
    same = [r for r in valid if abs(r["z"]) >= config.Z_ABNORMAL and r["z"] * sign > 0]
    share = len(same) / len(valid) if valid else 0
    verdict = "PASS" if valid and share > 0.5 else ("PARTIAL" if same else "FAIL")
    return _out("C", verdict, {"own_return_z": own_z, "own_return_pct": own_v, "peers_tested": len(valid),
                               "peers_abnormal_same_sign": len(same), "share": round(share, 2)},
                sorted(rows, key=lambda r: -abs(r["z"] or 0)), {"rule": "same trading day"},
                "most peers moved abnormally the same way" if verdict == "PASS" else
                "some peers moved abnormally" if verdict == "PARTIAL" else "peers were normal")


# ---------------------------------------------------------------------- D
def check_D(spike_id):
    s = _spike(spike_id)
    group = next((g for g in store.load("peers").values() if s["stock"] in g["members"]), None)
    tickers = group["us_peers"] if group else []
    if not tickers:
        return _out("D", "FAIL", {"us_peers": 0}, [], {"rule": "US session before A-share open"},
                    "no US peer defined for this stock's product line")
    gap_z, gap_v = _ret_z(s["stock"], s["date"], "gap")
    us = store.load("us_prices")
    rows = []
    for t in tickers:
        series = us.get(t, [])
        prev = [r for r in series if r["date"] < s["date"]]          # last US session that closed before D's open
        if len(prev) < config.Z_MIN_OBS + 1:
            continue
        last = prev[-1]
        z = _z([r["ret"] for r in prev[:-1]], last["ret"])
        rows.append({"id": t, "us_date": last["date"], "ret_pct": last["ret"], "z": z})
    ab = [r for r in rows if r["z"] is not None and abs(r["z"]) >= config.Z_ABNORMAL]
    aligned = [r for r in ab if gap_z is not None and gap_z * r["z"] > 0 and abs(gap_z) >= config.Z_ABNORMAL]
    verdict = "PASS" if aligned else ("PARTIAL" if ab else "FAIL")
    return _out("D", verdict, {"opening_gap_z": gap_z, "opening_gap_pct": gap_v, "us_abnormal": len(ab)},
                sorted(rows, key=lambda r: -abs(r["z"] or 0)),
                {"rule": "US close (previous US session) precedes the A-share open; stock must gap at the open"},
                "US peers moved abnormally overnight and the stock gapped the same way at the open" if verdict == "PASS"
                else "US peers moved abnormally but the stock did not gap at the open" if verdict == "PARTIAL"
                else "no abnormal US peer move on the previous session")


# ---------------------------------------------------------------------- E
def _index_z(day):
    out = {}
    for name, rows in store.load("indices").items():
        rows = sorted(rows, key=lambda r: r["date"])
        i = next((k for k, r in enumerate(rows) if r["date"] == day), None)
        if not i:
            continue
        rets = [100 * (rows[k]["close"] / rows[k - 1]["close"] - 1) for k in range(1, len(rows))]
        out[name] = {"ret_pct": round(rets[i - 1], 2), "z": _z(rets[max(0, i - 1 - config.Z_WINDOW):i - 1], rets[i - 1])}
    return out


def check_E(spike_id):
    s = _spike(spike_id)
    idx = _index_z(s["date"])
    zmax = max((abs(v["z"]) for v in idx.values() if v["z"] is not None), default=0)
    verdict = "PASS" if zmax >= config.Z_ABNORMAL else ("PARTIAL" if zmax >= config.Z_PARTIAL else "FAIL")
    return _out("E", verdict, {"max_abs_index_z": zmax}, [dict(id=k, **v) for k, v in idx.items()],
                {"rule": "same trading day"},
                "the whole market moved abnormally" if verdict == "PASS" else
                "the market moved noticeably" if verdict == "PARTIAL" else "the market was normal")


# ---------------------------------------------------------------------- F
def check_F(spike_id):
    s = _spike(spike_id)
    start = (datetime.fromisoformat(s["onset"]) - timedelta(hours=72)).isoformat(sep=" ")
    pol = [a for a in store.load("articles") if a["stock"] == s["stock"] and POLICY.search(a["title"])
           and start <= a["time"] < s["onset"]]
    breadth = {"C": check_C(spike_id)["verdict"], "E": check_E(spike_id)["verdict"]}
    wide = any(v in ("PASS", "PARTIAL") for v in breadth.values())
    verdict = "PASS" if pol and wide else ("PARTIAL" if pol else "FAIL")
    return _out("F", verdict, {"policy_articles_before_onset": len(pol), "breadth": breadth},
                [{"id": a["post_id"], "time": a["time"], "title": a["title"]} for a in sorted(pol, key=lambda a: -a["reads"])],
                {"onset": s["onset"], "rule": "policy article time < onset"},
                "policy news preceded the surge and the move was broad" if verdict == "PASS" else
                "policy news, but the move was not broad" if verdict == "PARTIAL" else "no policy news before the surge")


# ---------------------------------------------------------------------- G
def check_G(spike_id):
    s = _spike(spike_id)
    tl = store.load("toplist")
    rows = [r for r in tl["rows"] if r["stock"] == s["stock"] and r["date"] == s["date"]]
    dist = tl["market_abs_netbuy_ratio_sorted"]
    p95 = dist[int(0.95 * (len(dist) - 1))] if dist else None
    best = max(rows, key=lambda r: abs(r["net_buy"]) / r["turnover"] if r["turnover"] else 0) if rows else None
    ratio = abs(best["net_buy"]) / best["turnover"] if best and best["turnover"] else None
    verdict = "PASS" if ratio is not None and p95 is not None and ratio >= p95 else ("PARTIAL" if rows else "FAIL")
    return _out("G", verdict, {"on_top_list": bool(rows), "abs_netbuy_to_turnover": round(ratio, 3) if ratio else None,
                               "market_p95": round(p95, 3) if p95 else None},
                [{"id": "toplist", "time": r["date"], "title": r["reason"][:60], "net_buy": r["net_buy"],
                  "note": r["note"][:40]} for r in rows],
                {"rule": "exempt: the top list is published after the close"},
                "on the top list with an extreme one-sided net buy/sell" if verdict == "PASS" else
                "on the top list, ordinary net flow" if verdict == "PARTIAL" else "not on the top list")


CAUSE_TOOLS = {"A": check_A, "B": check_B, "C": check_C, "D": check_D, "E": check_E, "F": check_F, "G": check_G}
