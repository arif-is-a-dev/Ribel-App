"""Blueprint halaman utama dan dashboard."""

from flask import Blueprint, current_app, redirect, render_template, session, url_for

from ribel.db import get_db
from ribel.repositories import users as users_repo
from ribel.security import login_required
from ribel.services import scoring

bp = Blueprint("main", __name__)


@bp.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    user_id = session["user_id"]
    return render_template(
        "dashboard.html",
        username=session["username"],
        scores=scoring.get_scores(db, user_id),
        top_scores=users_repo.leaderboard(db, current_app.config["LEADERBOARD_LIMIT"]),
    )
