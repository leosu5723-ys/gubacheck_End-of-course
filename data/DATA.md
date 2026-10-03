# Data

All sources are public and free. Collection code is in `collectors/`; the snapshot the tools read (`data/snapshot/`) is built by `pipeline/anomaly.py` (spikes, sample posts, daily stats), `pipeline/context_snapshot.py` (everything else) and `pipeline/redteam.py` (three synthetic guardrail spikes); `pipeline/refresh.py` runs the whole chain incrementally.

| Source | How | History | Fields kept | Rows |
|---|---|---|---|---|
| Eastmoney popularity rank | AKShare `stock_hot_rank_detail_em` | ~1 year, daily | date, rank | 3,660 rows; used by the earlier designs only, **not read by any v4 tool** |
| Eastmoney Guba forum | Separate full-year collection via the forum's public list API, imported by `pipeline/import_guba.py` | 2025-10-03 to 2026-10-02, 365/365 days for every stock | post_id, stock, publish time, title, reads, comments, post_type, bar_code | 1,098,973 posts; 1,023,925 from the stock's own bar |
| CNINFO announcements | AKShare `stock_zh_a_disclosure_report_cninfo` | Full | ann_id, stock, title, date, url | 1,604 filings (10 stocks); 468 substantive ones judged by the LLM + RAG |
| CLS telegraph | AKShare `stock_info_global_cls` | Latest ~20 only | time, title, content | 20 |
| Eastmoney flash | AKShare `stock_info_global_em` | Latest ~200 only | time, title, summary, url | 200 |
| Eastmoney stock news | AKShare `stock_news_em` | Latest ~10 per stock | time, title, content, url | 100 (the three news feeds: 320 items in `news.json`, kept for the record, **read by no tool** — they have no history) |
| Daily prices | AKShare `stock_zh_a_hist` (Sina fallback), unadjusted | Full | open, close, high, low, pct change, previous close | 22 stocks, 7,199 daily bars (10 watched + 12 peers) |
| Peer groups | `data/peers.json`, chosen by product line | — | A-share peers (cause C), US peers (cause D) | 4 groups |
| US peers | AKShare `stock_us_daily` (NVDA, AMD, AVGO, LITE, COHR, TSLA) | Full | daily close, return | 6 tickers × 399 days |
| Indices | CSI 300, ChiNext (Sina) | Full | daily open, close | CSI 300 284 days, ChiNext 388 days |
| Exchange top list (龙虎榜) | AKShare `stock_lhb_detail_em`, month by month | Sep 2025–Sep 2026 | stock, date, net buy, turnover, reason | 21,916 market rows (15 for watched stocks; the rest set the "extreme flow" percentile for cause G) |
| Filing text | CNINFO PDFs, `collectors/announcements.py` | Full | text excerpt; exact publication time when the link carries one | 634 texts |

**Watchlist:** `data/watchlist.json` — 10 stocks (AI hardware, EV/auto, battery, shipbuilding); forum window 2025-10-03 to 2026-10-02; announcements and prices from 2025-08/09 to 2026-09-30; news feeds snapshot from 2026-10 only (not used).

## Files

| Path | Committed | Content |
|---|---|---|
| `data/raw/*.jsonl` | No (size, platform terms) | Everything collected, incl. the imported forum posts |
| `data/snapshot/*.json` | Yes | Frozen subset the tools read: spikes, the sample posts of each spike, announcements, news, prices, stock names |
| `data/labels/labelled.csv` | Yes | 99 hand-labelled post titles (bull / bear / neutral / unsure) — the test set |
| `data/labels/llm_part*.csv` + `llm_done/` | Yes | 3,000 other posts labelled by an LLM — the training set (prompt and model in LLM_LABEL_PROMPT.md) |
| `data/labels/LABEL_RULES.md` | Yes | The rule sheet the labels follow |
| `data/post_titles_en.json` | Yes | English glosses of the 408 post titles the app shows as clues (six per spike), written with an AI assistant for the English demo only; the tools never read them |
| `data/stock_profiles.json` | Yes | English name and a short bilingual profile per stock for the app's hover card: position (written by hand), market cap **estimated** from the 30 Sep close × approximate total shares, counts computed from the snapshot, peers from `data/peers.json` |

The repository runs end to end from `data/snapshot/` without the raw files.

## Labels: what happened

1. A 300-post sheet was drawn (10 stocks × 12 months). The first `labelled.csv` committed for it (commit e05de8c, described there as human labels) **was produced by an LLM, not by hand**. A blind LLM check later agreed with it on 300 of 300 posts, which exposed the problem. That file and the baseline computed from it were withdrawn.
2. I then labelled **99 posts by hand** (the first 99 of the sheet by date, 2025-10-03 to 2026-01-11). Seven I could not decide and marked `unsure`; they are excluded from scoring and reported separately. The other 201 posts of the sheet are unlabelled.
3. The LLM-vs-human check uses GPT-6's labels from step 1 for the 99 hand-labelled posts. Those labels predate the hand labels, so the model never saw them. (A later "blind check" file was contaminated: the labelling tool could read the hand-label file in the same folder. It is not used.)
4. Many titles cannot be labelled from the text alone: "300见，别怪我说话难听" is bullish or bearish depending on whether the price that day was below or above 300. Labels were assigned without looking up the price, so they carry this ambiguity.

## v4 notes

- **Media proxy for cause B and F — weaker than its name.** Free news feeds keep no history, so "media" is the forum's own `post_type` 20 posts in the stock's bar, excluding market wrap-ups. I first took these for reposted news; checked by hand (2026-10-04), most are **long posts written by ordinary users** (open letters to management, trading diaries), not professional media. So B measures a burst of long forum posts about the company — forum rumour and narrative — not press coverage. Professional sources that do have history are capped: Eastmoney's news search returns at most 1,000 articles per stock (back to 2026-09-07 for 寒武纪, 2026-06-13 for 广汽), Sina's stock-news list about as many. A full-year professional news archive needs a paid feed.
- **Spike onset** is the first hour whose post count is abnormal against the same clock hour on previous days; posts after 15:00 belong to the next trading day.
- **Hand labels of causes** (`evals/cause_labels.csv`): all 68 spikes, labelled by me on 2026-10-03/04 from `evals/cause_review.md`, which shows raw evidence without tool verdicts.

## Known limitations

- **CNINFO times are date-only.** All announcements are treated as published after the close; trading is the next day at the open.
- **News feeds keep no history.** `news.json` (320 items, collected from 2026-10) is kept for the record but read by no tool; media cause B uses the forum's article posts instead.
- **No board-secretary Q&A.** The free feeds (互动易 / e互动) only return about three months, and the collection finished after the evaluation snapshot was built, so it was never part of any evaluated run. It was removed from the system (2026-10-04); cause A uses CNINFO filings only.
- **Forum list pages include a few pinned and hot posts from other bars.** Posts whose bar_code names a different stock are dropped.
- **Titles only.** Post bodies are not collected; sentiment is judged from titles.
- **Test labels cover 2025-10 to 2026-01 only,** while training labels and spikes span the whole year.

## Forum access and how the full-year data was obtained

**First attempt (this repository's `collectors/guba.py`).** Paging the forum's HTML list with three parallel workers triggered the site's identity check ("身份核实") after about 20 pages per stock. The collector at that time treated the check page as "no more posts" and ended quietly with two weeks of data for three stocks and none for seven: a silent failure. The collector now stops and reports when it sees the check, runs one request at a time and never tries to get around the check.

**Full-year data (used for all results).** Collected separately through the forum's public JSON list endpoint (`gbapi.eastmoney.com/webarticlelist/api/Article/Articlelist`, `sorttype=0`, 100 posts per page). No login, proxies or check-solving were involved. The collection scripts ran **8 parallel requests with 0.4 s between batches**, faster than this project's own access policy, and included a public-DNS fallback for that host. I record this as it happened; the scripts are not part of this repository and are not re-run. Every stock has a collection report with record counts, date bounds, page continuity checks and a SHA-256 of its data file; `pipeline/import_guba.py` re-checks day coverage (365/365 for all ten) and restores each post's true source bar from the raw pages.

**Limits of the dataset.** It reflects posts publicly listed at collection time (deleted or hidden posts are absent). `reads` and `comments` are counts at collection time, not at posting time. Titles only, no bodies or replies.

## Privacy and terms

No user ids, nicknames or IP regions are stored. This repository's collector is sequential and rate-limited (1 request every 5 s); see above for how the full-year forum data was collected. Raw collections are not redistributed; the snapshot contains only what the evaluation needs.
