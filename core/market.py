"""
GubaCheck - A-SHARE MARKET RULES AND EVENT TYPING
=========================================================================
Deterministic helpers. No model is involved in anything in this file:
price limits, board detection and announcement typing are rules that can
be checked, so they are code.

    board_of(code)            main | gem | star | bse
    limit_up_price(...)       the price at which a stock is limit-up
    event_type_of(title)      announcement title -> event type

The event typing works on CNINFO titles, which are highly standardised.
It is also the non-AI baseline the README refers to: if a title rule can
type an announcement, a model is not needed for that step.
=========================================================================
"""
import re


def board_of(code):
    """Board from the stock code prefix. Decides the daily price limit."""
    if code.startswith("688"):
        return "star"
    if code.startswith(("300", "301")):
        return "gem"
    if code.startswith(("8", "4", "920")):
        return "bse"
    return "main"


_LIMIT = {"main": 0.10, "gem": 0.20, "star": 0.20, "bse": 0.30}


def limit_up_price(prev_close, board, is_st=False):
    """Exchange limit-up price, rounded to the 0.01 tick.

    WATCH OUT   ST stocks on the main board move at most 5%. Getting this
                wrong makes a limit-up open look buyable, which is the most
                common source of fake profit in A-share backtests.
    """
    pct = 0.05 if (is_st and board == "main") else _LIMIT[board]
    return round(prev_close * (1 + pct) + 1e-9, 2)


# Ordered: the first matching rule wins. Each rule is (type, include, exclude).
_RULES = [
    ("clarification",        r"澄清|异常波动|风险提示",                 None),
    ("lockup_expiry",        r"限售股.{0,6}上市流通|解除限售|解禁",       None),
    ("share_issuance",       r"向特定对象发行|非公开发行|定向增发|配售|发行境外上市外资股|H股.{0,8}(发行|上市|定价)|公开发行价格", None),
    ("buyback",              r"回购.*(方案|预案|计划|报告书)|以集中竞价.*回购", r"注销限制性|回购注销"),
    ("shareholder_decrease", r"减持",                                    None),
    ("shareholder_increase", r"增持",                                    None),
    ("earnings_preincrease", r"业绩预增|预增|扭亏|大幅(上升|增长)",        None),
    ("earnings_forecast",    r"业绩预告|业绩快报",                        None),
    ("major_contract",       r"中标|重大合同|签订.*合同|项目.*合同",        None),
    ("restructuring",        r"重组|发行股份购买|收购|吸收合并",            None),
]


def event_type_of(title):
    """Classify one announcement title.

    RETURNS     {"type": str, "ambiguous": bool}
    AMBIGUOUS   True for "earnings_forecast": the title says a forecast was
                published but not its direction, so the type cannot be
                decided from the title alone. The decision rules treat an
                ambiguous type as not allowed rather than guessing.
    """
    for etype, include, exclude in _RULES:
        if re.search(include, title) and not (exclude and re.search(exclude, title)):
            return {"type": etype, "ambiguous": etype == "earnings_forecast"}
    return {"type": "other", "ambiguous": False}
