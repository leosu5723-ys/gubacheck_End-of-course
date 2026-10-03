# Report outline (≈1,200 words, ±15%) and video outline

写作说明：下面是结构和每节可以引用的**实测数字**（都能在 `results/` 找到出处）。正文请用第一人称、用你自己的话写；标 `[ ]` 的地方等标注和 live 结果出来后填。教授公告强调：推理深度、对指标和评测的批判、遇到的困难、调优过程、粗糙之处、结构清晰。

---

## 1. The problem and why it matters (~150 words) — Rubric 1

- Persona: me, ten A-share stocks, ten minutes after the close. A forum spike is a signal I cannot read: company news? rumour? sector? Nasdaq? policy? hot money?
- Scale: 1.02M own-bar posts a year across ten stocks; 68 spikes in eleven months.
- Gap: popularity ranks say *that* a stock is hot, sentiment projects give a number, multi-agent tools give BUY/SELL — none says *why* with checkable evidence.
- What changes for me: one page per spike, a cause with evidence and timing, and how that kind of spike behaved afterwards.

## 2. How the design got here — the honest path (~200 words) — reasoning depth

- v1 "verify the rumour, then buy": 32 of 42 spikes had no official basis → an always-"don't chase" system scored 76%; the key could not separate good from lucky.
- v3 forward-watch backtest: buying at the first bullish filing after a frenzy **lost** money — S1 excess −2.2% at D+1, −5.6% at D+10 (n = 11); S2 (all 77 bullish filings) −1.4% to −2.6% for D+1…D+10, CI excluding 0; entry-day open-to-close −2.5% ("利好兑现"). → Detecting good news ≠ profiting from it.
- v4 reframes the product as attribution: explain the spike, then show the cause's history. Rules registered before results; every change logged with its reason (RULES.md).

## 3. Why an agent — and which parts are not (~250 words) — Rubric 2, D0

- Workflow test: the sequence of tests is chosen from clues in the posts; the number of tests varies (stop rule). Ground truth at every step: code-graded z-scores and timestamps.
- What stays code: anomaly detection, all verdicts, priors/posterior, stop rule, returns, costs. Model: clue scoring, next test, revision, conclusion, filing judgement.
- Fixed interfaces risk turning it into routing (rung 3); what keeps it an agent is revision after evidence — **measured**: accuracy agent 55.9% / routing 60.3% / exhaustive 47.1% / keyword 22.1%; tests per spike 4.38 / 4.29 / 7.00 / 4.59; cost US$0.0129 / 0.0118 per spike. **The agent revised in 1 of 68 runs**, and agent vs routing is 3 vs 6 paired wins (p = 0.51). Routing beats exhaustive with fewer tests (11 vs 2, p = 0.02).
- Honest outcome: routing matched the agent, so routing is the right rung for this task; the revise tool was available but almost never used. The LLM's value is in the ranking (fewer tests, better than exhaustive) and in reading PARTIAL evidence, not in revision.

## 4. Build vs buy and cost (~200 words) — Rubric 2, Class 5

- Sentiment: rented teacher once (GPT-6, 3,000 labels; 0.79 Macro-F1 on my labels), owned student (RoBERTa 0.73; TF-IDF 0.60; lexicon 0.32) — 1M posts at zero marginal cost, daily bullish-share bias +0.3 pts.
- Filing judge: title rule 0.51 → LLM 0.91 → LLM + RAG 0.82 with **0 false-bullish** (text mode: 4/52). RAG's forced same-period forecast fixed the "already pre-announced" errors (e.g. a 2025 express within its January forecast range); removing it drops Macro-F1 to 0.73. Trade-off: RAG became conservative on two large ship contracts.
- Cost to serve: US$0.0020 per filing, US$0.0129 per spike live (deepseek-v4.1-flash, US$0.88 for 68 spikes) — **misses my < US$0.01 target**; ~38k tokens per spike, 96% input (the tool results are re-sent every turn). At 10/100/1,000 stocks the model bill is US$0.16/1.59/15.9 a month, but manual re-checks of wrong attributions make it ~US$9/93/925 → the lever is accuracy, not a cheaper model.
- Rough edge in my own cost accounting: prices were typed by hand and the first live run was costed at a stale default (half the real price). Fixed by reading list prices from OpenRouter and recording the billed cost per call.

## 5. Evaluation and its limits (~250 words) — critique

- Attribution accuracy vs my labels: agent 55.9%, routing 60.3% (observe 64% / check 58%); always-H 7.4%; **always-B 69.1% beats every arm** — accuracy is the wrong headline on a 47/68-B label set; macro-F1 0.37 vs 0.12 is the honest one. D 0/3 and F 0/2 never recovered.
- Main error B → H: the B tool gave PARTIAL and the PASS-only rule cannot promote it; when model and code disagreed, the model was right 7/12 (routing), code 1/12. The rule I wrote to keep the model honest is now the bottleneck.
- 45 of 136 first live cases crashed on one extra argument (`spike_id` to `score_causes`) — an interface-robustness failure, fixed in the tool layer, re-run from checkpoints.
- What the numbers cannot say: one labeller; 68 spikes over 8 causes; one live trial per spike; labels written from the same evidence the tools see.
- Rough edges found: B passed 55/68 in its first form (heavy stocks always have articles) → rewritten as a z-score; intraday rumour spikes fail the timing rule because the onset is detected before the rumour spreads; board-secretary Q&A only for recent months; first sentiment test labels were LLM-made and withdrawn; forum access check and a silent-failure collector.
- Two reproduced failures: de-duplication removed → evidence counted five times, no error; US-before-open rule removed → 15/68 D verdicts change, one FAIL becomes PASS.
- Guardrails 10/10 incl. three red-team posts (injection, fake filing id, prompt request).

## 6. Responsible use and what next (~150 words)

- Intended use / non-use; OWASP LLM01/06/08; IMDA human at the action; PDPA.
- Next: price-driven category (23 of 68 spikes had |return z| ≥ 2 that no cause covers), intraday onset vs evidence, more labellers, live adding of stocks, news archive.

---

## Video (5 ± 3 min, face + screen)

| 时间 | 画面 | 讲什么 |
|---|---|---|
| 0:00–0:40 | 自己出镜 + 自选股面板 | 痛点：股吧突然炸了，不知道为什么 |
| 0:40–1:20 | 架构图（PRODUCT.md） | 本地模型 → z-score → 归因 agent → 历史回测；模型做什么、代码做什么 |
| 1:20–3:00 | 归因报告页：选一个 PASS 的案例 + 一个 H 的案例 | 线索评分 → 先验 → 每步验证 → 后验变化 → 停止 → 时间线 → 该原因历史 D+N |
| 3:00–3:50 | 终端 / EVALS.md 结果表 | 四种方案对比、RAG 消融、护栏 10/10（`python3 run_guardrails.py`） |
| 3:50–4:30 | 终端：`python3 demo_failures.py` | 两个失败：重复计证据、时间规则 |
| 4:30–5:10 | 出镜 | 局限和下一步；为什么从"买入信号"转向"归因" |
