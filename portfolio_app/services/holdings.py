"""Adding, editing, deleting and selling holdings."""
import unicodedata
from decimal import Decimal, localcontext

import pymysql

from .. import repositories as repo
from ..db import DUPLICATE_KEY, is_error
from ..errors import ApiError
from . import portfolios

INVESTMENT_TYPES = {"Bonds", "Commodities-Gold", "Commodities-Silver", "Mutual Funds", "Stocks/Shares"}


def list_for(connection, user_id, portfolio_id):
    portfolios.require_owned(connection, user_id, portfolio_id)
    return repo.find_holdings(connection, portfolio_id, user_id)


def list_sold(connection, user_id, portfolio_id):
    portfolios.require_owned(connection, user_id, portfolio_id)
    return repo.find_sold_holdings(connection, portfolio_id, user_id)


def add(connection, user_id, portfolio_id, data):
    portfolios.require_owned(connection, user_id, portfolio_id)
    fields = validate(data)
    if repo.holding_exists_with_same_details(connection, user_id, fields["type"], fields["normalized"],
                                             fields["ticker"], fields["units"], fields["price"]):
        raise _duplicate()
    try:
        holding_id = repo.create_holding(connection, user_id, portfolio_id, fields["type"], fields["name"],
                                         fields["normalized"], fields["ticker"], fields["units"], fields["price"])
    except pymysql.err.IntegrityError as exception:
        if is_error(exception, DUPLICATE_KEY):
            raise _duplicate()
        raise
    return repo.find_holding(connection, holding_id, user_id)


def update(connection, user_id, holding_id, data):
    if repo.find_holding(connection, holding_id, user_id) is None:
        raise _not_found()
    fields = validate(data)
    if repo.holding_exists_with_same_details(connection, user_id, fields["type"], fields["normalized"],
                                             fields["ticker"], fields["units"], fields["price"], holding_id):
        raise _duplicate()
    try:
        repo.update_holding(connection, holding_id, user_id, fields["type"], fields["name"], fields["normalized"],
                            fields["ticker"], fields["units"], fields["price"])
    except pymysql.err.IntegrityError as exception:
        if is_error(exception, DUPLICATE_KEY):
            raise _duplicate()
        raise
    holding = repo.find_holding(connection, holding_id, user_id)
    if holding is None:
        raise _not_found()
    return holding


def delete(connection, user_id, holding_id):
    if repo.delete_holding(connection, holding_id, user_id) == 0:
        raise _not_found()


def sell(connection, user_id, holding_id, units_to_sell=None):
    """Sells all units (units_to_sell is None or equal to the units owned) or part of them."""
    holding = repo.find_holding(connection, holding_id, user_id)
    if holding is None:
        raise _not_found()
    current_units = holding["unitsOwned"]
    if units_to_sell is None or units_to_sell == current_units:
        if repo.move_holding_to_sold(connection, holding_id, user_id) == 0:
            raise _not_found()
        return
    if units_to_sell <= 0:
        raise ApiError(400, "invalid_units", "Units to sell must be greater than zero.")
    if units_to_sell > current_units:
        raise ApiError(400, "invalid_units",
                       f"Cannot sell more units than currently owned ({plain(current_units)}).")
    if repo.record_partial_sale(connection, holding_id, user_id, units_to_sell, current_units - units_to_sell) == 0:
        raise _not_found()


def validate(data):
    """Checks and normalises holding input. data has the keys investmentType, companyName,
    ticker, unitsOwned and averagePurchasePrice (already parsed)."""
    if data is None:
        raise ApiError(400, "invalid_holding", "Holding fields are required.")
    investment_type = (data.get("investmentType") or "").strip()
    if investment_type not in INVESTMENT_TYPES:
        raise ApiError(400, "invalid_investment_type", "Select a valid investment type.")
    name = (data.get("companyName") or "").strip()
    if not name or len(name) > 255:
        raise ApiError(400, "invalid_investment_name",
                       "Investment name must contain 1 to 255 non-whitespace characters.")
    name = unicodedata.normalize("NFC", name)
    normalized = unicodedata.normalize("NFC", name.casefold())
    if len(normalized) > 512:
        raise ApiError(400, "investment_name_too_long", "Normalized investment name exceeds 512 characters.")
    ticker = data.get("ticker")
    ticker = ticker.strip() if ticker is not None else None
    if ticker == "":
        ticker = None
    if ticker is not None and len(ticker) > 32:
        raise ApiError(400, "ticker_too_long", "Ticker/reference code must be at most 32 characters.")
    units = fit_decimal(data.get("unitsOwned"), 24, 8, "units_owned")
    price = fit_decimal(data.get("averagePurchasePrice"), 19, 4, "average_purchase_price")
    if units <= 0:
        raise ApiError(400, "invalid_units", "Units owned must be greater than zero.")
    if price < 0:
        raise ApiError(400, "invalid_price", "Average purchase price must be zero or greater.")
    return {"type": investment_type, "name": name, "normalized": normalized, "ticker": ticker,
            "units": units, "price": price}


def fit_decimal(value, precision, scale, field):
    """Value with exactly `scale` decimal places, rejecting values that would need rounding
    or that do not fit a DECIMAL(precision, scale) column."""
    if value is None:
        raise ApiError(400, "missing_" + field, field + " is required.")
    error = ApiError(400, "invalid_" + field, field + " exceeds the supported decimal precision.")
    if not isinstance(value, Decimal) or not value.is_finite():
        raise error
    if value.adjusted() >= precision:
        raise error
    with localcontext() as context:
        context.prec = precision + scale + 10
        scaled = value.quantize(Decimal(1).scaleb(-scale))
    if scaled != value:
        raise error
    if len(scaled.as_tuple().digits) > precision:
        raise error
    return scaled


def plain(value):
    """A decimal without trailing zeros and without exponent, e.g. 12.5 or 100."""
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def _duplicate():
    return ApiError(409, "duplicate_investment",
                    "A record with the same details already exists for the same holdings. "
                    "Please add different details.")


def _not_found():
    return ApiError(404, "holding_not_found", "Holding was not found.")
