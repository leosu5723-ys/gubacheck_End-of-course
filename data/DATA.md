# Data

All sources are public and free. Collection code is in `collectors/`; the snapshot the agent reads is built by `pipeline/build_snapshot.py`.

| Source | How | History | Fields kept | Rows *(fill in)* |
|---|---|---|---|---|
| Eastmoney popularity rank | AKShare `stock_hot_rank_detail_em` | ~1 year, daily | date, rank | |
| Eastmoney Guba forum | `collectors/guba.py`, list pages `list,<code>,f_<n>.html` | Candidate spike days + a recent window | post_id, stock, publish time, title, reads, comments, post_type, bar_code | |
| CNINFO announcements | AKShare `stock_zh_a_disclosure_report_cninfo` | Full | ann_id, stock, title, date, url | |
| CLS telegraph | AKShare `stock_info_global_cls` | Latest ~20 only | time, title, content | |
| Eastmoney flash | AKShare `stock_info_global_em` | Latest ~200 only | time, title, summary, url | |
| Eastmoney stock news | AKShare `stock_news_em` | Latest ~10 per stock | time, title, content, url | |
| Daily prices | AKShare `stock_zh_a_hist`, unadjusted | Full | open, close, high, low, pct change, previous close | |

**Watchlist:** `data/watchlist.json` — [N] stocks, collection window [from]–[to].

## Files

| Path | Committed | Content |
|---|---|---|
| `data/raw/*.jsonl` | No (size, platform terms) | Everything collected |
| `data/snapshot/*.json` | Yes | Frozen subset the tools read: spikes, the sample posts of each spike, announcements, news, prices, stock names |
| `data/labels/labelled.csv` | Yes | Hand-labelled post titles (bull / bear / neutral) |
| `data/labels/LABEL_RULES.md` | Yes | The rule sheet the labels follow |

The repository runs end to end from `data/snapshot/` without the raw files.

## Known limitations

- **CNINFO times are date-only.** All announcements are treated as published after the close; trading is the next day at the open.
- **News feeds keep no history.** Media coverage can only be evaluated for dates after daily collection started ([date]). Cases before that date can never reach `await_confirmation` through media, which the answer key reflects.
- **Forum list pages include a few pinned and hot posts from other bars.** Posts whose bar_code names a different stock are dropped.
- **Titles only.** Post bodies are not collected; sentiment is judged from titles.

## Forum access

The forum serves an identity check ("身份核实") when requests come too fast. The first collection run used three parallel workers, triggered the check after about 20 pages per stock, and — because the collector treated the check page as "no more posts" — ended quietly with two weeks of data for three stocks and none for seven. Two changes followed: the collector now stops and reports when it sees the check, and it no longer pages through the whole year. It collects only the candidate spike days found from the popularity rank (one request per stock), one request at a time, 3 s apart. The check is never bypassed.

## Privacy and terms

No user ids, nicknames or IP regions are stored. Requests are sequential and rate-limited (1 every 3 s). Raw collections are not redistributed; the snapshot contains only what the evaluation needs.
