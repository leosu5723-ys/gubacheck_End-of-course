# Prompt used for LLM labelling

The prompt below was used, unchanged, for all six training parts (`llm_part1..6.csv`). The LLM-vs-human check labels came from an earlier GPT-6 run (see the table).

Record here when done:

| Field | Value |
|---|---|
| Model (name and version) | GPT-6 |
| Interface (chat app / API) | Codex |
| Date | 2026-10-03 |
| Parts labelled in one conversation or separately | Training parts 1–6 in one Codex run (files written 01:52). Check labels for the 99 hand-labelled posts are taken from GPT-6's earlier labelling of the whole 300-post sheet (01:17), made before any hand label existed; that run followed the label rules, the exact prompt text was not recorded. |
| Rows the model refused or skipped | 0 |

---

## Prompt

```
你是A股股吧帖子标注员。对每一行帖子标题，判断发帖人对这只股票短期股价的态度，
只能输出三个标签之一：bull（看涨/建议买入或持有）、bear（看跌/建议卖出或回避）、
neutral（提问、陈述事实、数据、广告、与股价无关、无法判断）。

规则：
1. 判断的是发帖人的立场，不是新闻本身的好坏。
2. 讽刺按真实立场标："真是好股票，又套我三年" → bear。
3. "利好出尽/利好兑现就是出货" → bear；"利空出尽/该抄底了" → bull。
4. 短期看跌、长期看好 → 按未来几天的立场 → bear。
5. 黑话：吃肉、上车、起飞、格局、启动 = bull；埋了、站岗、韭菜、核按钮、诱多 = bear。
6. 广告、刷屏、与本股无关、无法在10秒内判断 → neutral。

输出格式：严格保持输入的CSV格式与行顺序，原样保留post_id和title两列，
只在label列填入 bull / bear / neutral。不要添加、删除或合并任何行，不要输出解释。
```
