"""Akses database SQLite memakai pustaka standar ``sqlite3``."""

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def connect(database):
    """Buat koneksi SQLite mandiri (dipakai di luar konteks request)."""
    path = Path(database)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """Ambil koneksi untuk request yang sedang berjalan."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(exc=None):
    """Tutup koneksi di akhir request."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def read_schema():
    return SCHEMA_PATH.read_text(encoding="utf-8")


def init_db(conn):
    """Buat seluruh tabel yang dibutuhkan. Aman dijalankan berulang."""
    conn.executescript(read_schema())
    conn.commit()


def init_app(app):
    app.teardown_appcontext(close_db)
