"""Paket aplikasi Ribel: kuis belajar Matematika dan Kosakata."""

from pathlib import Path

from flask import Flask
from flask_wtf import CSRFProtect

from config import SECRET_KEY_ENV, get_config, read_secret_key
from ribel import db

csrf = CSRFProtect()

__all__ = ["create_app", "csrf"]


# Template dan aset statis tetap berada di root proyek agar struktur
# tampilan tidak berubah pada fase ini.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_FOLDER = str(PROJECT_ROOT / "templates")
STATIC_FOLDER = str(PROJECT_ROOT / "static")


def create_app(config_name=None, overrides=None):
    """Buat instance Flask lengkap dengan blueprint dan proteksi CSRF."""
    app = Flask(
        __name__,
        template_folder=TEMPLATE_FOLDER,
        static_folder=STATIC_FOLDER,
    )

    app.config.from_object(get_config(config_name))

    if overrides:
        app.config.update(overrides)

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = read_secret_key()

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY belum diatur. Set environment variable "
            f"{SECRET_KEY_ENV} sebelum menjalankan aplikasi Ribel. "
            "Aplikasi tidak menyediakan secret key bawaan."
        )

    csrf.init_app(app)
    db.init_app(app)

    from ribel.blueprints.auth import bp as auth_bp
    from ribel.blueprints.main import bp as main_bp
    from ribel.blueprints.practice import bp as practice_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(practice_bp)

    return app
