# Label Rules for Forum Post Titles

Written before any model was trained. **Every title gets exactly one of three labels: `bull`, `bear` or `neutral`.** Label the author's stance on this stock's price over the next few days, not whether the news is good or bad.

## The three labels

| Label | Use when the author… | Examples |
|---|---|---|
| `bull` | expects the price to rise, or says to buy / hold | 明天涨停，满仓干 · 启动吧，大船宝宝 · 利空出尽，该抄底了 |
| `bear` | expects the price to fall, or says to sell / avoid | 快跑，要暴雷 · 又诱多了一批 · 利好兑现就是出货 |
| `neutral` | asks a question, states a fact, posts an ad, is off-topic, or you cannot tell in 10 seconds | 今天成交量多少 · 分红什么时候到账 |

## Tricky cases (still one of the three labels)

| Situation | Label | Example |
|---|---|---|
| Sarcasm: words say one thing, stance is the opposite | the real stance | 真是好股票，又套我三年 → `bear` |
| Good news, but the author is negative | `bear` | 利好兑现就是出货 |
| Bad news, but the author is positive | `bull` | 利空出尽，该抄底了 |
| Short-term down, long-term up | stance for the next few days → usually `bear` | 短期还要跌，长期看好 |
| Spam, ads, posts addressed to bots | `neutral` | |
| Unsure after 10 seconds | `neutral` | |

Slang: 吃肉 / 上车 / 起飞 / 格局 / 启动 = `bull`; 埋了 / 站岗 / 韭菜 / 核按钮 / 诱多 = `bear`.

## The `note` column (optional)

Leave it empty, or write `unsure` / `spam` if you want to mark a hard case. It is never used as a label; it only lets the report look at hard cases separately.

## Process

Label the whole file in one sitting, without looking at any model output. Save as `data/labels/labelled.csv` (CSV UTF-8).
