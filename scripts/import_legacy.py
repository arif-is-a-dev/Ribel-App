"""Impor data lama Ribel ke database SQLite.

Sifat skrip ini:

* Idempoten: aman dijalankan berulang, data yang sudah ada tidak diduplikasi.
* Hanya membaca berkas sumber (users.txt dan berkas soal); tidak pernah mengubahnya.
* Tidak menampilkan username, email, atau password. Keluarannya hanya agregat.

Contoh pemakaian dari direktori proyek:

    py -3.13 scripts/import_legacy.py
    py -3.13 scripts/import_legacy.py --verify-only
"""

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import DATABASE_ENV, DEFAULT_DATABASE
from ribel import constants
from ribel.db import connect, init_db
from ribel.security import hash_password

USER_COLUMNS = 5
MIN_QUESTION_PARTS = 3


def resolve_database(explicit=None):
    """Tentukan lokasi berkas SQLite: argumen, lalu env, lalu default."""
    return explicit or os.environ.get(DATABASE_ENV) or DEFAULT_DATABASE


def parse_users(path):
    """Baca users.txt. Format: username,email,password,skor_mtk,skor_kosakata."""
    users = []
    problems = []
    if not path.exists():
        problems.append(f"{path.name}: berkas tidak ditemukan")
        return users, problems

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != USER_COLUMNS:
            problems.append(
                f"{path.name} baris {lineno}: jumlah kolom {len(parts)}, "
                f"seharusnya {USER_COLUMNS}"
            )
            continue
        username, email, password, mtk, kosakata = (part.strip() for part in parts)
        if not username or not email or not password:
            problems.append(f"{path.name} baris {lineno}: ada kolom wajib yang kosong")
            continue
        try:
            scores = {"matematika": int(mtk), "kosakata": int(kosakata)}
        except ValueError:
            problems.append(f"{path.name} baris {lineno}: skor bukan bilangan bulat")
            continue
        if min(scores.values()) < 0:
            problems.append(f"{path.name} baris {lineno}: skor bernilai negatif")
            continue
        users.append(
            {
                "username": username,
                "email": email,
                "password": password,
                "scores": scores,
            }
        )
    return users, problems


def parse_questions(path, subject):
    """Baca berkas soal. Format: pertanyaan;opsi1;opsi2;...;jawaban."""
    questions = []
    problems = []
    if not path.exists():
        problems.append(f"{path.name}: berkas tidak ditemukan")
        return questions, problems

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split(";")
        if len(parts) < MIN_QUESTION_PARTS:
            problems.append(
                f"{path.name} baris {lineno}: butuh pertanyaan, minimal satu opsi, "
                "dan jawaban"
            )
            continue
        prompt, *options, answer = (part.strip() for part in parts)
        if not prompt or not options or not answer:
            problems.append(f"{path.name} baris {lineno}: ada bagian yang kosong")
            continue
        if answer not in options:
            problems.append(f"{path.name} baris {lineno}: jawaban tidak ada di daftar opsi")
            continue
        questions.append(
            {
                "subject": subject,
                "prompt": prompt,
                "options": options,
                "answer": answer,
                "source_ref": f"{path.name}:{lineno}",
            }
        )
    return questions, problems


def load_legacy(source_dir):
    """Baca seluruh berkas lama. Mengembalikan (users, questions, problems)."""
    source_dir = Path(source_dir)
    problems = []

    users, user_problems = parse_users(source_dir / constants.LEGACY_USERS_FILE)
    problems.extend(user_problems)

    questions = {}
    for subject, file_name in constants.LEGACY_QUESTION_FILES.items():
        parsed, question_problems = parse_questions(source_dir / file_name, subject)
        problems.extend(question_problems)
        questions[subject] = parsed

    return users, questions, problems


def import_users(conn, users):
    """Impor akun. Skor lama hanya ditulis saat akun baru dibuat."""
    inserted = 0
    skipped = 0
    for user in users:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (user["username"],)
        ).fetchone()
        if existing is not None:
            skipped += 1
            continue
        cursor = conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?) "
            "ON CONFLICT (username) DO NOTHING",
            (user["username"], user["email"], hash_password(user["password"])),
        )
        if cursor.rowcount != 1:
            skipped += 1
            continue
        inserted += 1
        user_id = cursor.lastrowid
        for subject, score in user["scores"].items():
            conn.execute(
                "INSERT INTO user_scores (user_id, subject, score) VALUES (?, ?, ?)",
                (user_id, subject, score),
            )
    conn.commit()
    return {"inserted": inserted, "skipped": skipped}


def import_questions(conn, questions_by_subject):
    """Impor soal beserta opsinya. Soal yang sudah ada dilewati."""
    inserted = 0
    skipped = 0
    for subject, questions in questions_by_subject.items():
        for position, question in enumerate(questions):
            cursor = conn.execute(
                "INSERT INTO questions "
                "(subject, prompt, correct_answer, source_ref, position) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (subject, source_ref) DO NOTHING",
                (
                    subject,
                    question["prompt"],
                    question["answer"],
                    question["source_ref"],
                    position,
                ),
            )
            if cursor.rowcount != 1:
                skipped += 1
                continue
            inserted += 1
            question_id = cursor.lastrowid
            for option_position, option in enumerate(question["options"]):
                conn.execute(
                    "INSERT INTO question_options (question_id, option_text, position) "
                    "VALUES (?, ?, ?)",
                    (question_id, option, option_position),
                )
    conn.commit()
    return {"inserted": inserted, "skipped": skipped}


def import_all(conn, users, questions_by_subject):
    """Jalankan seluruh impor dan kembalikan ringkasan jumlah baris."""
    return {
        "users": import_users(conn, users),
        "questions": import_questions(conn, questions_by_subject),
    }


def verify(conn, users, questions_by_subject):
    """Bandingkan database dengan berkas sumber. Keluaran hanya agregat."""
    lines = []

    db_users = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
    missing = 0
    for user in users:
        found = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (user["username"],)
        ).fetchone()
        if found is None:
            missing += 1
    lines.append(
        f"akun: sumber {len(users)}, database {db_users}, belum masuk {missing}"
    )

    unhashed = conn.execute(
        "SELECT COUNT(*) AS total FROM users "
        "WHERE password_hash NOT LIKE 'scrypt:%' AND password_hash NOT LIKE 'pbkdf2:%'"
    ).fetchone()["total"]
    lines.append(f"akun dengan password belum ter-hash: {unhashed}")

    for subject, questions in questions_by_subject.items():
        db_questions = conn.execute(
            "SELECT COUNT(*) AS total FROM questions WHERE subject = ?", (subject,)
        ).fetchone()["total"]
        db_options = conn.execute(
            "SELECT COUNT(*) AS total FROM question_options AS o "
            "JOIN questions AS q ON q.id = o.question_id WHERE q.subject = ?",
            (subject,),
        ).fetchone()["total"]
        source_options = sum(len(question["options"]) for question in questions)
        lines.append(
            f"soal {subject}: sumber {len(questions)} soal/{source_options} opsi, "
            f"database {db_questions} soal/{db_options} opsi"
        )

    source_totals = {}
    for user in users:
        for subject, score in user["scores"].items():
            source_totals[subject] = source_totals.get(subject, 0) + score
    db_totals = {
        row["subject"]: row["total"]
        for row in conn.execute(
            "SELECT subject, COALESCE(SUM(score), 0) AS total "
            "FROM user_scores GROUP BY subject"
        ).fetchall()
    }
    for subject in constants.SUBJECTS:
        lines.append(
            f"total skor {subject}: sumber {source_totals.get(subject, 0)}, "
            f"database {db_totals.get(subject, 0)}"
        )
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Impor data lama Ribel ke database SQLite."
    )
    parser.add_argument("--database", default=None, help="lokasi berkas SQLite tujuan")
    parser.add_argument(
        "--source-dir", default=str(BASE_DIR), help="direktori berkas data lama"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="lewati impor, hanya tampilkan hasil verifikasi",
    )
    args = parser.parse_args(argv)

    users, questions_by_subject, problems = load_legacy(args.source_dir)

    print("== Pembacaan berkas sumber ==")
    print(f"akun terbaca: {len(users)}")
    for subject, questions in questions_by_subject.items():
        print(f"soal {subject} terbaca: {len(questions)}")

    if problems:
        print("")
        print("== BERHENTI: format data lama tidak dapat diimpor dengan aman ==")
        for problem in problems:
            print(f"- {problem}")
        print("Tidak ada perubahan yang ditulis ke database.")
        return 1

    conn = connect(resolve_database(args.database))
    try:
        init_db(conn)

        if not args.verify_only:
            summary = import_all(conn, users, questions_by_subject)
            print("")
            print("== Hasil impor ==")
            print(
                f"akun baru: {summary['users']['inserted']}, "
                f"akun dilewati: {summary['users']['skipped']}"
            )
            print(
                f"soal baru: {summary['questions']['inserted']}, "
                f"soal dilewati: {summary['questions']['skipped']}"
            )

        print("")
        print("== Verifikasi ==")
        for line in verify(conn, users, questions_by_subject):
            print(f"- {line}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
