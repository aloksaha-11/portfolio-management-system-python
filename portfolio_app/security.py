"""Passwords, login sessions and CSRF protection.

* Passwords use Argon2id with the same settings as Spring Security's
  Argon2PasswordEncoder.defaultsForSpringSecurity_v5_8(), so accounts created by the
  Java version can log in here and the other way round.
* The login session is a signed cookie that expires after 30 minutes without activity.
* CSRF uses the same double-submit cookie as Spring Security: the XSRF-TOKEN cookie
  must be echoed in the X-XSRF-TOKEN header of every POST, PUT, PATCH and DELETE.
"""
import functools
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import g, request, session

from . import config
from .errors import ApiError

CSRF_COOKIE = "XSRF-TOKEN"
CSRF_HEADER = "X-XSRF-TOKEN"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

_hasher = PasswordHasher(time_cost=2, memory_cost=16384, parallelism=1, hash_len=32, salt_len=16,
                         type=Type.ID)
# Checked when an email is unknown, so a failed login takes the same time either way
_DUMMY_HASH = _hasher.hash("portfolio-dummy-password")


def hash_password(password):
    return _hasher.hash(password)


def verify_password(password_hash, password):
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_password_check(password):
    verify_password(_DUMMY_HASH, password)


# ---------------------------------------------------------------- throttle keys

def throttle_hash(value):
    """HMAC-SHA-256 of value with PORTFOLIO_THROTTLE_HMAC_KEY (32 bytes)."""
    return hmac.new(config.throttle_secret(), value.encode("utf-8"), hashlib.sha256).digest()


# ---------------------------------------------------------------- CSRF

def csrf_token():
    """The CSRF token for this browser, creating one (and its cookie) when needed."""
    if g.get("new_csrf_token"):
        return g.new_csrf_token
    token = request.cookies.get(CSRF_COOKIE)
    if not token:
        token = issue_csrf_token()
    return token


def issue_csrf_token():
    """Creates a fresh CSRF token; the cookie is set when the response is sent."""
    g.new_csrf_token = secrets.token_urlsafe(32)
    return g.new_csrf_token


def check_csrf():
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not hmac.compare_digest(cookie.encode(), header.encode()):
        raise ApiError(403, "access_denied", None)


def set_csrf_cookie(response):
    token = g.get("new_csrf_token")
    if g.get("clear_csrf_cookie"):
        response.delete_cookie(CSRF_COOKIE, path="/", samesite="Lax", secure=config.is_production())
    elif token:
        response.set_cookie(CSRF_COOKIE, token, path="/", httponly=False, samesite="Lax",
                            secure=config.is_production())
    return response


# ---------------------------------------------------------------- sessions

def sign_in(user):
    session.clear()
    session.permanent = True
    session["user_id"] = user["user_id"]
    session["email"] = user["email"]
    session["session_version"] = user["session_version"]
    # A new CSRF token after login, as Spring Security does
    issue_csrf_token()


def sign_out():
    session.clear()
    g.clear_csrf_cookie = True


def current_user():
    """(user_id, email) of the signed-in user, or None."""
    if "user_id" not in session:
        return None
    return session["user_id"], session["email"]


def check_session_version(load_version):
    """Ends the session when the password was reset after this login."""
    if "user_id" not in session:
        return
    if load_version(session["user_id"]) != session.get("session_version"):
        session.clear()
        raise ApiError(401, "session_expired", "Please log in again.")


def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if user is None:
            raise ApiError(401, "authentication_required", None)
        g.user_id, g.user_email = user
        return view(*args, **kwargs)
    return wrapper
