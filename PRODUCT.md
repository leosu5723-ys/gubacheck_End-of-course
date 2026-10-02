# GubaCheck — Product Documentation

## Persona

**Me: a retail investor with a full-time job**, holding or watching about 10 A-share stocks, who looks at the market for ten minutes after the close and ten minutes before the open, on a phone. I know the Guba forum sometimes carries news early, and I know it is full of pump posts and rumours; I cannot tell which is which in ten minutes. My most expensive habit is buying into a "restructuring is coming" thread without checking.

**What changes once GubaCheck works:** I stop scrolling the forum. Each evening I read a few check cards. Each card gives one decision and the evidence behind it, and nothing is traded unless I say yes.

**The pain, in numbers** *(fill from data/snapshot)*: watchlist of [N] stocks, about [X] posts per day in total, [Y] spikes per month; checking one spike by hand (forum, CNINFO, news) takes me about [Z] minutes.

**Closest existing tools and the gap**

| Tool | What it does | What it does not do |
|---|---|---|
| TradingAgents / TradingAgents-CN, daily_stock_analysis | LLM agents debate and output BUY/SELL | Do not read the forum; conclusions cite no checkable evidence; no published evaluation of their own accuracy |
| Forum sentiment-index projects | Scrape Guba, output a sentiment score | A number, not a reason; never check whether a claim is true |
| Eastmoney / THS announcement pages | List announcements | Do not connect "what the forum says" to "what the company disclosed" |

**Out of scope:** real orders, advice to others, price prediction, whole-market scanning, a graphical interface.

## Input and output

**Input:** one forum spike, detected by code (RULES.md): own-bar posts that day ≥ 3× the 20-day mean, and the bullish share ≥ its 20-day mean + 20 points (sentiment from a fine-tuned Chinese RoBERTa). Example id `SPK-601127-20260915`.

**Output:** a decision record and a check card.

```
SPK-xxxxxx-2026xxxx  [stock name]  posts x4.2 (1,380 vs 330), bullish 71% (base 41%)
Forum claim : "下周公布重组"
Official    : none in CNINFO 2026-09-04..09-18 (searched: 重组, 资产, 收购)
Media       : CLS telegraph 09-17 "市场传闻…"   [news_id]
DECISION    : await_confirmation - awaiting a CNINFO 重大资产重组预案
```

| Decision | When | Must record |
|---|---|---|
| `paper_trade` | official evidence, allowed event type, tradeable; after my approval | evidence_id, event type, fill or rejection |
| `await_confirmation` | media coverage but no official announcement | the claim, the media item, the kind of announcement awaited |
| `flag_do_not_chase` | anything else, with exactly one trigger | the trigger and what was searched |

## Architecture

```
 COLLECT (daily, code)           BUILD (code + narrow ML)              DECIDE (agent)                     ACT
 ┌─────────────────────┐   ┌──────────────────────────────┐   ┌───────────────────────────────┐   ┌──────────────────┐
 │ Guba posts (titles) ├──►│ sentiment: RoBERTa (FT)      │   │ get_spike                     │   │ autonomy gate    │
 │ CNINFO announcements│   │ trained on LLM labels        │   │ ┌ search_cninfo   ┐ parallel  │   │ (my yes / no)    │
 │ CLS + EM news       ├──►│ spike detector (RULES.md)    ├──►│ │ search_news      │ one turn  ├──►│        │         │
 │ prices, popularity  │   │ frozen snapshot (JSON)       │   │ └ get_price_context┘          │   │ paper broker     │
 └─────────────────────┘   └──────────────────────────────┘   │ retry search with new terms   │   │ (A-share rules)  │
     AKShare + own scraper      no model in the hot path      │ check_event_type (title rule) │   │ ledger.csv       │
                                                              │ rented LLM via OpenRouter:    │   └──────────────────┘
                                                              │ reads posts, picks search     │
                                                              │ terms, applies RULES.md       │   results.json
                                                              │ GUARDS: step cap, budget,     │   check cards
                                                              │ de-dup, hostile-text screen,  │
                                                              │ evidence-required order       │
                                                              └───────────────────────────────┘
```

**Own vs rent, layer by layer**

| Layer | Own / rent | What | Why |
|---|---|---|---|
| Interface | Own | CLI + Markdown check cards | One user; a UI adds nothing to the decision |
| Orchestration | Own | Hand-written ReAct loop | When it misbehaves I must be able to read the code that did it |
| Model | Rent | OpenRouter, `[model A]` vs `[model B]` | General language ability is a commodity; switching is one string |
| Sentiment labels | Rent (once) | GPT-6 labelled 3,000 posts | A teacher: 0.79 Macro-F1 on my hand labels, but paying per post for a million posts is not sensible |
| Sentiment model | Own | Chinese RoBERTa (hfl/chinese-roberta-wwm-ext) fine-tuned on those labels; TF-IDF + LR as the cheap baseline | Runs locally on every post every day at zero marginal cost: 0.73 Macro-F1 |
| Data | Free public + own archive | CNINFO, CLS, Eastmoney via AKShare; Guba via own collector | Data cost is zero; the news archive exists only because I collect it daily |
| Evaluation | Own | Harness, answer key, guardrail checklist, results.json | The evidence is the product |

**Where the model is and is not used.** The model reads posts, decides what to search for and whether to search again, and applies the written rules. It never counts posts, computes a return, checks a price limit or sizes an order; those are code.

## Metrics: targeted vs reached

Targets were set before any result was seen (git history of this file).

| Metric | Target | Reached | Source |
|---|---|---|---|
| End-to-end decision pass rate, code check (scripted) | ≥ 80% | | results/results.json |
| End-to-end pass rate, live model A / model B | ≥ 70% | | results/results_live_*.json |
| **False act rate** (paper_trade when the key says do not) | ≤ 5% | | results/results.json |
| Judgement check (reason names the evidence and trigger) | ≥ 75% | | results/judgement_queue.json |
| Descriptor v2 vs v1 pass rate, same model | v2 higher | | results_live_*_v1 vs v2 |
| Sentiment Macro-F1 on hand labels (deployed model) | ≥ 0.65 and > lexicon | | results/sentiment_eval.json |
| Daily bullish share bias (predicted − true) | within ±3 points | | results/sentiment_eval.json |
| Sentiment abstention: error rate abstained vs answered | abstained higher | | results/sentiment_eval.json |
| Guardrail checklist | 10 / 10 | | results/guardrails.json |
| Median / worst turns | ≤ 5 / ≤ 8 | | results/results.json |
| Cost per case, live | < US$0.01 | | results/results_live_*.json |

## Responsible use

- **Intended use:** my own research and paper trading. **Not for:** real automated trading, advice to others, publishing rumour lists that name people.
- **Silent failure:** an announcement about a different matter accepted as evidence. Detection: the check card always shows the evidence title; the judgement check reads every reason.
- **Mitigations that are code, not disclaimers:** the autonomy gate, evidence-required orders, the 30-day search window, the hostile-text screen, step and budget caps, sentiment abstention.
- **Frameworks:** OWASP Top 10 for LLM Applications (LLM01 prompt injection via forum text, LLM06 unbounded consumption, LLM08 system-prompt exposure); Singapore IMDA Model AI Governance Framework (human-in-the-loop at the action); PDPA (no user names or ids are stored); platform access limits respected (sequential requests, 3 s apart; stop on the site's identity check).
