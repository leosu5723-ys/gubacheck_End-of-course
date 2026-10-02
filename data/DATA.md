# Data

All sources are public and free. Collection code is in `collectors/`; the snapshot the agent reads is built by `pipeline/build_snapshot.py`.

| Source | How | History | Fields kept | Rows *(fill in)* |
|---|---|---|---|---|
| Eastmoney popularity rank | AKShare `stock_hot_rank_detail_em` | ~1 year, daily | date, rank | |
| Eastmoney Guba forum | Separate full-year collection via the forum's public list API, imported by `pipeline/import_guba.py` | 2025-10-03 to 2026-10-02, 365/365 days for every stock | post_id, stock, publish time, title, reads, comments, post_type, bar_code | 1,098,973 posts; 1,023,925 from the stock's own bar |
| CNINFO announcements | AKShare `stock_zh_a_disclosure_report_cninfo` | Full | ann_id, stock, title, date, url | |
| CLS telegraph | AKShare `stock_info_global_cls` | Latest ~20 only | time, title, content | |
| Eastmoney flash | AKShare `stock_info_global_em` | Latest ~200 only | time, title, summary, url | |
| Eastmoney stock news | AKShare `stock_news_em` | Latest ~10 per stock | time, title, content, url | |
| Daily prices | AKShare `stock_zh_a_hist`, unadjusted | Full | open, close, high, low, pct change, previous close | |

**Watchlist:** `data/watchlist.json` — 10 stocks (AI hardware, EV/auto, battery, shipbuilding); forum window 2025-10-03 to 2026-10-02; announcements and prices from 2025-08/09 to 2026-09-30; news archive from 2026-08-06.

## Files

| Path | Committed | Content |
|---|---|---|
| `data/raw/*.jsonl` | No (size, platform terms) | Everything collected, incl. the imported forum posts |
| `data/snapshot/*.json` | Yes | Frozen subset the tools read: spikes, the sample posts of each spike, announcements, news, prices, stock names |
| `data/labels/labelled.csv` | Yes | 99 hand-labelled post titles (bull / bear / neutral / unsure) — the test set |
| `data/labels/llm_part*.csv` + `llm_done/` | Yes | 3,000 other posts labelled by an LLM — the training set (prompt and model in LLM_LABEL_PROMPT.md) |
| `data/labels/LABEL_RULES.md` | Yes | The rule sheet the labels follow |

The repository runs end to end from `data/snapshot/` without the raw files.

## Labels: what happened

1. A 300-post sheet was drawn (10 stocks × 12 months). The first `labelled.csv` committed for it (commit e05de8c, described there as human labels) **was produced by an LLM, not by hand**. A blind LLM check later agreed with it on 300 of 300 posts, which exposed the problem. That file and the baseline computed from it were withdrawn.
2. I then labelled **99 posts by hand** (the first 99 of the sheet by date, 2025-10-03 to 2026-01-11). Seven I could not decide and marked `unsure`; they are excluded from scoring and reported separately. The other 201 posts of the sheet are unlabelled.
3. The LLM-vs-human check uses GPT-6's labels from step 1 for the 99 hand-labelled posts. Those labels predate the hand labels, so the model never saw them. (A later "blind check" file was contaminated: the labelling tool could read the hand-label file in the same folder. It is not used.)
4. Many titles cannot be labelled from the text alone: "300见，别怪我说话难听" is bullish or bearish depending on whether the price that day was below or above 300. Labels were assigned without looking up the price, so they carry this ambiguity.

## Known limitations

- **CNINFO times are date-only.** All announcements are treated as published after the close; trading is the next day at the open.
- **News feeds keep no history.** Media coverage can only be evaluated for dates after daily collection started ([date]). Cases before that date can never reach `await_confirmation` through media, which the answer key reflects.
- **Forum list pages include a few pinned and hot posts from other bars.** Posts whose bar_code names a different stock are dropped.
- **Titles only.** Post bodies are not collected; sentiment is judged from titles.
- **Test labels cover 2025-10 to 2026-01 only,** while training labels and spikes span the whole year.

## Forum access and how the full-year data was obtained

**First attempt (this repository's `collectors/guba.py`).** Paging the forum's HTML list with three parallel workers triggered the site's identity check ("身份核实") after about 20 pages per stock. The collector at that time treated the check page as "no more posts" and ended quietly with two weeks of data for three stocks and none for seven: a silent failure. The collector now stops and reports when it sees the check, runs one request at a time and never tries to get around the check.

**Full-year data (used for all results).** Collected separately through the forum's public JSON list endpoint (`gbapi.eastmoney.com/webarticlelist/api/Article/Articlelist`, `sorttype=0`, 100 posts per page). No login, proxies or check-solving were involved. The collection scripts ran **8 parallel requests with 0.4 s between batches**, faster than this project's own access policy, and included a public-DNS fallback for that host. I record this as it happened; the scripts are not part of this repository and are not re-run. Every stock has a collection report with record counts, date bounds, page continuity checks and a SHA-256 of its data file; `pipeline/import_guba.py` re-checks day coverage (365/365 for all ten) and restores each post's true source bar from the raw pages.

**Limits of the dataset.** It reflects posts publicly listed at collection time (deleted or hidden posts are absent). `reads` and `comments` are counts at collection time, not at posting time. Titles only, no bodies or replies.

## Privacy and terms

No user ids, nicknames or IP regions are stored. This repository's collector is sequential and rate-limited (1 request every 5 s); see above for how the full-year forum data was collected. Raw collections are not redistributed; the snapshot contains only what the evaluation needs.
