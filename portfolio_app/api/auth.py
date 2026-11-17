"""/api/auth: CSRF token, sign-up, login, logout, current user and password reset."""
from flask import Blueprint, g, request

from .. import security
from ..db import get_db
from ..jsonutil import empty_response, json_response, read_body, text_field
from ..services import accounts

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.get("/csrf")
def csrf():
    return json_response({"headerName": security.CSRF_HEADER, "token": security.csrf_token()})


@bp.post("/register")
def register():
    body = read_body()
    email = text_field(body, "email")
    user_id = accounts.register(get_db(), email, text_field(body, "password"))
    return json_response({"userId": user_id, "email": accounts.normalize_email(email)}, 201)


@bp.post("/login")
def login():
    body = read_body()
    outcome, user = accounts.authenticate(get_db(), text_field(body, "email"), text_field(body, "password"),
                                          request.remote_addr)
    if outcome == "limited":
        return json_response({"error": "login_failed", "message": "Login failed. Please try again later."}, 429)
    if outcome != "ok":
        return json_response({"error": "invalid_credentials", "message": "Email or password is incorrect."}, 401)
    security.sign_in(user)
    return json_response({"userId": user["user_id"], "email": user["email"]})


@bp.post("/logout")
def logout():
    security.sign_out()
    return empty_response(204)


@bp.get("/me")
@security.login_required
def me():
    return json_response({"userId": g.user_id, "email": g.user_email})


@bp.post("/password-reset/request")
def request_password_reset():
    body = read_body(required=False)
    accounts.request_reset(get_db(), text_field(body, "email"), request.remote_addr)
    return json_response({"message": "If an account exists for that email, password reset instructions "
                                     "will be sent shortly."}, 202)


@bp.post("/password-reset/confirm")
def confirm_password_reset():
    body = read_body(required=False)
    accounts.reset_password(get_db(), text_field(body, "token"), text_field(body, "newPassword"))
    return json_response({"message": "Your password has been reset. You can now log in."})

