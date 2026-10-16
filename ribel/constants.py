"""Konstanta bersama aplikasi Ribel."""

SUBJECTS = {
    "matematika": "Matematika",
    "kosakata": "Kosakata",
}

# Berkas data lama. Hanya dibaca oleh skrip impor, tidak pernah diubah.
LEGACY_USERS_FILE = "users.txt"
LEGACY_QUESTION_FILES = {
    "matematika": "soal_mtk.txt",
    "kosakata": "soal_kosakata.txt",
}

# Nilai kolom status pada tabel quiz_attempts.
ATTEMPT_IN_PROGRESS = "in_progress"
ATTEMPT_FINISHED = "finished"
