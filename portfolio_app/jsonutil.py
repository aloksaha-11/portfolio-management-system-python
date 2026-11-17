"""JSON request parsing and response building.

Responses use the same field names and formats as the Java (Jackson) API:
decimals are JSON numbers, TIMESTAMP columns are ISO-8601 UTC instants such as
"2026-11-17T08:30:00.123456Z", and DATE columns are "YYYY-MM-DD".
"""
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from flask import Response, request

from .errors import invalid_request

INDIA = ZoneInfo("Asia/Kolkata")


def _reject_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def read_body(required=True):
    """Parses the request body as JSON. Decimals keep their exact value.

    Returns None for an empty body when required is False."""
    raw = request.get_data(cache=True, as_text=False)
    if not raw or not raw.strip():
        if required:
            raise invalid_request()
        return None
    try:
        body = json.loads(raw.decode("utf-8"), parse_float=Decimal, parse_constant=_reject_constant)
    except (ValueError, UnicodeDecodeError):
        raise invalid_request()
    if body is None:
        if required:
            raise invalid_request()
        return None
    if not isinstance(body, dict):
        raise invalid_request()
    return body


def text_field(body, name):
    """A string field. Numbers and booleans are converted to text like Jackson does."""
    value = body.get(name) if body else None
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, Decimal)):
        return str(value)
    raise invalid_request()


def decimal_field(body, name):
    """A number field (a JSON number or a numeric string) as an exact Decimal, or None."""
    value = body.get(name) if body else None
    if value is None:
        return None
    if isinstance(value, bool):
        raise invalid_request()
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            result = Decimal(text)
        except InvalidOperation:
            raise invalid_request()
        if not result.is_finite():
            raise invalid_request()
        return result
    raise invalid_request()


def object_field(body, name):
    value = body.get(name) if body else None
    if value is None:
        return None
    if not isinstance(value, dict):
        raise invalid_request()
    return value


def instant(value):
    """A naive IST datetime read from MySQL as an ISO-8601 UTC string."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=INDIA)
    value = value.astimezone(timezone.utc)
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        text += f".{value.microsecond:06d}".rstrip("0")
    return text + "Z"


def local_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat() if isinstance(value, date) else str(value)


def _default(value):
    if isinstance(value, Decimal):
        # Browsers read every JSON number as a double, so this matches what they got from Java
        return int(value) if value == value.to_integral_value() and abs(value) < 2 ** 53 else float(value)
    if isinstance(value, datetime):
        return instant(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Cannot convert {type(value).__name__} to JSON")


def to_json(data):
    return json.dumps(data, default=_default, ensure_ascii=False, separators=(",", ":"))


def json_response(data, status=200):
    return Response(to_json(data), status=status, mimetype="application/json")


def empty_response(status=204):
    return Response(status=status)
