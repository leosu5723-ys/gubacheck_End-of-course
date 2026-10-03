"""
GubaCheck - SNAPSHOT STORE
=========================================================================
Read-only access to the frozen data snapshot in data/snapshot/.

The agent never reads these files. It asks a tool a question and gets one
answer back; the tools read through this module. Freezing the data into a
snapshot is what makes every evaluation run reproducible: the forum, the
news feeds and the announcement site all change by the minute, the
snapshot does not.

Files (all JSON, written by collectors/ and pipeline/, described in
data/DATA.md):
    spikes.json        detected forum spikes - the agent's work queue
    posts.json         forum post titles, no user names
    announcements.json official filings (CNINFO): exact time, type, procedural flag
    ann_texts.json     text excerpts of filings in watch windows and their RAG context
    rag_context.json   per filing, the earlier same-company filings retrieved for it
    news.json          flash news and stock news (CLS telegraph, Eastmoney)
    prices.json        daily bars per stock
    stocks.json        name, board, ST flag and aliases per stock
=========================================================================
"""
import json
import os

from core import config

_CACHE = {}

_EMPTY = {"spikes": [], "posts": [], "cninfo": [], "news": [], "prices": {}, "stocks": {},
          "announcements": [], "ann_texts": {}, "rag_context": {}, "judgements": {}}


def load(table):
    """Return the parsed contents of data/snapshot/<table>.json.

    RETURNS     the JSON value, cached per process.
    MISSING     returns an empty value of the right shape and remembers the
                miss, so a run on a half-built snapshot degrades to the
                `data_missing` outcome instead of crashing.
    """
    if table not in _CACHE:
        path = os.path.join(config.DATA_DIR, "%s.json" % table)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                _CACHE[table] = json.load(fh)
        else:
            _CACHE[table] = _EMPTY[table]
    return _CACHE[table]


def reset():
    """Forget cached tables (used by tests that swap DATA_DIR)."""
    _CACHE.clear()


def spike(spike_id):
    return next((s for s in load("spikes") if s["spike_id"] == spike_id), None)


def stock(code):
    return load("stocks").get(code)


def bars(code):
    """Daily bars for one stock, oldest first."""
    return sorted(load("prices").get(code, []), key=lambda b: b["date"])


def announcement(ann_id):
    """One filing with exact time, type and procedural flag."""
    return next((a for a in load("announcements") if a["ann_id"] == ann_id), None)
