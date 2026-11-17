""""Create your own plan": suggests how to split a new investment budget across
Shares, Bonds, Commodities-Gold, Commodities-Silver and Mutual Funds.

This is a transparent rule-based engine, not AI:
1. The user's risk appetite selects a target mix (TARGETS below).
2. If the BSE Sensex fell on each of the last 3 trading days, 5 points move from
   Shares to Bonds (+3) and Commodities-Gold (+2) as a defensive tilt.
3. The budget is spent where the user is furthest below the target mix, in
   proportion to each shortfall. Nothing is sold: classes already above target
   get nothing.
"""
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal

from .. import repositories as repo
from ..errors import ApiError
from ..jsonutil import instant

RISK_PROFILES = ("CONSERVATIVE", "MODERATE", "AGGRESSIVE")
KEYS = ("shares", "bonds", "gold", "silver", "mutualFunds")
LABELS = ("Shares", "Bonds", "Commodities-Gold", "Commodities-Silver", "Mutual Funds")

# Target mix in percent, order: shares, bonds, gold, silver, mutual funds
TARGETS = {
    "CONSERVATIVE": (10, 45, 15, 5, 25),
    "MODERATE": (30, 20, 15, 5, 30),
    "AGGRESSIVE": (45, 10, 10, 5, 30),
}

# Sensex-tracking ETFs in the BSE Bhav Copy, most liquid first (same list as the Dashboard badge)
SENSEX_TRACKERS = ("SENSEXBEES", "SBISENSEX", "HDFCSENSEX", "SENSEXBETA")
TREND_DAYS = 3
RECENT_PLAN_LIMIT = 10
MAX_AMOUNT = Decimal("1000000000000")  # ₹1 lakh crore
HUNDRED = Decimal(100)
TEN_PLACES = Decimal("1E-10")
PAISE = Decimal("0.01")
ZERO = Decimal(0)


def create(connection, user_id, risk_profile, current_amounts, budget_value):
    """current_amounts: dict with the KEYS (values are Decimal or None)."""
    risk = "MODERATE" if risk_profile is None else risk_profile.strip().upper()
    if risk not in RISK_PROFILES:
        raise _invalid("Choose a risk appetite: Conservative, Moderate or Aggressive.")
    given = current_amounts or {}
    current = [valid_amount(given.get(key) if given.get(key) is not None else ZERO, LABELS[i] + " amount")
               for i, key in enumerate(KEYS)]
    budget = valid_amount(budget_value, "Budget")
    if budget <= 0:
        raise _invalid("Enter a budget greater than ₹0.")

    signal = market_signal(connection)
    target = target_for(risk, signal)
    suggested = allocate(current, budget, target)
    reasons = explain(risk, signal, current, budget, target, suggested)

    plan_id = repo.create_plan(connection, user_id, risk, current, budget, suggested, signal, reasons)
    return to_result(repo.find_plan(connection, plan_id, user_id))


def recent(connection, user_id):
    return [to_result(plan) for plan in repo.find_recent_plans(connection, user_id, RECENT_PLAN_LIMIT)]


def to_result(plan):
    current = plan["current"]
    suggested = plan["suggested"]
    after = [c + s for c, s in zip(current, suggested)]
    target = target_for(plan["risk_profile"], plan["market_signal"])
    return {
        "planId": plan["plan_id"],
        "riskProfile": plan["risk_profile"],
        "budget": plan["budget"],
        "current": _amounts(current),
        "suggested": _amounts(suggested),
        "targetPercent": _amounts([Decimal(t) for t in target]),
        "currentPercent": _amounts(percentages(current)),
        "resultingPercent": _amounts(percentages(after)),
        "marketSignal": plan["market_signal"],
        "reasons": plan["reasons"],
        "createdAt": instant(plan["created_at"]),
    }


def market_signal(connection):
    """DOWNTREND if a Sensex ETF fell on each of the last 3 trading days; UNKNOWN without enough data."""
    for symbol in SENSEX_TRACKERS:
        changes = repo.find_recent_changes(connection, symbol, TREND_DAYS)
        if len(changes) == TREND_DAYS:
            fell_every_day = all(change["close_price"] < change["previous_close"] for change in changes)
            return "DOWNTREND" if fell_every_day else "NORMAL"
    return "UNKNOWN"


def target_for(risk, signal):
    target = list(TARGETS[risk])
    if signal == "DOWNTREND":
        moved = min(5, target[0])
        target[0] -= moved
        target[1] += moved - 2
        target[2] += 2
    return target


def allocate(current, budget, target):
    """Splits the budget in proportion to how far each class is below its target share."""
    total_after = sum(current, ZERO) + budget
    gaps = []
    for i in range(5):
        desired = _divide(total_after * target[i], HUNDRED)
        gaps.append(max(desired - current[i], ZERO))
    gap_total = sum(gaps, ZERO)
    raw = []
    for i in range(5):
        # gap_total >= budget > 0 always (the shortfalls add up to at least the new money)
        raw.append(_divide(budget * gaps[i], gap_total) if gap_total > 0
                   else _divide(budget * target[i], HUNDRED))
    # Round to paise; give any rounding remainder to the largest share so the total equals the budget
    rounded = [value.quantize(PAISE, rounding=ROUND_DOWN) for value in raw]
    largest = 0
    for i in range(5):
        if raw[i] > raw[largest]:
            largest = i
    rounded[largest] += budget.quantize(PAISE, rounding=ROUND_DOWN) - sum(rounded, ZERO)
    return rounded


def explain(risk, signal, current, budget, target, suggested):
    reasons = [f"Your risk appetite is {risk.title()}, so the target mix is {mix(TARGETS[risk])}."]
    if signal == "DOWNTREND":
        reasons.append("The BSE Sensex fell on each of the last 3 trading days, so 5% of the target moved "
                       "from Shares to Bonds (+3%) and Commodities-Gold (+2%) to lower risk. "
                       f"Adjusted target: {mix(target)}.")
    elif signal == "NORMAL":
        reasons.append("The BSE Sensex has not fallen 3 trading days in a row, so no defensive "
                       "adjustment was made.")
    else:
        reasons.append("There is not enough recent BSE data to check the Sensex trend, so no market "
                       "adjustment was made.")
    total = sum(current, ZERO)
    current_pct = percentages(current)
    if total == 0:
        reasons.append(f"You have no investments recorded yet, so the budget of {rupees(budget)} "
                       "is split by the target mix.")
    else:
        reasons.append(f"The budget of {rupees(budget)} goes first to the asset classes that are furthest "
                       "below their target share. Nothing is sold.")
    for i in range(5):
        label = LABELS[i]
        if suggested[i] > 0:
            detail = "" if total == 0 else f" (now {percent(current_pct[i])} of your money, target {target[i]}%)"
            reasons.append(f"{label}: invest {rupees(suggested[i])}{detail}.")
        elif total > 0:
            reasons.append(f"{label}: nothing new, because it is already at or above its target "
                           f"({percent(current_pct[i])} now, target {target[i]}%).")
    after_pct = percentages([c + s for c, s in zip(current, suggested)])
    parts = [f"{LABELS[i]} {percent(after_pct[i])}" for i in range(5)]
    reasons.append("After investing, your mix will be " + _join(parts) + ".")
    return reasons


def percentages(values):
    total = sum(values, ZERO)
    if total == 0:
        return [ZERO] * 5
    return [(value * HUNDRED / total).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN) for value in values]


def valid_amount(value, field):
    if value is None:
        raise _invalid(field + " is required.")
    if value < 0:
        raise _invalid(field + " cannot be negative.")
    if value > MAX_AMOUNT:
        raise _invalid(field + " is too large.")
    return value.quantize(PAISE, rounding=ROUND_HALF_EVEN)


def mix(target):
    return _join([f"{LABELS[i]} {target[i]}%" for i in range(5)])


def rupees(amount):
    """Indian rupee format with Indian digit grouping, e.g. ₹1,00,000.00."""
    amount = amount.quantize(PAISE, rounding=ROUND_HALF_EVEN)
    sign = "-" if amount < 0 else ""
    whole, fraction = format(abs(amount), "f").split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return f"{sign}₹{whole}.{fraction}"


def percent(value):
    text = format(value.normalize(), "f")
    return ("0" if text in ("-0", "") else text) + "%"


def _join(parts):
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _divide(numerator, denominator):
    return (numerator / denominator).quantize(TEN_PLACES, rounding=ROUND_HALF_EVEN)


def _amounts(values):
    return dict(zip(KEYS, values))


def _invalid(message):
    return ApiError(400, "invalid_plan", message)
