# Decision Rules

Fixed before any agent result was graded. Every threshold is mirrored in `core/config.py`; the model receives the same rules through `core/prompt.py`. The commit date of this file is the evidence that the rules came first.

## 1. What counts as a spike (code)

A stock-day is a spike when all hold:

| Condition | Threshold |
|---|---|
| Own-bar posts that day vs mean of the previous 20 days | ≥ 2.0× |
| Bullish share vs its 20-day mean | ≥ +10 percentage points |
| Posts that day | ≥ 30 |
| Prior days available for the baseline | ≥ 10 |
| First day of an episode | no spike in the previous 5 days |

Bullish share = bullish / (bullish + bearish) posts, labelled by the sentiment model (fine-tuned RoBERTa; TF-IDF fallback).

Cross-check (not part of the rule): Eastmoney's daily popularity rank. A rank jump is rank ≤ 200 and ≥ 3× better than its 20-day median. `results/spike_validation.json` reports the correlation between daily post counts and popularity, and how many forum spikes fall within 2 days of a rank jump.

*Change log.* 2026-10-02: the forum blocked page-by-page collection, so spikes were temporarily defined from the popularity rank plus posts collected on candidate days. 2026-10-03: the full-year forum dataset became available and the rule returned to the original post-count definition above. 2026-10-03 (later): with full-year data the original thresholds (3.0× posts and +20 points) produced only 7 spikes in a year across 10 stocks, too few to evaluate. The reason is itself a finding: on the 152 stock-days with ≥ 3× posts, the bullish share usually *fell* (median −6 points; 90th percentile +12; maximum +27): the forum is busiest in sell-offs, not in euphoria. Episodes per threshold pair:

| Posts | Bullish shift | Episodes | Stocks |
|---|---|---|---|
| ≥ 3.0× | +20 pts | 7 | 5 |
| ≥ 3.0× | +10 pts | 15 | 8 |
| ≥ 2.5× | +10 pts | 27 | 10 |
| ≥ 2.0× | +10 pts | 42 | 10 |
| ≥ 3.0× | +0 pts | 35 | 9 |

The thresholds were changed to 2.0× and +10 points, keeping both conditions of the idea (a surge of discussion *and* a surge of bullishness). The choice used only the number of spikes, before any spike was examined, labelled or given to the agent.

All changes above were made before any spike was labelled or any agent run graded.

## 2. What happens after a spike (forward watch) — registered 2026-10-03, before any backtest was run

A spike puts the stock on a **watch list**. GubaCheck does not act on the forum; it waits for the company.

| Item | Rule |
|---|---|
| Watch window | announcements published from the spike day 00:00 to the close of the 10th trading day after the spike (D … D+10) |
| What is read | every CNINFO announcement in the window: full text (PDF), plus the company's own earlier filings retrieved from the knowledge base (RAG), never anything published after the announcement |
| Judgement | the model labels each announcement `bullish` / `bearish` / `neutral` with a one-sentence reason grounded in the text |
| Hard exclusions (code, not the model) | procedural filings (legal opinions, meeting notices, internal rules, monthly H-share returns) are `neutral` without a model call; share issuance / placement, shareholder reduction and lock-up expiry can never be `bullish` |
| Entry | the **first** `bullish` announcement in the window triggers one paper buy (after my approval) at the first open strictly after its publication time (an announcement at 20:42 on day t → open of t+1; one published before 09:30 on a trading day → that day's open) |
| Not tradeable | entry day suspended or opening at limit-up → no trade, recorded |
| Exits reported | close of trading day **+1, +2, +3, +5, +10, +15, +20** after entry, all seven reported; none is chosen after seeing results |
| Costs | commission 0.025% (min 5 CNY) both sides, transfer fee 0.001% both sides, stamp duty 0.05% on sells |
| Benchmark | CSI 300 index over the same holding period (excess return = stock − index) |

### Strategies compared on the same data

| Strategy | Entry |
|---|---|
| S0 naive chase | every spike, next trading day open |
| **S1 GubaCheck** | spike → watch → first bullish announcement (above) |
| S2 announcements only | every bullish announcement of the 10 stocks in the year, no spike needed |
| S3 no trade | — (return 0) |

S1 versus S2 answers whether the forum spike adds anything; S1 versus S0 answers whether waiting for official news beats chasing the crowd.

## 3. (Superseded) single-shot decision on the spike day

The first design decided on the spike day itself whether existing evidence supported the claim. Applied to the 42 spikes, 32 had no company-level official basis, so a system that always answered "do not chase" would score 76% on that key. The forward-watch design above replaced it; the original rules are kept below for the record.

### Original rules (agent)

Checked in order; the first rule that fires decides.

| # | Condition | Decision | Trigger |
|---|---|---|---|
| 1 | A sample post addresses the system (hostile_posts not empty) | flag_do_not_chase | hostile_text |
| 2 | Spike or price data missing | flag_do_not_chase | data_missing |
| 3 | A clarification / abnormal-movement announcement in the window | flag_do_not_chase | officially_denied |
| 4a | No supporting official announcement, but media coverage | await_confirmation | — (name the awaited announcement) |
| 4b | Nothing official or in media, after one retry with new terms | flag_do_not_chase | no_evidence |
| 5 | Supporting announcement's type not allowed, or ambiguous | flag_do_not_chase | type_not_allowed |
| 6a | Next trading day suspended or opens limit-up | flag_do_not_chase | untradeable |
| 6b | Return over the 5 days up to the spike > 15% | flag_do_not_chase | priced_in |
| 7 | Otherwise | paper_trade (after my approval) | — |

Search window: 14 days before the spike date to the spike date. Tools refuse windows over 30 days.

Allowed event types: buyback, shareholder_increase, earnings_preincrease, major_contract.

Rule 3 note: an A-share "股票交易异常波动公告" states that no undisclosed material information exists. When the forum claims undisclosed news, that is an official denial.

## 4. Paper broker

Entry at the next trading day's open (CNINFO times are date-only, so announcements are treated as after-close). Rejected if suspended or opening at limit-up (main board ±10%, ChiNext/STAR ±20%, ST ±5%, BSE ±30%). Size: 10% of 100,000 CNY, rounded down to 100 shares. Commission 0.025% (min 5 CNY) both sides, transfer fee 0.001% both sides, stamp duty 0.05% on sells. Exit at the close 20 trading days later.
