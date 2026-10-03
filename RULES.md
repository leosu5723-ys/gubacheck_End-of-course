# Decision Rules

Fixed before any result was looked at. Every threshold is mirrored in `core/config.py`. The commit history of this file is the evidence of what was decided when.

## 0. Current design (v4, registered 2026-10-03, before any attribution run or label)

GubaCheck explains **why** a stock's forum suddenly turned bullish, and reports how spikes with that kind of cause behaved afterwards. Buying is a reserved feature behind the gate, not the product.

### 0.1 Anomaly = z-score against the stock's own history
Every "is this abnormal?" test compares a value with the same stock's (or series') previous **120 trading days**, excluding the day itself. No fixed percentage thresholds.

| Test | Series | Abnormal when |
|---|---|---|
| Spike (forum) | log(1 + own-bar posts that day) | z ≥ 2.0 |
| | bullish share that day | recorded, not required (see change log) |
| Spike onset time | posts per hour vs the same hour on previous days | first hour with z ≥ 2.0 |
| Price / volume | daily return, opening gap, turnover | \|z\| ≥ 2.0 |
| Index | CSI 300, ChiNext daily return | \|z\| ≥ 2.0 (PARTIAL 1.5–2.0) |
| US peer | return on the last US session before the A-share open | \|z\| ≥ 2.0 |
| Money flow | top-list (龙虎榜) net buy, turnover | percentile ≥ 95 |

A spike is the first day of an episode: no spike in the previous 5 calendar days. A z-score needs at least 20 prior trading days, so spikes start in early November 2025.

*Change log 0.1 (2026-10-03, before any label or agent run):* the registered pair (posts z ≥ 2 **and** bullish share z ≥ 1.5) produced 7 spikes in a year, 6 stocks with none. Counts: posts z ≥ 1.5 & bull z ≥ 0.5 → 30; posts z ≥ 2 & bull z ≥ 0 → 25; **posts z ≥ 2 alone → 68 (25 before 2026-04-01)**. With the product now explaining spikes rather than buying on them, the direction condition was dropped; the bullish-share z is reported with every spike.

### 0.2 Causes and their fixed interfaces
*Change 0.2 (2026-10-03, before any label or agent run): B was first "any matching article before onset"; on the 68 spikes it passed 55 times because heavily traded stocks have articles every day, so B now uses an article-count z-score like every other test. G uses |net buy| / turnover against the market-wide 95th percentile because daily turnover for a turnover percentile is not in the free price feed.*

*Change 0.2-3 (2026-10-04, after hand labels, using the OBSERVE period only):* with B as above (72 h before onset), even the exhaustive arm reached 13 % accuracy, because I labelled 47 of 68 spikes B while the tool passed B once: media coverage and the forum surge happen **together**, not one before the other. On the 25 OBSERVE spikes only, the two-day count z (D−1 … D) separated my B labels from the rest (median 2.65 vs 0.79); thresholds 1.5 and 2.0 performed identically there, so the global z ≥ 2 was kept. On the 43 held-out CHECK spikes: recall 0.64, precision 0.78. Consequence: B now means "coverage and discussion surged together", not "coverage caused the discussion".

Seven causes, one tool each, identical input (`spike_id`) and output (`verdict` PASS / PARTIAL / FAIL computed by code, metrics, evidence, timing, cost). **H (unexplained) is never scored or tested; it is the outcome when nothing passes.**

| Cause | PASS | PARTIAL | Timing rule |
|---|---|---|---|
| A company official (CNINFO filing, board-secretary reply) | a filing or reply in [D−3, onset] judged in the spike's direction | exists but after onset, or neutral | evidence time < onset |
| B company rumour / media | company-specific articles on D−1 … D, count z ≥ 2 against the stock's own two-day counts | articles exist but not abnormal | **concurrent** (spike day and the day before) — see change 3 |
| C sector co-movement | more than half of the stock's peer group have \|z\| ≥ 2 return that day | at least one peer \|z\| ≥ 2 | same day |
| D overseas read-through | a US peer \|z\| ≥ 2 on the last US session before D's open **and** the stock's opening gap z ≥ 2 | US peer abnormal, no opening gap | US close < A-share open |
| E market | CSI 300 or ChiNext \|z\| ≥ 2 | 1.5 ≤ \|z\| < 2 | same day |
| F policy / macro | a policy-keyword article before onset **and** C or E at least PARTIAL | policy article only | evidence time < onset |
| G money / trading structure | on the top list (龙虎榜) with net buy percentile ≥ 95 | turnover percentile ≥ 95, not on the list | exempt: the list is published after the close |

### 0.3 Scoring, posterior and stopping
1. The model reads the day's most-read posts and gives each of A–G a raw score 0–10 citing post ids. Code normalises: prior_i = max(score_i, 0.5) / Σ (all zero → uniform 1/7).
   *Change 0.3 (2026-10-04, before any successful live run):* the floor of 0.5 was added because a cause scored 0 had a prior of exactly 0 and stayed at 0 even after its test PASSED (0 × 3 = 0), which the investigate-it-yourself screen made obvious. All arms were re-run under the new rule.
2. Each test multiplies the cause's weight: **PASS × 3, PARTIAL × 1, FAIL × 0.2**; code renormalises to the posterior.
3. After a test the model may revise raw scores of **untested** causes, with a reason (this is what makes the loop an agent; a run that never revises is the "routing" arm).
4. **STOP** when (① at least one cause PASSED **and** ② the summed posterior of untested causes < 20 %) **or** ③ 5 cause-tool calls were made.
5. Result: primary cause = the PASSED cause with the highest posterior; secondary = other PASSED causes; none passed → **H**.
6. Ties in the next cause to test are broken by cost: C, D, E, G (numbers only) before A, B, F (reading).

### 0.4 Evaluation
- Gold: my hand label of the primary cause (A–H) for every spike, written from an evidence bundle before any agent run is graded.
- Three arms on the same spikes: **exhaustive workflow** (all seven tools, then summarise), **routing** (rank once, never revise), **agent** (revise after each test). Metrics: primary-cause accuracy, tool calls, tokens and cost, over-investigation (calls after the stop condition held), premature stop (stopped while the gold cause was untested).
- Historical outcome by cause: D+1, 2, 3, 5, 10, 15, 20 net and excess returns (entry next open after the spike day), with sample size; observed on spikes before 2026-04-01, checked on spikes from 2026-04-01.
- **Change 2026-10-04 (in the product, per spike):** the result page shows the *same stock's* earlier spikes with the *same cause* (strictly before this spike, my labels), one row per spike with D+1, 2, 3, 5, 10, 20 net returns, plus mean, mean excess vs CSI 300 and win rate; the all-stocks same-cause table sits underneath. No holding-period slider: n is small. Rule suggestion: needs ≥ 3 earlier cases (this stock first, else all stocks); D+5 mean excess > +1% and win ≥ 60% → lean positive; < −1% and win ≤ 40% → avoid; otherwise wait. Optional LLM suggestion (user's own key) reads the cause, the test results, the history and RAG chunks of the company's earlier filings. The separate backtest-lab page was removed.
- **Change 2026-10-04 (data):** board-secretary Q&A removed from check A, the snapshot and the collectors. It was empty in the evaluated snapshot, so no verdict or result changes; the tool description of A now says "CNINFO filings" only.
- **Fix 2026-10-04 (cost):** the live agent/routing runs and the filing-judge evaluation were costed with a hand-typed stale price ($0.13 / $0.52, from the README example) instead of deepseek-v4.1-flash's $0.30 / $1.20. Costs were recomputed from the recorded token counts; no accuracy figure changes. The app now lists models and prices from OpenRouter's public catalogue, and every live call asks for and records the billed cost.
- **Fix 2026-10-04 (data):** prices are unadjusted, and two share conversions fall in the window (688256 on 2026-05-08, 0.49 per share; 300502 on 2026-06-11, 4 per 10). A holding that spans an ex-date showed a fake −35%. `backtest.trade` now counts the extra shares (`config.SHARE_FACTORS`, ratios from the CNINFO notices); cause backtests re-run. Gold all-cause D+5 excess moved from −1.92% to −0.81%. The archived v3 results (`backtest_rag/text.json`) were **not** re-run, because they use the older spike definition. One S0 trade (688256, entry 2026-04-16) is affected only at D+15/20; the S1/S2 figures quoted in the report (D+1…D+10) are unaffected.

---

## Earlier designs (kept for the record)

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
