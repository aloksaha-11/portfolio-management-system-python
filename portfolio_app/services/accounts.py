"""Sign-up, login (with brute-force throttling) and password reset."""
import base64
import hashlib
import re
import secrets

import pymysql

from .. import repositories as repo
from ..config import MailSettings
from ..db import DUPLICATE_KEY, after_commit, is_error
from ..errors import ApiError
from ..security import burn_password_check, hash_password, throttle_hash, verify_password
from . import mail

EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
RESET_ACCOUNT_LIMIT = 3
RESET_IP_LIMIT = 20


def normalize_email(email):
    return "" if email is None else email.strip().lower()


# ------------------------------------------------------------------ sign-up

def register(connection, email_input, password):
    email = normalize_email(email_input)
    if len(email) > 254 or not EMAIL_PATTERN.match(email):
        raise ApiError(400, "invalid_email", "Enter a valid email address.")
    if password is None or len(password) < 8:
        raise ApiError(400, "invalid_password", "Password must contain at least 8 characters.")
    try:
        return repo.create_user(connection, email, hash_password(password))
    except pymysql.err.IntegrityError as exception:
        if is_error(exception, DUPLICATE_KEY):
            raise ApiError(409, "email_already_registered", "An account with this email already exists.")
        raise


# ------------------------------------------------------------------ login

def authenticate(connection, email_input, password, remote_address):
    """Returns ("ok", user), ("failed", None) or ("limited", None)."""
    email = normalize_email(email_input)
    account_key = throttle_hash("ACCOUNT\0" + email)
    ip_key = throttle_hash("IP\0" + (remote_address or ""))

    account_state = repo.lock_throttle_bucket(connection, "ACCOUNT", account_key)
    ip_state = repo.lock_throttle_bucket(connection, "IP", ip_key)
    if ip_state["block_active"] or (not account_state["window_expired"] and account_state["delay_active"]):
        return "limited", None

    password = password or ""
    user = repo.find_user_by_email(connection, email)
    if user is None:
        burn_password_check(password)
        authenticated = False
    else:
        authenticated = verify_password(user["password_hash"], password)

    if authenticated:
        repo.reset_throttle_account(connection, "ACCOUNT", account_key)
        return "ok", user
    repo.record_throttle_failure(connection, "ACCOUNT", account_key, account_state)
    repo.record_throttle_failure(connection, "IP", ip_key, ip_state)
    return "failed", None


# ------------------------------------------------------------------ password reset

def request_reset(connection, email_input, remote_address):
    email = normalize_email(email_input)
    account_key = throttle_hash("PASSWORD_RESET_ACCOUNT\0" + email[:254])
    ip_key = throttle_hash("PASSWORD_RESET_IP\0" + (remote_address or "")[:128])

    account_state = repo.lock_throttle_bucket(connection, "ACCOUNT", account_key)
    ip_state = repo.lock_throttle_bucket(connection, "IP", ip_key)
    account_allowed = repo.record_throttle_attempt(connection, "ACCOUNT", account_key, account_state,
                                                   RESET_ACCOUNT_LIMIT)
    ip_allowed = repo.record_throttle_attempt(connection, "IP", ip_key, ip_state, RESET_IP_LIMIT)
    settings = MailSettings()
    if not account_allowed or not ip_allowed or len(email) > 254 or not settings.is_configured():
        return

    user = repo.find_user_by_email(connection, email)
    if user is None:
        return
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    repo.replace_reset_token(connection, user["user_id"], hashlib.sha256(token.encode("ascii")).digest())
    reset_link = settings.reset_link(token)
    recipient = user["email"]
    # The email is sent only after the token is safely saved
    after_commit(lambda: mail.queue_reset_email(recipient, reset_link))


def reset_password(connection, token, new_password):
    if new_password is None or not 8 <= len(new_password) <= 128:
        raise ApiError(400, "invalid_password", "Password must contain between 8 and 128 characters.")
    if token is None or not TOKEN_PATTERN.match(token):
        raise _invalid_token()
    token_hash = hashlib.sha256(token.encode("ascii")).digest()
    user_id = repo.find_user_id_for_valid_token(connection, token_hash)
    if user_id is None:
        raise _invalid_token()
    updated = repo.update_password_and_revoke_sessions(connection, user_id, hash_password(new_password))
    if updated != 1 or repo.delete_reset_token(connection, token_hash) != 1:
        raise _invalid_token()


def _invalid_token():
    return ApiError(400, "invalid_or_expired_reset_token",
                    "This password reset link is invalid or has expired. Request a new link.")
