"""BSE end-of-day market data."""
from datetime import date

from flask import Blueprint, request

from .. import repositories as repo
from ..db import get_db
from ..errors import ApiError
from ..jsonutil import json_response, local_date
from ..security import login_required

bp = Blueprint("market_data", __name__, url_prefix="/api/market-data/bse")


@bp.get("/latest")
@login_required
def latest():
    keys = [part for value in request.args.getlist("keys") for part in value.split(",")]
    if not keys:
        return json_response([])
    if len(keys) > 200:
        raise ApiError(400, "too_many_market_data_keys",
                       "Request no more than 200 BSE symbols or security codes at once.")
    normalized = list(dict.fromkeys(key.strip().upper() for key in keys))
    if any(not key or len(key) > 32 for key in normalized):
        raise ApiError(400, "invalid_market_data_key",
                       "BSE symbols and security codes must contain 1 to 32 characters.")
    return json_response(repo.find_latest_prices(get_db(), normalized))


@bp.get("/by-date")
@login_required
def by_date():
    raw = request.args.get("tradeDate")
    if raw is None:
        raise ApiError(400, "invalid_request", "tradeDate is required.")
    try:
        trade_date = date.fromisoformat(raw.strip().replace(",", "-"))
    except ValueError:
        raise ApiError(400, "invalid_request", "tradeDate must be a date in the form YYYY-MM-DD.")
    return json_response(repo.find_prices_by_date(get_db(), trade_date))


@bp.get("/dates")
@login_required
def trade_dates():
    return json_response([local_date(value) for value in repo.find_distinct_trade_dates(get_db())])


@bp.get("/symbols")
@login_required
def symbols():
    return json_response(repo.find_all_symbols(get_db()))


@bp.get("/status")
@login_required
def status():
    return json_response({"latestTradeDate": local_date(repo.latest_trade_date(get_db())),
                          "source": "BSE end-of-day Bhav Copy"})
