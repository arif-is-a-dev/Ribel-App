"""Konfigurasi aplikasi Ribel.

Catatan keamanan: tidak ada secret key bawaan yang tertanam di kode.
Secret key hanya dibaca dari environment variable ``RIBEL_SECRET_KEY``.
Bila variabel tersebut kosong, aplikasi menolak dijalankan (fail closed).
"""

import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATABASE = str(BASE_DIR / "instance" / "ribel.sqlite3")

SECRET_KEY_ENV = "RIBEL_SECRET_KEY"
CONFIG_ENV = "RIBEL_CONFIG"
DATABASE_ENV = "RIBEL_DATABASE"


def read_secret_key():
    """Baca secret key dari environment. Kembalikan None bila tidak diisi."""
    value = os.environ.get(SECRET_KEY_ENV)
    if value is None:
        return None
    value = value.strip()
    return value or None


class BaseConfig:
    """Konfigurasi dasar yang dipakai semua environment."""

    # Wajib diisi dari environment; tidak ada nilai fallback.
    SECRET_KEY = None

    DATABASE = os.environ.get(DATABASE_ENV) or DEFAULT_DATABASE

    # Proteksi CSRF untuk seluruh request yang mengubah data.
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # Cookie session.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

    MAX_CONTENT_LENGTH = 1024 * 1024

    # Aturan permainan.
    POINTS_PER_CORRECT = 10
    LEADERBOARD_LIMIT = 5

    # Timer dan booster kuis (Fase 5).
    # Server adalah sumber kebenaran untuk batas waktu: nilai ini hanya
    # dipakai untuk menghitung tenggat di sisi server, bukan di browser.
    QUIZ_TIMER_SECONDS = 30
    QUIZ_FREEZE_SECONDS = 5
    # Toleransi kecil untuk latensi jaringan saat memeriksa tenggat.
    QUIZ_TIMER_GRACE_SECONDS = 1.5
    # 50:50 hanya masuk akal bila masih ada dua opsi salah untuk disembunyikan.
    QUIZ_FIFTY_MIN_OPTIONS = 4

    # Batas jumlah soal per sesi latihan. Bila bank soal lebih banyak dari
    # nilai ini, soal dipilih acak agar setiap sesi terasa berbeda. Bila bank
    # lebih sedikit, seluruh soal tetap dipakai.
    QUIZ_QUESTIONS_PER_SESSION = 10


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestingConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    # Key acak per proses, hanya untuk pengujian otomatis.
    # Bukan nilai rahasia dan tidak dipakai di lingkungan nyata.
    SECRET_KEY = secrets.token_hex(32)


CONFIGS = {
    "development": DevelopmentConfig,
    "dev": DevelopmentConfig,
    "production": ProductionConfig,
    "prod": ProductionConfig,
    "testing": TestingConfig,
    "test": TestingConfig,
}

DEFAULT_CONFIG = "production"


def get_config(name=None):
    """Ambil kelas konfigurasi berdasarkan nama atau env RIBEL_CONFIG."""
    key = (name or os.environ.get(CONFIG_ENV) or DEFAULT_CONFIG).strip().lower()
    if key not in CONFIGS:
        raise RuntimeError(
            f"Konfigurasi {key!r} tidak dikenal. "
            f"Pilihan yang tersedia: {sorted(CONFIGS)}."
        )
    return CONFIGS[key]
