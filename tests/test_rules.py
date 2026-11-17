"""Tests for the business rules that do not need a database.

Run with:  python -m pytest
"""
from datetime import date, datetime
from decimal import Decimal as D

import pytest

from portfolio_app.errors import ApiError
from portfolio_app.jsonutil import instant
from portfolio_app.services import bse_importer, holdings, plans


# ------------------------------------------------------------------ plan engine

def test_moderate_plan_with_no_holdings_follows_target_mix():
    current = [D("0.00")] * 5
    suggested = plans.allocate(current, D("100000.00"), plans.target_for("MODERATE", "NORMAL"))
    assert suggested == [D("30000.00"), D("20000.00"), D("15000.00"), D("5000.00"), D("30000.00")]


def test_budget_goes_to_classes_below_target_and_nothing_is_sold():
    current = [D("100000.00"), D("0.00"), D("0.00"), D("0.00"), D("0.00")]
    budget = D("50000.00")
    suggested = plans.allocate(current, budget, plans.target_for("MODERATE", "NORMAL"))
    assert suggested[0] == D("0.00")            # shares are already above 30%
    assert sum(suggested) == budget             # the whole budget is used
    assert all(amount >= 0 for amount in suggested)


def test_rounding_remainder_keeps_total_equal_to_budget():
    current = [D("1.00"), D("2.00"), D("3.00"), D("4.00"), D("5.00")]
    budget = D("1000.01")
    suggested = plans.allocate(current, budget, plans.target_for("AGGRESSIVE", "NORMAL"))
    assert sum(suggested) == budget


def test_downtrend_moves_five_points_from_shares():
    assert plans.target_for("MODERATE", "DOWNTREND") == [25, 23, 17, 5, 30]
    assert plans.target_for("CONSERVATIVE", "DOWNTREND") == [5, 48, 17, 5, 25]
    assert plans.target_for("MODERATE", "UNKNOWN") == [30, 20, 15, 5, 30]


def test_percentages_and_text_formats():
    assert plans.percentages([D(1), D(1), D(1), D(0), D(0)]) == [D("33.3"), D("33.3"), D("33.3"), D("0.0"), D("0.0")]
    assert plans.percent(D("30.0")) == "30%"
    assert plans.percent(D("0.0")) == "0%"
    assert plans.percent(D("12.5")) == "12.5%"
    assert plans.rupees(D("100000")) == "₹1,00,000.00"
    assert plans.rupees(D("123456789.5")) == "₹12,34,56,789.50"
    assert plans.rupees(D("999")) == "₹999.00"
    assert plans.mix([30, 20, 15, 5, 30]) == ("Shares 30%, Bonds 20%, Commodities-Gold 15%, "
                                              "Commodities-Silver 5% and Mutual Funds 30%")


def test_plan_amount_validation():
    assert plans.valid_amount(D("10.005"), "Budget") == D("10.00")  # half-even, like Java
    with pytest.raises(ApiError):
        plans.valid_amount(D("-1"), "Budget")
    with pytest.raises(ApiError):
        plans.valid_amount(D("1000000000001"), "Budget")


def test_explain_mentions_each_class():
    current = [D("0.00")] * 5
    target = plans.target_for("MODERATE", "NORMAL")
    suggested = plans.allocate(current, D("100000.00"), target)
    reasons = plans.explain("MODERATE", "NORMAL", current, D("100000.00"), target, suggested)
    assert reasons[0].startswith("Your risk appetite is Moderate")
    assert "₹1,00,000.00" in reasons[2]
    assert reasons[-1] == ("After investing, your mix will be Shares 30%, Bonds 20%, Commodities-Gold 15%, "
                           "Commodities-Silver 5% and Mutual Funds 30%.")


# ------------------------------------------------------------------ holdings

def test_decimal_precision_rules():
    assert holdings.fit_decimal(D("1.5"), 24, 8, "units_owned") == D("1.50000000")
    with pytest.raises(ApiError):
        holdings.fit_decimal(D("1.123456789"), 24, 8, "units_owned")   # too many decimals
    with pytest.raises(ApiError):
        holdings.fit_decimal(D("1" + "0" * 16), 24, 8, "units_owned")  # too many digits
    with pytest.raises(ApiError):
        holdings.fit_decimal(None, 24, 8, "units_owned")


def test_holding_validation_normalises_name_and_ticker():
    fields = holdings.validate({"investmentType": " Mutual Funds ", "companyName": "  Straße Fund ",
                                "ticker": "  ", "unitsOwned": D("2"), "averagePurchasePrice": D("10.5")})
    assert fields["type"] == "Mutual Funds"
    assert fields["name"] == "Straße Fund"
    assert fields["normalized"] == "strasse fund"
    assert fields["ticker"] is None
    with pytest.raises(ApiError):
        holdings.validate({"investmentType": "Equity", "companyName": "X",
                           "unitsOwned": D("1"), "averagePurchasePrice": D("1")})


def test_plain_number_text():
    assert holdings.plain(D("100.00000000")) == "100"
    assert holdings.plain(D("12.50000000")) == "12.5"


# ------------------------------------------------------------------ BSE import

HEADER = ("TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,"
          "StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,"
          "SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,"
          "Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4")


def _row(code, symbol, series, name, close, previous):
    return (f"2026-11-16,2026-11-16,CM,BSE,STK,{code},INE000000000,{symbol},{series},,,,,{name},"
            f"100,110,90,{close},{close},{previous},,,,,12345,,,,,,,,,")


def test_parse_bhav_copy():
    text = "﻿" + "\r\n".join([
        HEADER,
        _row("500325", "reliance", "a", '"Reliance Industries, Ltd."', "1500.5", "1490"),
        _row("999999", "ZERO", "A", "Zero close", "0", "1"),  # skipped: close is not positive
        "",
    ])
    rows = bse_importer.parse(text, date(2026, 11, 16))
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == date(2026, 11, 16)
    assert row[1] == "500325"
    assert row[3] == "RELIANCE"
    assert row[4] == "Reliance Industries, Ltd."
    assert row[5] == "A"
    assert row[9] == D("1500.5")
    assert row[11] == 12345


def test_parse_rejects_file_for_another_date():
    text = HEADER + "\n" + _row("500325", "RELIANCE", "A", "Reliance", "1500", "1490")
    with pytest.raises(ValueError):
        bse_importer.parse(text, date(2026, 11, 17))


def test_split_csv_line_handles_quotes():
    assert bse_importer.split_csv_line('a,"b,c","d""e",') == ["a", "b,c", 'd"e', ""]
    with pytest.raises(ValueError):
        bse_importer.split_csv_line('a,"b')


# ------------------------------------------------------------------ JSON

def test_instant_converts_india_time_to_utc():
    assert instant(datetime(2026, 11, 17, 14, 0, 0)) == "2026-11-17T08:30:00Z"
    assert instant(datetime(2026, 11, 17, 14, 0, 0, 120000)) == "2026-11-17T08:30:00.12Z"
