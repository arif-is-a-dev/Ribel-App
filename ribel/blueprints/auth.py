"""Blueprint autentikasi: login, registrasi, dan logout."""

from flask import Blueprint, redirect, render_template, request, session, url_for

from ribel.db import get_db
from ribel.forms import LoginForm, SignupForm, first_error
from ribel.repositories import users as users_repo
from ribel.security import hash_password, verify_password

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        user = users_repo.get_by_username(get_db(), username)
        if user is not None and verify_password(
            user["password_hash"], form.password.data
        ):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("main.dashboard"))
        return render_template(
            "login.html", form=form, error="Username atau password salah."
        )

    if request.method == "POST":
        return render_template(
            "login.html",
            form=form,
            error=first_error(form, "Username atau password salah."),
        )
    return render_template("login.html", form=form)


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))

    form = SignupForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        email = form.email.data.strip()
        db = get_db()
        if users_repo.get_by_username(db, username) is not None:
            return render_template(
                "signup.html", form=form, error="Username sudah dipakai."
            )
        users_repo.create(db, username, email, hash_password(form.password.data))
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        return render_template(
            "signup.html",
            form=form,
            error=first_error(form, "Semua field wajib diisi."),
        )
    return render_template("signup.html", form=form)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("main.home"))
