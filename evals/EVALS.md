# Evaluations

Every number in PRODUCT.md comes from a file in `results/`. Each evaluation below says what it tests, how its gold standard was made, how to run it, and what it cannot tell.

## 1. Spike attribution (the core) — `evals/cases.json`, `evals/cause_labels.csv`

**Tests:** for each of the 68 spikes, does the run conclude the same primary cause (A–H) as my hand label?

**Gold:** I labelled every spike from `evals/cause_review.md`, an evidence bundle per spike (most-read posts, onset hour, price and gap z-scores, peers, US peers, indices, top list, filings, articles). The bundle shows raw evidence only; the tools' PASS/FAIL verdicts are deliberately hidden so the label is my judgement, not a copy of the tools. [Labelling date, number labelled, and how: fill in.]

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
