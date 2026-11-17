from flask import Blueprint

from ..jsonutil import json_response
from . import auth, market_data, plans, portfolios

info = Blueprint("info", __name__)


@info.get("/api")
def api_info():
    return json_response({"name": "Portfolio Management API", "status": "ready", "health": "/api/health"})


@info.get("/api/health")
def health():
    return json_response({"status": "UP"})


BLUEPRINTS = (info, auth.bp, portfolios.bp, market_data.bp, plans.bp)
