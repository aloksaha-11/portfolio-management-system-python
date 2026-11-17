"""Portfolios, holdings and sales."""
from flask import Blueprint, g

from ..db import get_db
from ..jsonutil import decimal_field, empty_response, json_response, read_body, text_field
from ..security import login_required
from ..services import holdings, portfolios

bp = Blueprint("portfolios", __name__)


@bp.get("/api/portfolios")
@login_required
def list_portfolios():
    return json_response(portfolios.list_for(get_db(), g.user_id))


@bp.post("/api/portfolios")
@login_required
def create_portfolio():
    body = read_body()
    return json_response(portfolios.create(get_db(), g.user_id, text_field(body, "name")), 201)


@bp.get("/api/portfolios/<int:portfolio_id>")
@login_required
def get_portfolio(portfolio_id):
    return json_response(portfolios.details(get_db(), g.user_id, portfolio_id))


@bp.delete("/api/portfolios/<int:portfolio_id>")
@login_required
def delete_portfolio(portfolio_id):
    portfolios.delete(get_db(), g.user_id, portfolio_id)
    return empty_response(204)


@bp.get("/api/portfolios/<int:portfolio_id>/holdings")
@login_required
def list_holdings(portfolio_id):
    return json_response(holdings.list_for(get_db(), g.user_id, portfolio_id))


@bp.get("/api/portfolios/<int:portfolio_id>/sold-holdings")
@login_required
def list_sold_holdings(portfolio_id):
    return json_response(holdings.list_sold(get_db(), g.user_id, portfolio_id))


@bp.post("/api/portfolios/<int:portfolio_id>/holdings")
@login_required
def add_holding(portfolio_id):
    return json_response(holdings.add(get_db(), g.user_id, portfolio_id, _holding_input()), 201)


@bp.put("/api/holdings/<int:holding_id>")
@login_required
def update_holding(holding_id):
    return json_response(holdings.update(get_db(), g.user_id, holding_id, _holding_input()))


@bp.delete("/api/holdings/<int:holding_id>")
@login_required
def delete_holding(holding_id):
    holdings.delete(get_db(), g.user_id, holding_id)
    return empty_response(204)


@bp.post("/api/holdings/<int:holding_id>/sell")
@login_required
def sell_holding(holding_id):
    body = read_body(required=False)
    holdings.sell(get_db(), g.user_id, holding_id, decimal_field(body, "units"))
    return empty_response(204)


def _holding_input():
    body = read_body()
    return {
        "investmentType": text_field(body, "investmentType"),
        "companyName": text_field(body, "companyName"),
        "ticker": text_field(body, "ticker"),
        "unitsOwned": decimal_field(body, "unitsOwned"),
        "averagePurchasePrice": decimal_field(body, "averagePurchasePrice"),
    }
