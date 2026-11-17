"""Portfolio Rebalancing System: the Python (Flask) version.

It serves the same web pages as the Java version and provides the same /api endpoints,
using the same MySQL database.
"""
import decimal
import logging
from datetime import timedelta
from pathlib import Path

from flask import Flask, abort, g, request, send_from_directory
from werkzeug.exceptions import HTTPException

from . import config, db, repositories, security
from .errors import ApiError
from .jsonutil import json_response

# Exact decimal arithmetic for money and unit amounts (DECIMAL(24,8) needs up to 32 digits)
decimal.DefaultContext.prec = 80
decimal.getcontext().prec = 80

STATIC_DIR = Path(__file__).resolve().parent / "static"
PUBLIC_PAGES = {
    "index.html", "login.html", "signup.html", "dashboard.html", "portfolio-details.html", "plan.html",
    "forgot-password.html", "reset-password.html",
}
logger = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=config.session_secret(),
        SESSION_COOKIE_NAME="PRS_SESSION",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.is_production(),
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        SESSION_REFRESH_EACH_REQUEST=True,
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    config.database_settings()  # fail fast when the database variables are missing
    config.throttle_secret()

    from .api import BLUEPRINTS
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    _register_pages(app)
    _register_hooks(app)
    _register_error_handlers(app)
    return app


def _register_pages(app):
    @app.get("/")
    def home():
        return send_from_directory(STATIC_DIR, "index.html")

    @app.get("/<page>")
    def page(page):
        if page not in PUBLIC_PAGES:
            abort(404)
        return send_from_directory(STATIC_DIR, page)

    @app.get("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(STATIC_DIR / "assets", filename)


def _register_hooks(app):
    @app.before_request
    def protect():
        security.check_csrf()
        if request.path.startswith("/api"):
            security.check_session_version(lambda user_id: repositories.session_version(db.get_db(), user_id))

    @app.after_request
    def finish(response):
        if "db" in g:
            db.finish_request(success=response.status_code < 500 and not g.get("rolled_back"))
        security.set_csrf_cookie(response)
        # The same protective headers Spring Security adds by default
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "0")
        response.headers["Cache-Control"] = "no-cache, no-store, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000 ; includeSubDomains")
        return response

    @app.teardown_request
    def close_connection(_error):
        if "db" in g:
            db.finish_request(success=False)


def _register_error_handlers(app):
    @app.errorhandler(ApiError)
    def api_error(error):
        db.rollback_request()
        g.rolled_back = True
        body = {"error": error.code}
        if error.message is not None:
            body["message"] = error.message
        return json_response(body, error.status)

    @app.errorhandler(HTTPException)
    def http_error(error):
        db.rollback_request()
        g.rolled_back = True
        if request.path.startswith("/api"):
            return json_response({"error": (error.name or "error").lower().replace(" ", "_"),
                                  "message": error.description}, error.code)
        return error

    @app.errorhandler(Exception)
    def unexpected_error(error):
        logger.exception("Unexpected error for %s %s", request.method, request.path)
        db.rollback_request()
        g.rolled_back = True
        return json_response({"error": "internal_error", "message": "Something went wrong. Please try again."}, 500)
