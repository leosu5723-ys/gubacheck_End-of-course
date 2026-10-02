# Decision Rules

Fixed before any agent result was graded. Every threshold is mirrored in `core/config.py`; the model receives the same rules through `core/prompt.py`. The commit date of this file is the evidence that the rules came first.

## 1. What counts as a spike (code)

A stock-day is a spike when all three hold:

| Condition | Threshold |
|---|---|
| Posts that day vs mean of the previous 20 days | ≥ 3.0× |
| Bullish share vs its 20-day mean | ≥ +20 percentage points |
| Posts that day | ≥ 30 |

Bullish share = bullish / (bullish + bearish) posts, from the sentiment model; uncertain and neutral posts are excluded. At least 10 prior days are required.

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
