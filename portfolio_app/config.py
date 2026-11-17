"""Settings read from environment variables.

The variable names are the same as in the Java version, so both versions can run
against the same MySQL database with the same configuration.
"""
import hashlib
import hmac
import os
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit


def env(name):
    """Trimmed value of an environment variable, or None when it is unset or blank."""
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def required_env(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise RuntimeError(f"Required environment variable is not set: {name}")
    return value


def int_env(name, default):
    try:
        return int(env(name))
    except (TypeError, ValueError):
        return default


def bool_env(name, default):
    """Same rule as Java's Boolean.parseBoolean: only "true" (any case) is true."""
    value = env(name)
    return default if value is None else value.lower() == "true"


def is_production():
    return (env("APP_ENV") or "").lower() == "production"


@dataclass(frozen=True)
class DatabaseSettings:
    host: str
    port: int
    database: str
    user: str
    password: str


def database_settings():
    """Reads PORTFOLIO_DB_URL, which may be a JDBC URL such as
    jdbc:mysql://localhost:3306/portfolio_management_system (as used by the Java app)
    or a plain mysql://host:port/database URL."""
    url = required_env("PORTFOLIO_DB_URL").strip()
    if url.lower().startswith("jdbc:"):
        url = url[5:]
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("mysql", "mysql+pymysql"):
        raise RuntimeError("PORTFOLIO_DB_URL must be a MySQL URL, for example "
                           "jdbc:mysql://localhost:3306/portfolio_management_system")
    database = unquote(parts.path.lstrip("/"))
    if not database:
        database = (parse_qs(parts.query).get("database") or [""])[0]
    if not database:
        raise RuntimeError("PORTFOLIO_DB_URL must include the database name")
    return DatabaseSettings(
        host=parts.hostname or "localhost",
        port=parts.port or 3306,
        database=database,
        user=required_env("PORTFOLIO_DB_USERNAME"),
        password=required_env("PORTFOLIO_DB_PASSWORD"),
    )


def throttle_secret():
    configured = os.environ.get("PORTFOLIO_THROTTLE_HMAC_KEY")
    if configured is None or not configured.strip():
        raise RuntimeError("Required environment variable is not set: PORTFOLIO_THROTTLE_HMAC_KEY")
    secret = configured.encode("utf-8")
    if len(secret) < 32:
        raise RuntimeError("PORTFOLIO_THROTTLE_HMAC_KEY must contain at least 32 UTF-8 bytes")
    return secret


def session_secret():
    """Key that signs the login session cookie.

    Uses PORTFOLIO_SESSION_SECRET when set. Otherwise a key is derived from
    PORTFOLIO_THROTTLE_HMAC_KEY, so no extra setup is needed."""
    configured = env("PORTFOLIO_SESSION_SECRET")
    if configured:
        if len(configured.encode("utf-8")) < 32:
            raise RuntimeError("PORTFOLIO_SESSION_SECRET must contain at least 32 UTF-8 bytes")
        return configured.encode("utf-8")
    return hmac.new(throttle_secret(), b"portfolio-session-cookie", hashlib.sha256).digest()


class MailSettings:
    """SMTP settings for password-reset emails (PORTFOLIO_MAIL_* variables)."""

    def __init__(self):
        self.host = env("PORTFOLIO_MAIL_HOST")
        self.port = int_env("PORTFOLIO_MAIL_PORT", 587)
        self.username = env("PORTFOLIO_MAIL_USERNAME")
        self.password = env("PORTFOLIO_MAIL_PASSWORD")
        self.sender = env("PORTFOLIO_MAIL_FROM")
        self.public_base_url = env("PORTFOLIO_PUBLIC_BASE_URL")
        self.start_tls = bool_env("PORTFOLIO_MAIL_STARTTLS", True)
        self.ssl = bool_env("PORTFOLIO_MAIL_SSL", False)

    def is_configured(self):
        return (bool(self.host)
                and 0 < self.port <= 65535
                and bool(self.sender)
                and self._public_base_url_is_valid()
                and (not self.username) == (not self.password)
                and (self.start_tls or self.ssl)
                and not (self.start_tls and self.ssl)
                and (not is_production() or self.public_base_url.lower().startswith("https://")))

    def reset_link(self, token):
        return self.public_base_url.rstrip("/") + "/reset-password.html#token=" + token

    def _public_base_url_is_valid(self):
        if not self.public_base_url:
            return False
        try:
            parts = urlsplit(self.public_base_url)
        except ValueError:
            return False
        return (parts.scheme.lower() in ("http", "https")
                and bool(parts.hostname)
                and parts.username is None and parts.password is None
                and not parts.query and not parts.fragment)
