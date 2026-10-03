# GubaCheck — Product Documentation

**When a stock's forum suddenly explodes, GubaCheck finds out why — and shows how spikes with that cause behaved afterwards.**

## Persona

**Me: a retail investor with a full-time job** who follows ten A-share stocks (AI hardware, EVs, batteries, shipbuilding) on a phone, ten minutes after the close. When the Eastmoney forum (Guba) of one of my stocks suddenly fills with posts, I cannot tell in ten minutes whether it is company news, a rumour, the whole sector, last night's Nasdaq, the market, a policy headline or hot money. Chasing the crowd without knowing which is my most expensive habit.

**What changes once GubaCheck works:** I open one page per spike. It tells me the most likely cause, the evidence and its timing, and what happened, on average, after earlier spikes with the same cause. Buying is not the product; a gated paper-order entry is kept for later.

**The pain in numbers:** ten stocks, ~1.02 million own-bar posts in a year (≈ 2,800 a day); 68 spikes in eleven months (≈ 6 a month); checking one by hand across filings, peers, US prices, indices and news took me [Z] minutes.

**Closest existing tools and the gap**

| Tool | What it does | What it does not do |
|---|---|---|
| Eastmoney popularity rank / Guba heat | shows that a stock is hot | does not say **why** |
| Forum-sentiment projects on GitHub | a daily sentiment score | a number, no cause, no evidence |
| TradingAgents(-CN), daily_stock_analysis | multi-agent BUY/SELL calls | no checkable attribution, no measured accuracy |

**Out of scope:** real orders, advice to others, price prediction, whole-market scanning, adding new stocks live (cut for time; the offline pipeline supports it).

## Input and output

**Input:** a spike = a trading day whose own-bar post count is abnormal for that stock (log-posts z ≥ 2 against its previous 120 trading days, first day of an episode). Example `SPK-688256-20260203`.

**Output:** an attribution report (page 2 of the app)

```
SPK-688256-20260203  寒武纪  posts 2,249 (z 5.0), bullish 21% (z −1.8), onset 2026-02-03 09:00
clues → priors      C 33% · B 28% · G 22% · A 17%   (from the most-read posts)
tested              C FAIL (peers flat) → B PARTIAL (articles, but after onset) → G FAIL → A PARTIAL → D FAIL
stopped             5 tests (cap)           primary  H (unexplained)
history of H        D+1 −0.7% · D+5 −1.6% · D+20 −2.0% excess vs CSI 300 (n = 54)
```

## Architecture

```
 DATA (frozen snapshot)            MODELS (local + rented)              ATTRIBUTION AGENT                      OUTPUT
 ┌──────────────────────┐   ┌──────────────────────────────┐   ┌────────────────────────────────────┐   ┌───────────────────┐
 │ 1.02M forum titles   ├──►│ RoBERTa (fine-tuned, local)  │   │ get_spike                          │   │ Streamlit UI      │
 │ CNINFO filings (text)├──►│  bull/bear/neutral per post  ├──►│ score_causes  (LLM raw 0-10, A-G)  │   │  watchlist        │
 │ prices: 10 + 12 peers│   │ z-score engine (code)        │   │   → code: priors                   ├──►│  attribution      │
 │ US peers, indices    │   │  spikes, onset hour          │   │ loop: check_A … check_G            │   │  evaluation       │
 │ top list (龙虎榜)     │   │ filing judge: LLM + chunked  │   │   → code: verdict, posterior, STOP │   │  paper (reserved) │
 │ article posts        │   │  RAG over own filings        │   │ revise_scores (LLM, agent arm only)│   │ cause backtest    │
 └──────────────────────┘   └──────────────────────────────┘   │ GUARDS: step cap, budget, de-dup,  │   │  D+1 … D+20       │
   AKShare + forum API         bge-small-zh embeddings          │ stop rule, hostile text, gate      │   └───────────────────┘
                               DeepSeek V4.1 Flash (OpenRouter) └────────────────────────────────────┘
```

**Where the model is and is not used.** The LLM reads post titles and turns clues into raw scores, chooses which cause to test next, may re-score untested causes after a surprise, writes the conclusion, and judges filings. **Code** computes every z-score, every PASS / PARTIAL / FAIL, every probability, the stop rule, every return and every cost.

**Own vs rent**

| Layer | Own / rent | What | Why |
|---|---|---|---|
| Interface | Own | Streamlit, Chinese / English | One user; reads the frozen snapshot, no key needed |
| Orchestration | Own | Hand-written loop + investigation state | The stop rule and posterior must be checkable code |
| Reasoning model | Rent | DeepSeek V4.1 Flash via OpenRouter | Commodity; one string to swap |
| Post sentiment | Own (teacher rented once) | RoBERTa fine-tuned on 3,000 GPT-6 labels | 1M posts at zero marginal cost: 0.73 vs 0.79 Macro-F1 for the teacher |
| Retrieval | Own | bge-small-zh, metadata filter, top-5 ≥ 0.80, forced same-period forecast | Local; the forced document removed every false-bullish call |
| Data | Free public | CNINFO, prices, US prices, indices, top list via AKShare; forum via its public list API | Data cost 0 |
| Evaluation | Own | Hand labels, harness, four arms, guardrail checklist | The evidence is the product |

## Metrics: targeted vs reached

| Metric | Target | Reached | Source |
|---|---|---|---|
| Post sentiment Macro-F1 (hand labels, deployed model) | ≥ 0.65 and > lexicon | **0.73** (CI 0.62–0.82); lexicon 0.32 | results/sentiment_eval.json |
| Daily bullish-share bias | within ±3 pts | **+0.3 pts** (40.0% vs 39.7%) | results/sentiment_eval.json |
| Filing judge Macro-F1 (30 hand-labelled filings) | > title rule | text **0.91**, RAG **0.82**; title rule 0.51 | results/judge_eval.json |
| Filing judge false-bullish (non-bullish filing called bullish) | lowest | RAG **0 / 52**; text 4 / 52 | results/judge_eval.json |
| Primary-cause accuracy, agent arm (68 hand labels) | > always-H baseline and > keyword arm | **55.9%** (always-H 7.4%, keyword 22.1%); but **below always-B 69.1%** | results/results_agent_live_*.json |
| Primary-cause macro-F1, agent arm | > always-B (0.12) | **0.37** (routing 0.36, exhaustive 0.22, keyword 0.17) | results/results_*.json |
| Cause tests per spike, agent vs exhaustive | fewer at equal accuracy | **4.38** vs 7.00, accuracy 55.9% vs 47.1% | results/results_*.json |
| Agent better than routing (revision adds value) | agent > routing | **not reached**: 55.9% vs 60.3%, paired 3 vs 6 cases (p = 0.51); the agent revised in 1 of 68 runs | results/results_*_live_*.json |
| Guardrail checklist | 10 / 10 | **10 / 10** | results/guardrails.json |
| Cost per spike (live, deepseek-v4.1-flash) | < US$0.01 | **US$0.0056** agent, US$0.0051 routing | results/cost_model.json |
| Unit tests | all pass | **12 / 12** | tests/ |

## Cost to serve (results/cost_model.json)

| Layer | Value |
|---|---|
| Sentiment | US$0 per 1,000 posts (local, ~414 posts/s) |
| Filing judgement | US$0.00088 per filing (measured, 468 calls) |
| Attribution | US$0.0056 per spike (live agent arm, 68 spikes, US$0.38 in total) |
| Volume | 0.62 spikes and 3.9 substantive filings per stock-month |
| 10 / 100 / 1,000 stocks | model US$0.07 / 0.69 / 6.9 a month; **with manual re-checks of wrong attributions ~US$9 / 92 / 916** |

The model bill is negligible; the cost that scales is a person re-checking wrong attributions. The lever is accuracy, not a cheaper model.

## Responsible use

- **Intended use:** my own research — attribution and historical context. **Not for:** automated trading, advice to others, naming people behind rumours.
- **Silent failures, and how they are caught:** a cause explained by evidence that came *after* the move (every tool checks timing; failure 2 in `demo_failures.py` shows 15 of 68 verdicts change without it); evidence counted twice (de-duplication; failure 1); an over-confident cause with little support (verdicts are code, posteriors are shown, "H" is an allowed answer).
- **Code, not disclaimers:** stop rule and 5-test cap, budget ceiling, de-duplication, hostile-text screen on forum titles, evidence-required and never-bullish guards on the reserved order, human gate.
- **Frameworks:** OWASP Top 10 for LLM Applications (LLM01 injection via forum text — red-team cases G1–G3; LLM06 unbounded consumption — G5, G7; LLM08 prompt exposure — G3); Singapore IMDA Model AI Governance Framework (a human at the action); PDPA (no user ids stored).
