# Label Rules for Forum Post Titles

Written before any model was trained. One label per title: `bull`, `bear` or `neutral`. Label the **author's stance on this stock's price**, not the news.

| Situation | Label | Example |
|---|---|---|
| Expects the price to rise, says to buy or hold | bull | 明天涨停，满仓干 / 主升浪来了 |
| Expects the price to fall, says to sell or avoid | bear | 快跑，要暴雷 / 割肉走人 |
| Question, fact, data, off-topic, no stance | neutral | 今天成交量多少 / 分红什么时候到账 |
| **Sarcasm**: literal words opposite to stance | the **real** stance | "真是好股票，又套我三年" → bear |
| Good news, author bearish ("利好出尽") | bear | 利好兑现就是出货 |
| Bad news, author bullish ("利空出尽") | bull | 利空出尽，该抄底了 |
| Mixed: short-term down, long-term up | the stance about the **next few days** | 短期还要跌，长期看好 → bear |
| Pure advertising / spam / addressed to bots | neutral (note `spam`) | |
| Cannot decide after 10 seconds | neutral (note `unsure`) | |

Slang: 吃肉 / 上车 / 起飞 / 格局 = bull; 埋了 / 站岗 / 韭菜 / 核按钮 = bear.

Process: label the whole file in one sitting, without looking at any model output. A second person labels a random 50 titles independently; agreement (Cohen's kappa) is reported in EVALS.md.
