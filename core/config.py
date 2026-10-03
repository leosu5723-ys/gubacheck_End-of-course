"""
GubaCheck - CONFIGURATION
=========================================================================
Every setting that a reader might want to change lives here, and nowhere
else: which model, which backend, the guardrail limits, the decision-rule
thresholds and the paper-broker cost assumptions.

    BACKEND = "scripted"   replays pre-written agent moves. Free,
                           deterministic, no key, no network. This is the
                           default, so `python3 run_eval.py` reproduces
                           the reported numbers on any machine.
    BACKEND = "live"       calls a real model through OpenRouter.
                           Costs money. Needs OPENROUTER_API_KEY.

The thresholds in the RULES block are copied from RULES.md, which was
committed BEFORE any agent result was looked at. Change them there first.
=========================================================================
"""
import os

# -------------------------------------------------------------------------
# BACKEND AND MODEL. Switching model is changing one string.
# -------------------------------------------------------------------------
BACKEND = os.environ.get("GUBACHECK_BACKEND", "scripted")   # "scripted" | "live"
MODEL = os.environ.get("GUBACHECK_MODEL", "openai/gpt-4o-mini")
BASE_URL = "https://openrouter.ai/api/v1"
API_KEY = os.environ.get("OPENROUTER_API_KEY", "")           # never hard-code a key

# Prices in US dollars per MILLION tokens for MODEL. Re-check on the vendor
# page before quoting them; record the date you checked.
PRICE_IN = float(os.environ.get("GUBACHECK_PRICE_IN", "0.15"))
PRICE_OUT = float(os.environ.get("GUBACHECK_PRICE_OUT", "0.60"))
PRICES_CHECKED = os.environ.get("GUBACHECK_PRICES_CHECKED", "YYYY-MM-DD")

# -------------------------------------------------------------------------
# GUARDRAIL LIMITS. Set from evidence (see EVALS.md: turn distribution),
# not from a round number.
# -------------------------------------------------------------------------
MAX_TURNS = 10                # worst legitimate scripted run is 8 tool turns (results/results.json)
MAX_TOKENS_PER_RUN = 80000       # worst legitimate scripted run ~55k tokens (estimate); cap = that + ~45%
AUTONOMY = "confirm"          # "suggest" | "confirm" | "act"
#   suggest - the agent proposes, I place every order myself
#   confirm - the agent does everything except the order, which waits for my yes
#   act     - the agent places the paper order itself

# -------------------------------------------------------------------------
# DECISION RULES (mirrors RULES.md - edit RULES.md first)
# -------------------------------------------------------------------------
# Spike detection (forum activity, the full-year post data)
SPIKE_HEAT_RATIO = 2.0        # posts today >= 2x the mean of the previous 20 days
SPIKE_BULL_SHIFT = 0.10       # bullish share >= its 20-day mean + 10 points
SPIKE_MIN_POSTS = 30          # ignore thin days
SPIKE_BASELINE_DAYS = 20      # trailing window (calendar days with posts)
SPIKE_MIN_HISTORY = 10        # need at least 10 prior days for a baseline
EPISODE_GAP_DAYS = 5          # spikes within 5 days of a previous spike = same episode

# v4 anomaly tests (RULES.md section 0)
Z_WINDOW = 120                # trading days of history for every z-score
Z_POSTS = 2.0                 # log posts z for a spike
Z_BULL = None                 # no direction condition (RULES.md 0.1 change log); bull-share z is reported
Z_MIN_OBS = 20                # minimum history (trading days) before a z-score is used
Z_ABNORMAL = 2.0              # price, gap, index, US peer
Z_PARTIAL = 1.5               # index PARTIAL band
PCTL_MONEY = 95               # top-list / turnover percentile
CAUSES = ["A", "B", "C", "D", "E", "F", "G"]
WEIGHT = {"PASS": 3.0, "PARTIAL": 1.0, "FAIL": 0.2}
STOP_UNTESTED_MASS = 0.20
SCORE_FLOOR = 0.5             # raw scores below this count as 0.5: no cause starts at exactly 0 (RULES.md 0.3 change)
MAX_CAUSE_CALLS = 5
CHEAP_CAUSES = ["C", "D", "E", "G"]   # tie-break: numbers before reading

# Cross-check only: Eastmoney popularity-rank jumps (pipeline/candidates.py)
SPIKE_MAX_RANK = 200
SPIKE_RANK_RATIO = 3.0

# Evidence search
SEARCH_WINDOW_MAX_DAYS = 30   # a tool refuses wider windows (stale evidence)
SEARCH_MAX_RESULTS = 5
NEWS_CONTENT_CHARS = 200      # observation trimming

# Event types I am willing to act on
ALLOWED_EVENT_TYPES = ["buyback", "shareholder_increase",
                       "earnings_preincrease", "major_contract"]

# Forward watch and backtest (RULES.md section 2)
WATCH_TRADING_DAYS = 10
EXIT_HORIZONS = [1, 2, 3, 5, 10, 15, 20]
NEVER_BULLISH_TYPES = ["share_issuance", "shareholder_decrease", "lockup_expiry"]
BENCHMARK = "000300"          # CSI 300

# Tradability
PRICED_IN_PCT = 15.0          # pre-event 5-day gain above this -> priced_in

# -------------------------------------------------------------------------
# PAPER BROKER (A-share frictions). Commission varies by broker.
# -------------------------------------------------------------------------
CAPITAL_CNY = 100_000
POSITION_PCT = 0.10           # one order uses at most 10% of capital
LOT_SIZE = 100
COMMISSION_RATE = 0.00025     # both sides
COMMISSION_MIN_CNY = 5.0
STAMP_DUTY_SELL = 0.0005      # sell side only
TRANSFER_FEE = 0.00001        # both sides
HOLD_DAYS = 20                # exit after N trading days at the close

# -------------------------------------------------------------------------
# WHERE THINGS LIVE
# -------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("GUBACHECK_DATA", os.path.join(ROOT, "data", "snapshot"))
EVALS_DIR = os.path.join(ROOT, "evals")
RESULTS_DIR = os.path.join(ROOT, "results")


def summary():
    """One line printed at the top of every run, so every number on screen
    can be traced to the backend and model that produced it."""
    where = "scripted (free, deterministic)" if BACKEND == "scripted" else "LIVE (costs money)"
    model = "-" if BACKEND == "scripted" else MODEL
    return ("backend=%s | model=%s | max_turns=%d | autonomy=%s | data=%s"
            % (where, model, MAX_TURNS, AUTONOMY, DATA_DIR))
