# GubaCheck

**Verifies A-share stock-forum hype against official disclosures before I act.**

When discussion of one of my stocks suddenly spikes on the Eastmoney forum (Guba), GubaCheck reads the posts, searches the official disclosure site (CNINFO) and the news feeds for evidence, and reaches one of three decisions: place a paper trade (only after my confirmation), wait for a named official confirmation, or flag the spike as "do not chase". Every decision cites its evidence.

Product documentation (persona, input/output, architecture, metrics targeted vs reached): **[PRODUCT.md](PRODUCT.md)**. The decision rules: **[RULES.md](RULES.md)**. Data: **[data/DATA.md](data/DATA.md)**. Evaluations: **[evals/EVALS.md](evals/EVALS.md)**.

---

## Run it (no key, no network, standard library only)

Python 3.9+.

```bash
python3 run_eval.py                  # full evaluation set, graded -> results/results.json
python3 run_eval.py SPK-600519-20260918   # one case, every turn shown
python3 run_guardrails.py            # guardrail checklist -> results/guardrails.json
python3 demo_failures.py             # the two reproduced failures, before/after
python3 run_eval.py --prompt         # exactly what the model is told
python3 -m unittest discover tests   # unit tests on a synthetic fixture
```

These all use the **scripted** backend: the agent's moves are replayed from `evals/scripted_moves.json` while the tools run for real against the frozen data in `data/snapshot/`. Results are identical on every machine.

## Live runs (costs money)

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-...
GUBACHECK_BACKEND=live GUBACHECK_MODEL=openai/gpt-4o-mini python3 run_eval.py
GUBACHECK_BACKEND=live python3 run_eval.py --v1      # weak tool descriptors, same model
python3 -m pipeline.sentiment eval --llm             # sentiment: LLM few-shot vs TF-IDF
```

Live results are written to `results/results_live_<model>.json`, with token counts taken from the API's usage field.

## Rebuild the data from scratch

```bash
pip install -r requirements.txt
# 1. edit data/watchlist.json
python3 -m collectors.guba 600519 2026-06-01 2026-09-30          # per stock
python3 -m collectors.market_data cninfo 600519 2026-05-01 2026-09-30
python3 -m collectors.market_data prices 600519 2026-05-01 2026-10-31
python3 -m collectors.market_data news 600519 000858             # latest items only
# 2. label posts, train the sentiment model
python3 -m pipeline.sentiment sample 300      # -> data/labels/to_label.csv
python3 -m pipeline.sentiment eval            # after labelling -> results/sentiment_eval.json
python3 -m pipeline.sentiment train           # -> results/sentiment_model.pkl
# 3. freeze the snapshot and detect spikes
python3 -m pipeline.build_snapshot 2026-06-01 2026-09-30
```

Daily collection (the news feeds keep no history, so this is what builds the news archive): `python3 -m collectors.daily`, scheduled after the close.

## Repository map

| Path | What it is |
|---|---|
| `core/agent.py` | The ReAct loop, instrumented (turns, tokens, cost, tool calls, guard events) |
| `core/tools.py` | Six tools with documentation blocks and model-facing descriptors |
| `core/guardrails.py` | Step cap, budget ceiling, de-duplication, autonomy gate, hostile-text screen, evidence-required order |
| `core/prompt.py` | Decision rules + descriptors -> system prompt (v1 and v2) |
| `core/backends.py` | Scripted and live backends; the only vendor-specific code |
| `core/paper_broker.py` | Local order simulation with A-share rules (next-day open, limit-up, lots, fees) |
| `core/market.py` | Price limits by board, announcement-title event typing |
| `core/harness.py` | Answer key, code check, judgement queue, summary metrics |
| `collectors/` | Guba, CNINFO, news and price collectors |
| `pipeline/` | Sentiment classifier and evaluation; snapshot builder and spike detector |
| `data/` | Watchlist, labels, frozen snapshot (raw collections are not committed) |
| `evals/` | Answer key, scripted moves, guardrail cases |
| `results/` | Every number quoted in PRODUCT.md and the report |

## Intended use

Personal research and paper trading only. GubaCheck never places a real order, does not give investment advice to anyone, and does not publish lists of rumours. See PRODUCT.md, "Responsible use".

## Acknowledgements

The agent-loop, guardrail and scripted/live backend structure is adapted from the PE6201 course starter code; the problem, tools, data, rules, evaluation set and results are my own. An AI coding assistant was used during development; I can explain every module.
