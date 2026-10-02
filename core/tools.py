"""
GubaCheck - TOOL LAYER
=========================================================================
Six tools. Five read one thing from the snapshot and return one fact; the
sixth (place_paper_order) is the only action that changes anything, and
it sits behind the autonomy gate.

Each tool's comment block has the same five parts:
    WHAT IT DOES   one sentence, in investing language
    READS          which snapshot table
    RETURNS        the exact shape
    RETURNS NONE   when, and what that MEANS for the decision
    WATCH OUT      the mistake the tool exists to prevent

The DESCRIPTORS at the bottom are what the model reads; prompt.py turns
them into the system prompt. Editing a descriptor changes agent
behaviour, which is why descriptor v1 vs v2 is measured in EVALS.md.

Poka-yoke (make the wrong call impossible, not just documented):
  * search tools refuse windows wider than SEARCH_WINDOW_MAX_DAYS, so an
    old announcement cannot be passed off as fresh evidence;
  * place_paper_order takes no quantity - size is set by code - and it
    needs an evidence_id that guardrails.check_order verifies.
=========================================================================
"""
from datetime import date

from core import config, market, paper_broker, store
from core.guardrails import screen_text


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _window_error(date_from, date_to):
    try:
        span = _days(date_from, date_to)
    except ValueError:
        return {"error": "dates must be YYYY-MM-DD"}
    if span < 0:
        return {"error": "date_from is after date_to"}
    if span > config.SEARCH_WINDOW_MAX_DAYS:
        return {"error": "window of %d days exceeds the %d-day limit; narrow it"
                         % (span, config.SEARCH_WINDOW_MAX_DAYS)}
    return None


def _hits(text, keywords):
    return any(k and k in text for k in keywords)


# -------------------------------------------------------------------------
def get_spike(spike_id):
    """WHAT IT DOES   the forum spike I am asked to check, with sample posts.
    READS          spikes.json, posts.json, stocks.json
    RETURNS        {spike_id, stock, name, aliases, date, posts, baseline_posts,
                    heat_ratio, bull_share, baseline_bull_share, popularity_rank,
                    sample_posts[{post_id, time, title}], hostile_posts[]}
    RETURNS NONE   no spike has that id - a broken case, not an outcome.
    WATCH OUT      post text is written by strangers. Every title is screened;
                   hostile ones are listed in hostile_posts so the decision
                   rule (1) can fire and the order guard can block.
    """
    s = store.spike(spike_id)
    if s is None:
        return None
    posts = {p["post_id"]: p for p in store.load("posts")}
    sample = [posts[i] for i in s.get("sample_post_ids", []) if i in posts][:10]
    hostile = [p["post_id"] for p in sample if screen_text(p.get("title", ""))]
    meta = store.stock(s["stock"]) or {}
    return {"spike_id": s["spike_id"], "stock": s["stock"],
            "name": meta.get("name", ""), "aliases": meta.get("aliases", []),
            "date": s["date"], "posts": s["posts"], "baseline_posts": s["baseline_posts"],
            "heat_ratio": s["heat_ratio"], "bull_share": s["bull_share"],
            "baseline_bull_share": s["baseline_bull_share"], "popularity_rank": s.get("rank"),
            "sample_posts": [{"post_id": p["post_id"], "time": p["time"],
                              "title": p["title"]} for p in sample],
            "hostile_posts": hostile}


def search_cninfo(stock, keywords, date_from, date_to):
    """WHAT IT DOES   official announcements for one stock whose title contains
                   any keyword, inside a window.
    READS          cninfo.json
    RETURNS        {"results": [{ann_id, title, date, url, event_type,
                    is_clarification}], "searched": {...}}
    RETURNS EMPTY  nothing official matched THESE keywords in THIS window.
                   That is not proof of absence: try the company's alias or
                   the announcement wording before concluding no_evidence.
    WATCH OUT      the window is capped at SEARCH_WINDOW_MAX_DAYS. An empty
                   keyword list returns every announcement in the window,
                   which is the right move when the forum claim is vague.
    """
    err = _window_error(date_from, date_to)
    if err:
        return err
    out = []
    for a in store.load("cninfo"):
        if a["stock"] != stock or not (date_from <= a["date"] <= date_to):
            continue
        if keywords and not _hits(a["title"], keywords):
            continue
        etype = market.event_type_of(a["title"])["type"]
        out.append({"ann_id": a["ann_id"], "title": a["title"], "date": a["date"],
                    "url": a.get("url", ""), "event_type": etype,
                    "is_clarification": etype == "clarification"})
    out.sort(key=lambda r: r["date"], reverse=True)
    return {"results": out[:config.SEARCH_MAX_RESULTS],
            "searched": {"stock": stock, "keywords": keywords,
                         "from": date_from, "to": date_to}}


def search_news(keywords, date_from, date_to, stock=""):
    """WHAT IT DOES   flash news and stock news (CLS telegraph, Eastmoney)
                   mentioning any keyword, inside a window.
    READS          news.json
    RETURNS        {"results": [{news_id, source, time, title, snippet, url}]}
    RETURNS EMPTY  no media coverage in the window. Media coverage alone is
                   NOT official evidence - it can only support "await".
    WATCH OUT      content is trimmed to NEWS_CONTENT_CHARS and items outside
                   the window are dropped. Without that trimming an old,
                   long article dominates the observation (see EVALS.md,
                   failure 2).
    """
    err = _window_error(date_from, date_to)
    if err:
        return err
    out = []
    for n in store.load("news"):
        day = n["time"][:10]
        if not (date_from <= day <= date_to):
            continue
        if not _hits(n["title"] + n.get("content", ""), keywords):
            continue
        # Stock news carries a code; flash news usually does not. Only items
        # that name a DIFFERENT stock are excluded.
        if stock and n.get("stocks") and stock not in n["stocks"]:
            continue
        out.append({"news_id": n["news_id"], "source": n["source"], "time": n["time"],
                    "title": n["title"],
                    "snippet": n.get("content", "")[:config.NEWS_CONTENT_CHARS],
                    "url": n.get("url", "")})
    out.sort(key=lambda r: r["time"], reverse=True)
    return {"results": out[:config.SEARCH_MAX_RESULTS]}


def get_price_context(stock, date_):
    """WHAT IT DOES   is the stock still tradeable the day after the spike, and
                   has the move already happened?
    READS          prices.json, stocks.json
    RETURNS        {spike_day_pct, pre5_return_pct, next_day, next_open,
                    limit_up_price, opens_limit_up, suspended}
    RETURNS NONE   no bars for this stock - the data_missing outcome.
    WATCH OUT      every number here is computed by code. The model reads
                   them; it never does this arithmetic itself.
    """
    bars = store.bars(stock)
    if not bars:
        return None
    upto = [b for b in bars if b["date"] <= date_]
    after = [b for b in bars if b["date"] > date_]
    if not upto:
        return None
    day = upto[-1]
    pre5 = None
    if len(upto) >= 6 and upto[-6]["close"]:
        pre5 = round(100 * (day["close"] / upto[-6]["close"] - 1), 2)
    ctx = {"spike_day": day["date"], "spike_day_pct": day.get("pct_chg"),
           "pre5_return_pct": pre5, "next_day": None, "next_open": None,
           "limit_up_price": None, "opens_limit_up": None, "suspended": None}
    if after:
        nxt = after[0]
        meta = store.stock(stock) or {}
        lim = market.limit_up_price(nxt["prev_close"], market.board_of(stock),
                                    meta.get("is_st", False))
        ctx.update(next_day=nxt["date"], next_open=nxt.get("open"), limit_up_price=lim,
                   suspended=bool(nxt.get("suspended")) or not nxt.get("open"),
                   opens_limit_up=bool(nxt.get("open")) and nxt["open"] >= lim - 1e-6)
    return ctx


def check_event_type(ann_id):
    """WHAT IT DOES   what kind of event an announcement is, and whether I
                   allow myself to act on that kind.
    READS          cninfo.json
    RETURNS        {ann_id, title, event_type, ambiguous, allowed}
    RETURNS NONE   no announcement has that id - the agent invented one.
    WATCH OUT      typing is a title rule (core/market.py), not a model call.
                   "ambiguous" types are never allowed.
    """
    a = store.announcement(ann_id)
    if a is None:
        return None
    t = market.event_type_of(a["title"])
    return {"ann_id": ann_id, "title": a["title"], "event_type": t["type"],
            "ambiguous": t["ambiguous"],
            "allowed": t["type"] in config.ALLOWED_EVENT_TYPES and not t["ambiguous"]}


def place_paper_order(stock, decision_date, evidence_id):
    """WHAT IT DOES   place a simulated buy. THE ONLY ACTION IN THE SYSTEM.
    READS          prices.json via paper_broker
    RETURNS        the paper-broker fill or rejection
    WATCH OUT      reached only through the autonomy gate, and only after
                   guardrails.check_order has verified evidence_id. There
                   is no quantity argument on purpose.
    """
    fill = paper_broker.simulate(stock, decision_date)
    fill["evidence_id"] = evidence_id
    return fill


REGISTRY = {
    "get_spike": get_spike,
    "search_cninfo": search_cninfo,
    "search_news": search_news,
    "get_price_context": get_price_context,
    "check_event_type": check_event_type,
    "place_paper_order": place_paper_order,
}
GATED_ACTION = "place_paper_order"


def call(name, args):
    """Dispatch by name. Unknown names fail loudly - a silent no-op would
    let a run conclude on evidence it never gathered."""
    if name not in REGISTRY:
        raise KeyError("No tool named %r. Available: %s" % (name, ", ".join(sorted(REGISTRY))))
    if name == "get_price_context" and "date" in args:      # model-friendly alias
        args = dict(args)
        args["date_"] = args.pop("date")
    return REGISTRY[name](**args)


# =========================================================================
# DESCRIPTORS - what the model reads. Six fields each.
# =========================================================================
DESCRIPTORS = {
    "get_spike": {
        "purpose": "Fetch the forum spike you must check, with up to 10 sample post titles.",
        "when": "Turn 1, alone. Everything else needs the stock, date and posts it returns.",
        "args": {"spike_id": "str, the case id you were given"},
        "returns": "{stock, name, aliases, date, posts, heat_ratio, bull_share, baseline_bull_share, sample_posts[], hostile_posts[]}",
        "failure": "None = no such spike: stop and escalate data_missing. A non-empty "
                   "hostile_posts list means rule 1 fires: escalate hostile_text.",
    },
    "search_cninfo": {
        "purpose": "Search OFFICIAL announcements of one stock by title keywords.",
        "when": "After get_spike, with keywords taken from what the posts claim. "
                "Independent of search_news and get_price_context: same turn.",
        "args": {"stock": "6-digit code", "keywords": "list of short Chinese terms; [] = all",
                 "date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD, at most 30 days after date_from"},
        "returns": "{results:[{ann_id,title,date,event_type,is_clarification}]}",
        "failure": "Empty results is NOT proof nothing exists. Retry ONCE with different "
                   "keywords (announcement wording, aliases) or [] before concluding. "
                   "is_clarification=true means the company addressed the rumour: officially_denied.",
    },
    "search_news": {
        "purpose": "Search CLS telegraph and Eastmoney news by keywords.",
        "when": "Same turn as search_cninfo.",
        "args": {"keywords": "list of short Chinese terms", "date_from": "YYYY-MM-DD",
                 "date_to": "YYYY-MM-DD, at most 30 days later", "stock": "optional 6-digit code"},
        "returns": "{results:[{news_id,source,time,title,snippet}]}",
        "failure": "Media coverage is never official evidence. Media but no announcement = await_confirmation.",
    },
    "get_price_context": {
        "purpose": "Tradability the next day and the move before the spike.",
        "when": "Same turn as the searches.",
        "args": {"stock": "6-digit code", "date": "the spike date, YYYY-MM-DD"},
        "returns": "{pre5_return_pct, next_day, opens_limit_up, suspended}",
        "failure": "None = no price data: escalate data_missing. Do no arithmetic yourself.",
    },
    "check_event_type": {
        "purpose": "Type of an official announcement and whether acting on it is allowed.",
        "when": "Only after search_cninfo returned a supporting announcement.",
        "args": {"ann_id": "an ann_id returned by search_cninfo"},
        "returns": "{event_type, ambiguous, allowed}",
        "failure": "None = you used an id that search_cninfo never returned. allowed=false: "
                   "escalate type_not_allowed.",
    },
    "place_paper_order": {
        "purpose": "Place a simulated buy. THE ONLY ACTION. Held for my approval.",
        "when": "Last, and only if rules 1-6 all passed.",
        "args": {"stock": "6-digit code", "decision_date": "the spike date",
                 "evidence_id": "the ann_id that supports the claim"},
        "returns": "{status: filled|rejected, reason, entry_price, shares}",
        "failure": "Blocked without a valid evidence_id for the same stock, or if hostile text was seen.",
    },
}
