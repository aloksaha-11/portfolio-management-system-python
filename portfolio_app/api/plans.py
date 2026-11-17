"""Create your own plan."""
from flask import Blueprint, g

from ..db import get_db
from ..jsonutil import decimal_field, json_response, object_field, read_body, text_field
from ..security import login_required
from ..services import plans

bp = Blueprint("plans", __name__)


@bp.post("/api/plans")
@login_required
def create_plan():
    """Creates a plan, computes the suggested split and saves it."""
    body = read_body()
    current = object_field(body, "current")
    amounts = None if current is None else {key: decimal_field(current, key) for key in plans.KEYS}
    result = plans.create(get_db(), g.user_id, text_field(body, "riskProfile"), amounts,
                          decimal_field(body, "budget"))
    return json_response(result, 201)


@bp.get("/api/plans")
@login_required
def recent_plans():
    """The signed-in user's 10 most recent plans, newest first."""
    return json_response(plans.recent(get_db(), g.user_id))
