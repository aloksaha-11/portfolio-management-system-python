"""All SQL used by the application. The queries match the Java repositories.

Every function takes an open PyMySQL connection as its first argument.
"""
from decimal import ROUND_HALF_UP, Decimal

from .jsonutil import instant, local_date

TWO_PLACES = Decimal("0.01")


def _one(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def _all(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def _update(connection, sql, params=()):
    with connection.cursor() as cursor:
        return cursor.execute(sql, params)


def _insert(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        if not cursor.lastrowid:
            raise RuntimeError("MySQL did not return an identifier")
        return cursor.lastrowid


def _exists(connection, sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
        return bool(row and list(row.values())[0])


# ======================================================================= users

def find_user_by_email(connection, email):
    return _one(connection,
                "SELECT user_id, email, password_hash, session_version FROM users WHERE email = %s",
                (email,))


def session_version(connection, user_id):
    row = _one(connection, "SELECT session_version FROM users WHERE user_id = %s", (user_id,))
    return -1 if row is None else row["session_version"]


def create_user(connection, email, password_hash):
    return _insert(connection, "INSERT INTO users (email, password_hash) VALUES (%s, %s)",
                   (email, password_hash))


def update_password_and_revoke_sessions(connection, user_id, password_hash):
    return _update(connection,
                   "UPDATE users SET password_hash = %s, session_version = session_version + 1 "
                   "WHERE user_id = %s", (password_hash, user_id))


# ======================================================================= login throttle

def lock_throttle_bucket(connection, bucket_type, key_hash):
    _update(connection, """
        INSERT INTO login_throttle (bucket_type, bucket_key_hash, failure_count, window_started_at)
        VALUES (%s, %s, 0, CURRENT_TIMESTAMP(6))
        ON DUPLICATE KEY UPDATE throttle_id = throttle_id
        """, (bucket_type, key_hash))
    row = _one(connection, """
        SELECT failure_count,
               window_started_at <= CURRENT_TIMESTAMP(6) - INTERVAL 15 MINUTE AS window_expired,
               delay_until > CURRENT_TIMESTAMP(6) AS delay_active,
               blocked_until > CURRENT_TIMESTAMP(6) AS block_active
        FROM login_throttle
        WHERE bucket_type = %s AND bucket_key_hash = %s
        FOR UPDATE
        """, (bucket_type, key_hash))
    if row is None:
        raise RuntimeError("Login throttle bucket was not created")
    return {
        "failure_count": int(row["failure_count"]),
        "window_expired": bool(row["window_expired"]),
        "delay_active": bool(row["delay_active"]),
        "block_active": bool(row["block_active"]),
    }


def record_throttle_failure(connection, bucket_type, key_hash, previous):
    expired = previous["window_expired"]
    next_count = 1 if expired else previous["failure_count"] + 1
    delay_seconds = min(30, 1 << min(5, next_count - 5)) if bucket_type == "ACCOUNT" and next_count >= 5 else 0
    block = bucket_type == "IP" and next_count >= 60
    _update(connection, """
        UPDATE login_throttle
        SET failure_count = %s,
            window_started_at = IF(%s, CURRENT_TIMESTAMP(6), window_started_at),
            delay_until = IF(%s > 0, CURRENT_TIMESTAMP(6) + INTERVAL %s SECOND, NULL),
            blocked_until = IF(%s, CURRENT_TIMESTAMP(6) + INTERVAL 15 MINUTE, NULL)
        WHERE bucket_type = %s AND bucket_key_hash = %s
        """, (next_count, expired, delay_seconds, delay_seconds, block, bucket_type, key_hash))


def record_throttle_attempt(connection, bucket_type, key_hash, previous, limit):
    expired = previous["window_expired"]
    next_count = 1 if expired else previous["failure_count"] + 1
    _update(connection, """
        UPDATE login_throttle
        SET failure_count = %s,
            window_started_at = IF(%s, CURRENT_TIMESTAMP(6), window_started_at)
        WHERE bucket_type = %s AND bucket_key_hash = %s
        """, (next_count, expired, bucket_type, key_hash))
    return next_count <= limit


def reset_throttle_account(connection, bucket_type, key_hash):
    _update(connection, """
        UPDATE login_throttle
        SET failure_count = 0, window_started_at = CURRENT_TIMESTAMP(6), delay_until = NULL
        WHERE bucket_type = %s AND bucket_key_hash = %s
        """, (bucket_type, key_hash))


# ======================================================================= password reset tokens

def replace_reset_token(connection, user_id, token_hash):
    _update(connection, "DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))
    _update(connection, """
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
        VALUES (%s, %s, CURRENT_TIMESTAMP(6) + INTERVAL 30 MINUTE)
        """, (user_id, token_hash))


def find_user_id_for_valid_token(connection, token_hash):
    row = _one(connection, """
        SELECT user_id FROM password_reset_tokens
        WHERE token_hash = %s AND expires_at > CURRENT_TIMESTAMP(6)
        FOR UPDATE
        """, (token_hash,))
    return None if row is None else row["user_id"]


def delete_reset_token(connection, token_hash):
    return _update(connection, "DELETE FROM password_reset_tokens WHERE token_hash = %s", (token_hash,))


# ======================================================================= portfolios

def _portfolio(row):
    return {
        "portfolioId": row["portfolio_id"],
        "name": row["name"],
        "currency": row["currency"],
        "createdAt": instant(row["created_at"]),
        "updatedAt": instant(row["updated_at"]),
    }


def create_portfolio(connection, user_id, name):
    return _insert(connection, "INSERT INTO portfolios (user_id, name, currency) VALUES (%s, %s, 'INR')",
                   (user_id, name))


def portfolio_name_exists(connection, user_id, name):
    return _exists(connection, """
        SELECT EXISTS (
            SELECT 1 FROM portfolios
            WHERE user_id = %s
              AND LOWER(TRIM(name)) COLLATE utf8mb4_0900_ai_ci
                  = LOWER(%s) COLLATE utf8mb4_0900_ai_ci
        ) AS found
        """, (user_id, name))


def find_portfolios(connection, user_id):
    return [_portfolio(row) for row in _all(connection, """
        SELECT portfolio_id, name, currency, created_at, updated_at
        FROM portfolios WHERE user_id = %s
        ORDER BY created_at, portfolio_id
        """, (user_id,))]


def find_portfolio(connection, portfolio_id, user_id):
    row = _one(connection, """
        SELECT portfolio_id, name, currency, created_at, updated_at
        FROM portfolios WHERE portfolio_id = %s AND user_id = %s
        """, (portfolio_id, user_id))
    return None if row is None else _portfolio(row)


def delete_portfolio(connection, portfolio_id, user_id):
    return _update(connection, "DELETE FROM portfolios WHERE portfolio_id = %s AND user_id = %s",
                   (portfolio_id, user_id))


def portfolio_has_holdings(connection, portfolio_id):
    return _exists(connection, "SELECT EXISTS (SELECT 1 FROM holdings WHERE portfolio_id = %s) AS found",
                   (portfolio_id,))


# ======================================================================= holdings

def _cost_basis(units, price):
    return (units * price).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _holding(row):
    return {
        "holdingId": row["holding_id"],
        "portfolioId": row["portfolio_id"],
        "investmentType": row["investment_type"],
        "investmentName": row["investment_name"],
        "ticker": row["ticker"],
        "unitsOwned": row["units_owned"],
        "averagePurchasePrice": row["average_purchase_price"],
        "costBasis": _cost_basis(row["units_owned"], row["average_purchase_price"]),
        "createdAt": instant(row["created_at"]),
        "updatedAt": instant(row["updated_at"]),
    }


def _sold_holding(row):
    return {
        "soldHoldingId": row["sold_holding_id"],
        "originalHoldingId": row["original_holding_id"],
        "portfolioId": row["portfolio_id"],
        "investmentType": row["investment_type"],
        "investmentName": row["investment_name"],
        "ticker": row["ticker"],
        "unitsOwned": row["units_owned"],
        "averagePurchasePrice": row["average_purchase_price"],
        "costBasis": _cost_basis(row["units_owned"], row["average_purchase_price"]),
        "addedAt": instant(row["added_at"]),
        "soldAt": instant(row["sold_at"]),
    }


def create_holding(connection, user_id, portfolio_id, investment_type, name, normalized_name, ticker,
                   units, average_price):
    return _insert(connection, """
        INSERT INTO holdings
            (owner_user_id, portfolio_id, investment_type, investment_name, normalized_investment_name, ticker,
             units_owned, average_purchase_price)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (user_id, portfolio_id, investment_type, name, normalized_name, ticker, units, average_price))


def holding_exists_with_same_details(connection, user_id, investment_type, normalized_name, ticker, units,
                                     average_price, excluding_holding_id=None):
    sql = """
        SELECT EXISTS (
            SELECT 1 FROM holdings h
            JOIN portfolios p ON p.portfolio_id = h.portfolio_id
            WHERE p.user_id = %s
              AND h.normalized_investment_name = %s
              AND h.investment_type = %s
              AND LOWER(COALESCE(h.ticker, '')) COLLATE utf8mb4_0900_ai_ci
                  = LOWER(COALESCE(%s, '')) COLLATE utf8mb4_0900_ai_ci
              AND h.units_owned = %s
              AND h.average_purchase_price = %s
        """
    params = [user_id, normalized_name, investment_type, ticker, units, average_price]
    if excluding_holding_id is not None:
        sql += " AND h.holding_id <> %s"
        params.append(excluding_holding_id)
    return _exists(connection, sql + ") AS found", params)


_HOLDING_COLUMNS = """
    SELECT h.holding_id, h.portfolio_id, h.investment_type, h.investment_name, h.ticker,
           h.units_owned, h.average_purchase_price, h.created_at, h.updated_at
    FROM holdings h
    JOIN portfolios p ON p.portfolio_id = h.portfolio_id
"""


def find_holdings(connection, portfolio_id, user_id):
    return [_holding(row) for row in _all(
        connection, _HOLDING_COLUMNS + " WHERE h.portfolio_id = %s AND p.user_id = %s ORDER BY h.holding_id",
        (portfolio_id, user_id))]


def find_holding(connection, holding_id, user_id):
    row = _one(connection, _HOLDING_COLUMNS + " WHERE h.holding_id = %s AND p.user_id = %s",
               (holding_id, user_id))
    return None if row is None else _holding(row)


def find_sold_holdings(connection, portfolio_id, user_id):
    return [_sold_holding(row) for row in _all(connection, """
        SELECT sold_holding_id, original_holding_id, portfolio_id, investment_type,
               investment_name, ticker, units_owned, average_purchase_price, added_at, sold_at
        FROM sold_holdings
        WHERE portfolio_id = %s AND owner_user_id = %s
        ORDER BY sold_at DESC, sold_holding_id DESC
        """, (portfolio_id, user_id))]


def move_holding_to_sold(connection, holding_id, user_id):
    inserted = _update(connection, """
        INSERT INTO sold_holdings (
            original_holding_id, owner_user_id, portfolio_id, investment_type,
            investment_name, ticker, units_owned, average_purchase_price, added_at
        )
        SELECT h.holding_id, h.owner_user_id, h.portfolio_id, h.investment_type,
               h.investment_name, h.ticker, h.units_owned, h.average_purchase_price, h.created_at
        FROM holdings h
        WHERE h.holding_id = %s AND h.owner_user_id = %s
        """, (holding_id, user_id))
    if inserted == 0:
        return 0
    return _update(connection, "DELETE FROM holdings WHERE holding_id = %s AND owner_user_id = %s",
                   (holding_id, user_id))


def record_partial_sale(connection, holding_id, user_id, sold_units, remaining_units):
    inserted = _update(connection, """
        INSERT INTO sold_holdings (
            original_holding_id, owner_user_id, portfolio_id, investment_type,
            investment_name, ticker, units_owned, average_purchase_price, added_at
        )
        SELECT h.holding_id, h.owner_user_id, h.portfolio_id, h.investment_type,
               h.investment_name, h.ticker, %s, h.average_purchase_price, h.created_at
        FROM holdings h
        WHERE h.holding_id = %s AND h.owner_user_id = %s
        """, (sold_units, holding_id, user_id))
    if inserted == 0:
        return 0
    return _update(connection, "UPDATE holdings SET units_owned = %s WHERE holding_id = %s AND owner_user_id = %s",
                   (remaining_units, holding_id, user_id))


def update_holding(connection, holding_id, user_id, investment_type, name, normalized_name, ticker, units,
                   average_price):
    return _update(connection, """
        UPDATE holdings h
        JOIN portfolios p ON p.portfolio_id = h.portfolio_id
        SET h.investment_type = %s, h.investment_name = %s, h.normalized_investment_name = %s, h.ticker = %s,
            h.units_owned = %s, h.average_purchase_price = %s
        WHERE h.holding_id = %s AND p.user_id = %s
        """, (investment_type, name, normalized_name, ticker, units, average_price, holding_id, user_id))


def delete_holding(connection, holding_id, user_id):
    return _update(connection, """
        DELETE h FROM holdings h
        JOIN portfolios p ON p.portfolio_id = h.portfolio_id
        WHERE h.holding_id = %s AND p.user_id = %s
        """, (holding_id, user_id))


# ======================================================================= BSE daily prices

_PRICE_COLUMNS = ("trade_date, security_code, isin, bse_symbol, company_name, series, "
                  "open_price, high_price, low_price, close_price, previous_close, volume")
_UPSERT_BATCH = 500


def _price(row):
    return {
        "securityCode": row["security_code"],
        "isin": row["isin"],
        "symbol": row["bse_symbol"],
        "companyName": row["company_name"],
        "series": row["series"],
        "tradeDate": local_date(row["trade_date"]),
        "openPrice": row["open_price"],
        "highPrice": row["high_price"],
        "lowPrice": row["low_price"],
        "closePrice": row["close_price"],
        "previousClose": row["previous_close"],
        "volume": row["volume"],
    }


def upsert_prices(connection, prices):
    """Inserts or updates BSE prices in batches of 500. Each price is a tuple in
    the order of _PRICE_COLUMNS. Returns the number of rows sent."""
    for start in range(0, len(prices), _UPSERT_BATCH):
        batch = prices[start:start + _UPSERT_BATCH]
        placeholders = ", ".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(batch))
        params = [value for price in batch for value in price]
        _update(connection, f"""
            INSERT INTO bse_daily_prices ({_PRICE_COLUMNS})
            VALUES {placeholders}
            AS incoming
            ON DUPLICATE KEY UPDATE
                isin = incoming.isin,
                bse_symbol = incoming.bse_symbol,
                company_name = COALESCE(incoming.company_name, bse_daily_prices.company_name),
                open_price = incoming.open_price,
                high_price = incoming.high_price,
                low_price = incoming.low_price,
                close_price = incoming.close_price,
                previous_close = incoming.previous_close,
                volume = incoming.volume,
                imported_at = CURRENT_TIMESTAMP(6)
            """, params)
    return len(prices)


def find_latest_prices(connection, keys):
    if not keys:
        return []
    placeholders = ", ".join(["%s"] * len(keys))
    rows = _all(connection, f"""
        WITH matched_prices AS (
            SELECT p.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY p.security_code, p.series
                       ORDER BY p.trade_date DESC
                   ) AS price_rank
            FROM bse_daily_prices p
            WHERE (p.bse_symbol IN ({placeholders}) OR p.security_code IN ({placeholders}))
              AND p.trade_date = (SELECT MAX(trade_date) FROM bse_daily_prices)
        )
        SELECT security_code, isin, bse_symbol, company_name, series, trade_date,
               open_price, high_price, low_price, close_price, previous_close, volume
        FROM matched_prices
        WHERE price_rank = 1
        ORDER BY (series = 'EQ') DESC, bse_symbol ASC
        """, list(keys) + list(keys))
    return [_price(row) for row in rows]


def find_prices_by_date(connection, trade_date):
    return [_price(row) for row in _all(connection, """
        SELECT security_code, isin, bse_symbol, company_name, series, trade_date,
               open_price, high_price, low_price, close_price, previous_close, volume
        FROM bse_daily_prices
        WHERE trade_date = %s
        ORDER BY (series = 'EQ') DESC, bse_symbol ASC, security_code ASC
        """, (trade_date,))]


def find_all_symbols(connection):
    return [row["bse_symbol"] for row in _all(connection, """
        SELECT DISTINCT bse_symbol
        FROM bse_daily_prices
        WHERE bse_symbol IS NOT NULL AND TRIM(bse_symbol) <> ''
        ORDER BY bse_symbol
        """)]


def find_trade_dates_missing_company_names(connection, from_date):
    return [row["trade_date"] for row in _all(connection, """
        SELECT DISTINCT trade_date
        FROM bse_daily_prices
        WHERE trade_date >= %s AND company_name IS NULL
        ORDER BY trade_date
        """, (from_date,))]


def latest_trade_date(connection):
    row = _one(connection, "SELECT MAX(trade_date) AS latest FROM bse_daily_prices")
    return None if row is None else row["latest"]


def find_recent_changes(connection, symbol, days):
    """The most recent `days` (trade_date, previous_close, close_price) rows for a symbol, newest first."""
    return _all(connection, """
        SELECT trade_date, previous_close, close_price
        FROM bse_daily_prices
        WHERE bse_symbol = %s AND previous_close > 0
        ORDER BY trade_date DESC
        LIMIT %s
        """, (symbol, days))


def find_distinct_trade_dates(connection):
    return [row["trade_date"] for row in _all(connection, """
        SELECT DISTINCT trade_date
        FROM bse_daily_prices
        ORDER BY trade_date DESC
        """)]


# ======================================================================= investment plans

PLAN_ASSETS = ("shares", "bonds", "gold", "silver", "mutual_funds")


def create_plan(connection, user_id, risk_profile, current, budget, suggested, market_signal, reasons):
    return _insert(connection, """
        INSERT INTO investment_plans (
            user_id, risk_profile,
            current_shares, current_bonds, current_gold, current_silver, current_mutual_funds,
            budget,
            suggested_shares, suggested_bonds, suggested_gold, suggested_silver, suggested_mutual_funds,
            market_signal, reasons
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, [user_id, risk_profile, *current, budget, *suggested, market_signal, "\n".join(reasons)])


def _stored_plan(row):
    return {
        "plan_id": row["plan_id"],
        "risk_profile": row["risk_profile"],
        "current": [row["current_" + name] for name in PLAN_ASSETS],
        "budget": row["budget"],
        "suggested": [row["suggested_" + name] for name in PLAN_ASSETS],
        "market_signal": row["market_signal"],
        "reasons": row["reasons"].split("\n"),
        "created_at": row["created_at"],
    }


def find_plan(connection, plan_id, user_id):
    row = _one(connection, "SELECT * FROM investment_plans WHERE plan_id = %s AND user_id = %s",
               (plan_id, user_id))
    if row is None:
        raise RuntimeError("Saved plan was not found")
    return _stored_plan(row)


def find_recent_plans(connection, user_id, limit):
    return [_stored_plan(row) for row in _all(connection, """
        SELECT * FROM investment_plans
        WHERE user_id = %s
        ORDER BY created_at DESC, plan_id DESC
        LIMIT %s
        """, (user_id, limit))]
