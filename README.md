PROTOTIPE PROJECT UAS PEMROGRAMAN DASAR

Aplikasi kuis belajar (Matematika dan Kosakata) berbasis Flask dengan penyimpanan SQLite.

## Demo Website
https://bit.ly/Ribel

## Struktur Proyek

- `app.py` - titik masuk aplikasi.
- `config.py` - konfigurasi; secret key hanya dibaca dari environment.
- `ribel/` - paket aplikasi (`db.py`, `schema.sql`, `blueprints/`, `repositories/`, `services/`).
- `templates/` - kerangka bersama `base.html` beserta halaman dan partial.
- `static/css/` - `base.css` (design token "Studio Editorial"), lalu
  `landing.css`, `auth.css`, `dashboard.css`, dan `quiz.css` untuk halaman terkait.
- `static/js/quiz.js` - hitung mundur, interaksi pilihan, dan animasi halaman kuis.
- `scripts/import_legacy.py` - impor data lama, idempoten.
- `scripts/seed_bank.py` - seed bank soal tambahan, idempoten.
- `data/` - bank soal tambahan (`bank_matematika.txt`, `bank_kosakata.txt`) dan
  `patch_opsi_keempat.txt` untuk melengkapi soal lama menjadi empat opsi.
- `tests/` - pengujian dengan `unittest`.

## Menjalankan (Windows PowerShell)

    $env:RIBEL_SECRET_KEY = "<secret-key-acak>"
    $env:RIBEL_CONFIG = "development"
    py -3.13 scripts/import_legacy.py
    py -3.13 scripts/seed_bank.py
    py -3.13 app.py

Buat secret key acak dengan:

    py -3.13 -c "import secrets; print(secrets.token_hex(32))"

## Pengujian

    py -3.13 -m unittest discover -s tests -t . -v

## Fitur kuis

- Timer 30 detik per soal; tenggat dihitung dan diverifikasi di server, bukan di browser.
- Empat booster sekali pakai per sesi: 50:50, Time Freeze, Double Points, dan Second Chance.
- Combo jawaban benar berurutan, serta layar hasil dengan skor sesi dari database.
- Setiap soal memiliki empat opsi unik (A-D) dengan satu jawaban benar.
- Satu sesi mengambil 10 soal acak per mata pelajaran agar tiap sesi bervariasi.

## Bank soal

- `soal_mtk.txt` dan `soal_kosakata.txt` adalah data awal dan hanya dibaca.
- `data/bank_matematika.txt` dan `data/bank_kosakata.txt` menambah 50 soal per
  mata pelajaran, sehingga tersedia 53 soal Matematika dan 53 soal Kosakata.
- `scripts/seed_bank.py` bersifat idempoten: dijalankan berulang kali tidak
  membuat duplikat, dan tidak menghapus akun, riwayat, maupun skor pengguna.
- `py -3.13 scripts/seed_bank.py --check` hanya memvalidasi berkas bank soal.

## Catatan

- `users.txt`, `soal_mtk.txt`, dan `soal_kosakata.txt` hanya dibaca oleh skrip impor dan tidak pernah diubah.
- Tidak ada secret key bawaan di kode. Aplikasi menolak dijalankan bila `RIBEL_SECRET_KEY` kosong.
