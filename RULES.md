# Decision Rules

Fixed before any agent result was graded. Every threshold is mirrored in `core/config.py`; the model receives the same rules through `core/prompt.py`. The commit date of this file is the evidence that the rules came first.

## 1. What counts as a spike (code)

Two stages. Stage 1 uses Eastmoney's daily popularity rank (one year per stock, one request); stage 2 uses the forum posts collected for that day.

| Stage | Condition | Threshold |
|---|---|---|
| 1 | Rank that day | ≤ 200 |
| 1 | Median rank of the previous 20 days ÷ rank that day | ≥ 3.0 |
| 1 | First day of an episode | no jump in the previous 5 trading days |
| 2 | Posts collected that day | ≥ 30 |
| 2 | Bullish share = bullish / (bullish + bearish), from the sentiment model | ≥ 60% |

Uncertain and neutral posts are excluded from the share. Candidates failing stage 2 are kept in `data/snapshot/rejected_candidates.json`.

*Change log:* the first version counted posts per day (≥ 3× the 20-day mean). Counting requires every post of the year, which the forum's access check does not allow; the popularity rank replaced it on 2026-10-02, before any spike was labelled or any agent run graded.

## 2. How a spike is decided (agent)

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

## 3. Paper broker

Entry at the next trading day's open (CNINFO times are date-only, so announcements are treated as after-close). Rejected if suspended or opening at limit-up (main board ±10%, ChiNext/STAR ±20%, ST ±5%, BSE ±30%). Size: 10% of 100,000 CNY, rounded down to 100 shares. Commission 0.025% (min 5 CNY) both sides, transfer fee 0.001% both sides, stamp duty 0.05% on sells. Exit at the close 20 trading days later.
