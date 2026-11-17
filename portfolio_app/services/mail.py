"""Sends password-reset emails in the background (never blocks a web request)."""
import logging
import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage

from ..config import MailSettings

logger = logging.getLogger(__name__)
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="password-reset-mail")
_TIMEOUT_SECONDS = 5


def log_configuration_warning():
    if not MailSettings().is_configured():
        logger.warning("Password reset email delivery is disabled until SMTP and public URL "
                       "environment variables are configured")


def queue_reset_email(email, reset_link):
    settings = MailSettings()
    if not settings.is_configured():
        logger.warning("Password reset email is not configured; set the PORTFOLIO_MAIL_* and "
                       "PORTFOLIO_PUBLIC_BASE_URL environment variables")
        return
    try:
        _executor.submit(_send, settings, email, reset_link)
    except RuntimeError as exception:
        logger.warning("Could not queue password reset email (%s)", type(exception).__name__)


def _send(settings, email, reset_link):
    message = EmailMessage()
    message["From"] = settings.sender
    message["To"] = email
    message["Subject"] = "Reset your Portfolio Rebalancing System password"
    message.set_content(
        "A password reset was requested for your Portfolio Rebalancing System account.\n\n"
        "Use this one-time link within 30 minutes to choose a new password:\n"
        + reset_link + "\n\n"
        "If you did not request this, you can ignore this email. Your password will not change.",
        charset="utf-8")
    try:
        context = ssl.create_default_context()
        if settings.ssl:
            server = smtplib.SMTP_SSL(settings.host, settings.port, timeout=_TIMEOUT_SECONDS, context=context)
        else:
            server = smtplib.SMTP(settings.host, settings.port, timeout=_TIMEOUT_SECONDS)
        with server:
            if settings.start_tls:
                server.starttls(context=context)
            if settings.username:
                server.login(settings.username, settings.password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exception:
        logger.warning("Could not send password reset email (%s)", type(exception).__name__)
