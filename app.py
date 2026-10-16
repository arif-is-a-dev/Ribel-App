"""Titik masuk aplikasi Ribel.

Konfigurasi dibaca dari environment:
    RIBEL_SECRET_KEY  (wajib) secret key Flask; tidak ada nilai bawaan.
    RIBEL_CONFIG      development | production | testing (default: production).
    RIBEL_DATABASE    lokasi berkas SQLite (opsional).

Jalankan dari direktori proyek, contohnya:

    $env:RIBEL_SECRET_KEY = "<secret-key-acak>"
    $env:RIBEL_CONFIG = "development"
    py -3.13 app.py
"""

from ribel import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config.get("DEBUG", False))
