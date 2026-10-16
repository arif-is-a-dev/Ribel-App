"""Helper keamanan: hashing password dan proteksi rute."""

from functools import wraps

from flask import redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(raw_password):
    """Hash password mentah memakai algoritma default Werkzeug."""
    return generate_password_hash(raw_password)


def verify_password(password_hash, raw_password):
    """Verifikasi password terhadap hash yang tersimpan."""
    if not password_hash or not raw_password:
        return False
    try:
        return check_password_hash(password_hash, raw_password)
    except ValueError:
        return False


def login_required(view):
    """Batasi akses rute hanya untuk pengguna yang sudah masuk."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped
