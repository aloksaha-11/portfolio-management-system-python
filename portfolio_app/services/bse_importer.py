"""Imports BSE end-of-day prices from the public Bhav Copy CSV file."""
import logging
import re
import threading
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from .. import repositories as repo
from ..db import standalone_transaction

logger = logging.getLogger(__name__)
INDIA = ZoneInfo("Asia/Kolkata")
MAX_LOOKBACK_DAYS = 7
BSE_FILE_URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{}_F_0000.csv"
_LINE_BREAK = re.compile(r"\r\n|[\n\u000b\u000c\r\u0085  ]")
_lock = threading.Lock()


class DownloadResult:
    def __init__(self, status, body=""):
        self.status = status
        self.body = body


def today_in_india():
    return datetime.now(INDIA).date()


def import_after_market_close():
    """Scheduled at 6:15 PM and 7:15 PM IST, Monday to Friday."""
    import_latest_available()


def catch_up_after_startup():
    """Runs shortly after start-up and then once a day."""
    import_latest_available()
    backfill_recent_company_names()


def import_latest_available():
    """Imports the newest Bhav Copy published in the last 8 days."""
    with _lock:
        start = today_in_india()
        for offset in range(MAX_LOOKBACK_DAYS + 1):
            trade_date = start - timedelta(days=offset)
            try:
                response = download(trade_date)
                if response.status == 404:
                    continue
                if response.status != 200:
                    logger.warning("BSE EOD download returned HTTP %s for %s", response.status, trade_date)
                    return
                rows = parse(response.body, trade_date)
                if not rows:
                    logger.warning("BSE EOD file for %s contained no equity prices", trade_date)
                    return
                with standalone_transaction() as connection:
                    stored = repo.upsert_prices(connection, rows)
                logger.info("Imported %s BSE end-of-day prices for %s", stored, trade_date)
                return
            except Exception:
                logger.warning("Could not import BSE EOD prices for %s", trade_date, exc_info=True)
                return
        logger.info("No BSE equity Bhav Copy was available for the last %s days", MAX_LOOKBACK_DAYS + 1)


def backfill_recent_company_names():
    from_date = today_in_india() - timedelta(days=MAX_LOOKBACK_DAYS)
    try:
        with standalone_transaction() as connection:
            dates = repo.find_trade_dates_missing_company_names(connection, from_date)
    except Exception:
        logger.warning("Could not look for BSE rows without company names", exc_info=True)
        return
    for trade_date in dates:
        try:
            response = download(trade_date)
            if response.status != 200:
                logger.warning("Could not backfill BSE company names for %s: HTTP %s", trade_date, response.status)
                continue
            rows = parse(response.body, trade_date)
            with standalone_transaction() as connection:
                stored = repo.upsert_prices(connection, rows)
            logger.info("Backfilled company names in %s BSE rows for %s", stored, trade_date)
        except Exception:
            logger.warning("Could not backfill BSE company names for %s", trade_date, exc_info=True)


def download(trade_date):
    url = BSE_FILE_URL.format(trade_date.strftime("%Y%m%d"))
    request = urllib.request.Request(url, headers={
        "Accept": "text/csv,application/octet-stream,*/*",
        "User-Agent": "PortfolioManagementSystem/1.0",
        "Referer": "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx",
    })
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return DownloadResult(response.status, response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as error:
        return DownloadResult(error.code)


def parse(csv_text, requested_date):
    """Parses the Bhav Copy CSV into tuples ready for repositories.upsert_prices."""
    lines = _LINE_BREAK.split(csv_text.replace("﻿", ""))
    while lines and lines[-1] == "":
        lines.pop()
    if len(lines) < 2:
        raise ValueError("BSE Bhav Copy is empty or malformed")
    headers = split_csv_line(lines[0])
    columns = {header.strip(): index for index, header in enumerate(headers)}

    def required(name):
        if name not in columns:
            raise ValueError(f"BSE Bhav Copy is missing the {name} column")
        return columns[name]

    trade_date_column = required("TradDt")
    security_code_column = required("FinInstrmId")
    isin_column = required("ISIN")
    symbol_column = required("TckrSymb")
    company_name_column = columns.get("FinInstrmNm", -1)
    series_column = required("SctySrs")
    open_column = required("OpnPric")
    high_column = required("HghPric")
    low_column = required("LwPric")
    close_column = required("ClsPric")
    previous_close_column = required("PrvsClsgPric")
    volume_column = required("TtlTradgVol")

    result = []
    for line_number in range(1, len(lines)):
        line = lines[line_number].strip()
        if not line:
            continue
        values = split_csv_line(line)
        if len(values) < len(headers):
            raise ValueError(f"Malformed BSE Bhav Copy row {line_number + 1}")

        def value(column):
            return values[column].strip()

        def number(column):
            raw = value(column)
            if not raw:
                return None
            try:
                parsed = Decimal(raw)
            except InvalidOperation:
                raise ValueError(f"Invalid number {raw!r} in BSE Bhav Copy row {line_number + 1}")
            if not parsed.is_finite():
                raise ValueError(f"Invalid number {raw!r} in BSE Bhav Copy row {line_number + 1}")
            return parsed

        trade_date = date.fromisoformat(value(trade_date_column))
        if trade_date != requested_date:
            raise ValueError("BSE file date does not match its filename date")
        security_code = value(security_code_column)
        series = value(series_column).upper()
        close = number(close_column)
        if not security_code or not series or close is None or close <= 0:
            continue
        symbol = value(symbol_column).upper()
        company_name = None if company_name_column < 0 else (value(company_name_column) or None)
        volume_text = value(volume_column)
        result.append((
            trade_date,
            security_code,
            value(isin_column) or None,
            symbol or None,
            company_name,
            series,
            number(open_column),
            number(high_column),
            number(low_column),
            close,
            number(previous_close_column),
            int(volume_text) if volume_text else None,
        ))
    return result


def split_csv_line(line):
    values = []
    current = []
    quoted = False
    index = 0
    while index < len(line):
        character = line[index]
        if character == '"':
            if quoted and index + 1 < len(line) and line[index + 1] == '"':
                current.append('"')
                index += 1
            else:
                quoted = not quoted
        elif character == "," and not quoted:
            values.append("".join(current))
            current = []
        else:
            current.append(character)
        index += 1
    values.append("".join(current))
    if quoted:
        raise ValueError("BSE Bhav Copy contains an unterminated CSV field")
    return values
