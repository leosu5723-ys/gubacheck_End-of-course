"""
GubaCheck - COST TO SERVE (three layers, Class 5)
=========================================================================
    python3 -m pipeline.cost_model

Every unit cost is read from a results file produced by a real run; the
only assumptions are the volumes and the price range, both printed.

Layer 1  per-unit variable   sentiment per 1,000 posts (local model)
                             filing judgement per filing (RAG + LLM, measured)
                             attribution per spike (live arm, measured; scripted
                             estimate until the live run exists)
Layer 2  per-unit expected   variable cost / success rate + failure cost
                             (a failed or premature run is re-done by hand:
                             MINUTES_PER_MANUAL_CHECK of my time)
Layer 3  fixed monthly       data feeds (free), hosting (local / free CI)

Volumes are derived from the year of data: spikes per stock-month and
non-procedural filings per stock-month, scaled to a watchlist size.
Sensitivity: model price x0.5 / x1 / x2, watchlist 10 / 100 / 1,000 stocks.
=========================================================================
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

R = os.path.join(ROOT, "results")
MINUTES_PER_MANUAL_CHECK = 10
HOURLY_VALUE_USD = 20.0          # my time, for the expected-cost layer


def load(name):
    p = os.path.join(R, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def latest(pattern):
    files = sorted(glob.glob(os.path.join(R, pattern)))
    return json.load(open(files[-1], encoding="utf-8")) if files else None


def main():
    judge = load("judge_eval.json") or {}
    rag = judge.get("methods", {}).get("llm_rag", {})
    per_filing = rag["usd_total"] / rag["calls"] if rag.get("calls") else None
    bert = load("bert_predict_stats.json") or {}
    pps = [v["posts_per_second"] for v in bert.get("stocks", {}).values()]
    live = latest("results_agent_live_*.json")
    scripted = latest("results_keyword.json")
    src = live or scripted
    att = src["summary"] if src else {}
    per_spike = att.get("total_cost_usd", 0) / att["runs"] if att.get("runs") else None
    bill = load("billing.json") or {}
    basis = "tokens x list price"
    model = "deepseek/deepseek-v4.1-flash"
    if bill.get("full_arm_runs", {}).get(model):    # the provider's bill beats tokens x list price
        per_spike = bill["by_model_usd"][model] / bill["full_arm_runs"][model]
        basis = "billed upper bound (results/billing.json)"
    success = att.get("accuracy")

    spikes = json.load(open(os.path.join(ROOT, "data", "snapshot", "spikes.json"), encoding="utf-8"))
    n_spikes = sum(1 for s in spikes if not s.get("synthetic"))
    anns = json.load(open(os.path.join(ROOT, "data", "snapshot", "announcements.json"), encoding="utf-8"))
    n_filings = sum(1 for a in anns if not a["procedural"])
    stock_months = 10 * 11                     # 10 stocks, Nov 2025 - Sep 2026 with z-scores available
    spikes_per_sm = n_spikes / stock_months
    filings_per_sm = n_filings / (10 * 12)

    report = {"assumptions": {"minutes_per_manual_check": MINUTES_PER_MANUAL_CHECK,
                              "hourly_value_usd": HOURLY_VALUE_USD,
                              "attribution_cost_source": ("live runs, " + basis) if live else "scripted estimate (no live run yet)"},
              "layer1_variable": {"sentiment_usd_per_1000_posts": 0.0,
                                  "sentiment_posts_per_second_local": round(sum(pps) / len(pps), 1) if pps else None,
                                  "filing_judgement_usd_per_filing": round(per_filing, 6) if per_filing else None,
                                  "attribution_usd_per_spike": round(per_spike, 6) if per_spike is not None else None},
              "volumes_per_stock_month": {"spikes": round(spikes_per_sm, 3), "non_procedural_filings": round(filings_per_sm, 2)},
              "scenarios": []}
    for stocks in (10, 100, 1000):
        for mult in (0.5, 1.0, 2.0):
            var = stocks * (spikes_per_sm * (per_spike or 0) + filings_per_sm * (per_filing or 0)) * mult
            fail_rate = 1 - success if success is not None else 0.5
            expected = var + stocks * spikes_per_sm * fail_rate * MINUTES_PER_MANUAL_CHECK / 60 * HOURLY_VALUE_USD
            report["scenarios"].append({"stocks": stocks, "price_multiplier": mult,
                                        "variable_usd_month": round(var, 3),
                                        "expected_usd_month_incl_manual_rework": round(expected, 2),
                                        "fixed_usd_month": 0.0})
    json.dump(report, open(os.path.join(R, "cost_model.json"), "w"), indent=1)
    print(json.dumps(report["layer1_variable"], indent=1))
    print("volumes per stock-month:", report["volumes_per_stock_month"])
    for s in report["scenarios"]:
        if s["price_multiplier"] == 1.0:
            print("  %4d stocks: variable US$%.2f / month, expected incl. manual rework US$%.2f / month"
                  % (s["stocks"], s["variable_usd_month"], s["expected_usd_month_incl_manual_rework"]))


if __name__ == "__main__":
    main()
