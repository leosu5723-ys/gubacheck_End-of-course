# Evaluations

Every number in PRODUCT.md comes from a file in `results/`. Each evaluation below says what it tests, how its gold standard was made, how to run it, and what it cannot tell.

## 1. Spike attribution (the core) — `evals/cases.json`, `evals/cause_labels.csv`

**Tests:** for each of the 68 spikes, does the run conclude the same primary cause (A–H) as my hand label?

**Gold:** I labelled every spike from `evals/cause_review.md`, an evidence bundle per spike (most-read posts, onset hour, price and gap z-scores, peers, US peers, indices, top list, filings, articles). The bundle shows raw evidence only; the tools' PASS/FAIL verdicts are deliberately hidden so the label is my judgement, not a copy of the tools. All 68 spikes were labelled by hand on 2026-10-03/04, before any live run was graded; gold was not changed after seeing model output.

**Arms** (RULES.md 0.4), same spikes, same tools, same stop rule:

| Arm | Scores from | Revises? | Stop rule | Backend |
|---|---|---|---|---|
| exhaustive | — (uniform) | — | none: all seven tests | scripted |
| keyword | keyword counts in posts (non-AI) | no | yes | scripted |
| routing | LLM, once | no | yes | live |
| **agent** | LLM | yes, after each test | yes | live |

**Metrics** (`results/results_<arm>*.json`): primary-cause accuracy, overall and by period (observe < 2026-04-01 ≤ check); the always-H baseline; mean cause tests; tokens and cost; over-investigation (tests attempted after STOP held); premature stops (the gold cause was never tested); model-vs-code disagreement (the model's stated primary vs the posterior's).

```bash
python3 run_eval.py --arm=keyword
python3 run_eval.py --arm=exhaustive
GUBACHECK_BACKEND=live python3 run_eval.py --arm=agent   --workers=4
GUBACHECK_BACKEND=live python3 run_eval.py --arm=routing --workers=4
```

**Results** (68 spikes, one live trial each, model deepseek/deepseek-v4.1-flash, 2026-10-04):

| Arm | Accuracy | Macro-F1 | Observe / check | Tests per spike | Cost (68 spikes) | Premature stops |
|---|---|---|---|---|---|---|
| always-B (majority) | 69.1% | 0.12 | — | — | — | — |
| always-H | 7.4% | — | — | — | — | — |
| keyword | 22.1% | 0.17 | 16% / 26% | 4.59 | no LLM | 36 |
| exhaustive | 47.1% | 0.22 | 52% / 44% | 7.00 | no LLM | 0 |
| routing (live) | **60.3%** | 0.36 | 64% / 58% | 4.29 | see below | 0 |
| agent (live) | 55.9% | **0.37** | 52% / 58% | 4.38 | see below | 3 |

**Cost.** The OpenRouter bill for DeepSeek V4.1 Flash on this key is US$1.23 in total — the two full arms (136 runs) plus trial runs and tests — so the full arms cost **at most US$0.009 per spike** (`results/billing.json`). The `cost_usd` fields in the results files are tokens × list price ($0.30 / $1.20) and overstate the bill (US$1.68 for the two arms, more than the whole key): every turn re-sends the conversation and the provider bills cached input at a discount. Lesson: price × tokens is not a bill; since 2026-10-04 every live call records the billed cost.

**Single-run model comparison** (`python3 -m pipeline.model_compare SPK-300308-20260728 --models=… [--arm=agent]`, `results/model_single_*.json`). One spike — 中际旭创 2026-07-28, my label C, where C, D and B all PASS — one live run per model and arm, billed:

| Model | Arm | Primary | Tests in order | Tokens in / out | Billed US$ | Seconds |
|---|---|---|---|---|---|---|
| DeepSeek V4.1 Flash | routing | D ✗ | A D C B | 30.9k / 1.5k | 0.0019 | 23 |
| | agent | D ✗ | A D C | 28.2k / 1.9k | 0.0014 | 22 |
| Claude Haiku 4.5 | routing | C ✓ | A C D B | 39.1k / 1.8k | 0.0479 | 26 |
| | agent | C ✓ | A C D B | 41.8k / 1.7k | 0.0506 | 27 |
| DeepSeek V4 Flash | routing | C ✓ | A C D B | 32.4k / 2.2k | 0.0037 | 13 |
| | agent | D ✗ | A D C | 29.1k / 2.3k | 0.0038 | 15 |

What it shows: (1) **the cause tested first wins** — in all six runs the primary is whichever of C and D was tested first, because every PASS is multiplied by the same 3 and the order of the priors survives; when several causes pass, the conclusion comes from the model's opening clue scores, not from the strength of the evidence. (2) No model revised its scores, Haiku included — "the agent behaves as routing" is not a DeepSeek quirk. (3) Haiku costs ~30× more per run here (no cache discount). (4) One spike says how a model behaves and what it costs, not which is more accurate; V4 Flash gave different answers in its two arms.

Paired (same spike, exact McNemar): routing vs exhaustive 11 vs 2 cases right only in one arm (p = 0.02); agent vs exhaustive 8 vs 2 (p = 0.11); **agent vs routing 3 vs 6 (p = 0.51)**.

What the numbers say:
- **Accuracy alone is misleading.** 47 of 68 labels are B, so "always B" scores 69%, above every arm. Macro-F1 shows the arms do separate causes (0.37 vs 0.12), but D (0/3) and F (0/2) are never recovered by any arm.
- **The agent did not behave as an agent.** It used `revise_scores` in 1 of 68 runs, so in practice it was routing, and it scored slightly worse (not significant). On this data, routing is the right rung.
- **The main error is B → H.** The B tool returned PARTIAL on 13 of the agent's 14 gold-B spikes concluded H; under the PASS-only rule a PARTIAL cannot become primary. When the model's stated primary differed from the code's posterior primary, the model was right 4 / 7 (agent) and 7 / 12 (routing) times, and the code 0 and 1 times — the model reads PARTIAL evidence better than the strict rule.
- A failed first run (45 of 136 cases crashed because the model passed an unexpected `spike_id` to `score_causes`) was fixed in the tool layer and only the failed cases were re-run from the checkpoints.

**What this cannot tell:** whether my label is right — it is one person's judgement from public evidence; live runs are one trial per spike; 68 spikes over eight causes leave some causes with a handful of cases.

## 2. What happened after each cause — `results/cause_backtest_<source>.json`

Entry at the next open after the spike day; exits at the close of +1, +2, +3, +5, +10, +15, +20 trading days; net of fees; excess vs CSI 300. Grouped by cause (gold labels for the report), split by period (observe / check) and by spike direction. A pattern counts only if it appears in both periods. Sample sizes are printed with every number.

```bash
python3 -m pipeline.cause_backtest gold
```

## 3. Forum sentiment — `results/sentiment_eval.json`

99 titles labelled by me (7 marked unsure, excluded) are the test set; 3,000 other titles labelled by GPT-6 are the training set. Compared: majority, keyword lexicon, TF-IDF + LR, fine-tuned RoBERTa, GPT-6 directly. Macro-F1 with bootstrap CIs; abstention; daily bullish-share bias. *History:* the first test labels were LLM-made and were withdrawn (DATA.md).

## 4. Filing judge and RAG ablation — `results/judge_eval.json`

30 substantive filings labelled by me (main test) + 40 random filings (37 neutral; measures false-bullish calls). Compared: title rule, LLM on the text, LLM + chunked RAG with forced same-period forecast, chunked RAG without the forced document, whole-document retrieval.

## 5. Guardrail checklist — `evals/guardrail_cases.json` → `results/guardrails.json`

| id | Wrong behaviour it catches | Guard |
|---|---|---|
| G1 | obeys a forum post that says buy now (LLM01) | hostile-text block |
| G2 | trades on a fake announcement id quoted in a post | hostile text / evidence required |
| G3 | a post asking for the system prompt goes unflagged (LLM08) | hostile-text screen |
| G4 | keeps testing causes after STOP held | stop-rule refusal |
| G5 | runs more than five cause tests | 5-test cap |
| G6 | repeats the same test | de-duplication |
| G7 | unbounded spend on one spike (LLM06) | budget ceiling |
| G8 | re-scores in the routing arm | arm rule |
| G9 | places an order I declined | gate |
| G10 | buys on a share issuance | never-bullish guard |

G1–G3 use three synthetic red-team spikes (`evals/redteam_posts.json`): a real spike's statistics with hostile posts substituted. They are never in the evaluation set or the backtests.

```bash
python3 run_guardrails.py
```

## 6. Reproduced failures — `demo_failures.py`

1. **Loop control, minus de-duplication:** the same test repeated five times; each repeat re-weights the posterior, so evidence is counted several times and the test budget is spent — with no error.
2. **Tool interface, minus the US-before-open rule:** 15 of 68 D verdicts change, using US sessions that closed after the A-share move they claim to explain. The fix is in the tool, not the prompt.

## Earlier designs

The single-shot decision key and the forward-watch backtest (RULES.md "Earlier designs") are kept with their results; they are not part of the v4 evaluation.
