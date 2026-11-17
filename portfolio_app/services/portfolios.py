"""Creating, listing and deleting portfolios."""
import pymysql

from .. import repositories as repo
from ..db import DUPLICATE_KEY, ROW_IS_REFERENCED, ROW_IS_REFERENCED_2, is_error
from ..errors import ApiError


def create(connection, user_id, name_input):
    name = (name_input or "").strip()
    if not name or len(name) > 100:
        raise ApiError(400, "invalid_portfolio_name",
                       "Portfolio name must contain 1 to 100 non-whitespace characters.")
    if repo.portfolio_name_exists(connection, user_id, name):
        raise _duplicate_name()
    try:
        portfolio_id = repo.create_portfolio(connection, user_id, name)
    except pymysql.err.IntegrityError as exception:
        # The unique database constraint handles simultaneous create requests
        if is_error(exception, DUPLICATE_KEY):
            raise _duplicate_name()
        raise
    return require_owned(connection, user_id, portfolio_id)


def list_for(connection, user_id):
    return repo.find_portfolios(connection, user_id)


def details(connection, user_id, portfolio_id):
    portfolio = require_owned(connection, user_id, portfolio_id)
    return {**portfolio, "holdings": repo.find_holdings(connection, portfolio_id, user_id)}


def delete(connection, user_id, portfolio_id):
    require_owned(connection, user_id, portfolio_id)
    if repo.portfolio_has_holdings(connection, portfolio_id):
        raise _not_empty()
    try:
        if repo.delete_portfolio(connection, portfolio_id, user_id) == 0:
            raise _not_found()
    except pymysql.err.IntegrityError as exception:
        if is_error(exception, ROW_IS_REFERENCED, ROW_IS_REFERENCED_2):
            raise _not_empty()
        raise


def require_owned(connection, user_id, portfolio_id):
    portfolio = repo.find_portfolio(connection, portfolio_id, user_id)
    if portfolio is None:
        raise _not_found()
    return portfolio


def _not_found():
    return ApiError(404, "portfolio_not_found", "Portfolio was not found.")


def _not_empty():
    return ApiError(409, "portfolio_not_empty", "Delete the portfolio's holdings before deleting the portfolio.")


def _duplicate_name():
    return ApiError(409, "duplicate_portfolio_name",
                    "You already have a portfolio with this name. Choose a different name.")
