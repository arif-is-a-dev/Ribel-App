"""Layanan percobaan kuis: pemilihan soal, pencatatan jawaban, dan skor."""

from ribel.constants import ATTEMPT_FINISHED, ATTEMPT_IN_PROGRESS, SUBJECTS
from ribel.services import scoring


class QuizError(Exception):
    """Kesalahan yang berkaitan dengan alur kuis."""


def start_attempt(db, user_id, subject):
    """Mulai percobaan baru dan kembalikan id-nya."""
    if subject not in SUBJECTS:
        raise QuizError(f"Mata pelajaran {subject!r} tidak dikenal.")
    cursor = db.execute(
        "INSERT INTO quiz_attempts (user_id, subject, status) VALUES (?, ?, ?)",
        (user_id, subject, ATTEMPT_IN_PROGRESS),
    )
    db.commit()
    return cursor.lastrowid


def get_attempt(db, attempt_id):
    if attempt_id is None:
        return None
    return db.execute(
        "SELECT * FROM quiz_attempts WHERE id = ?", (attempt_id,)
    ).fetchone()


def get_answer(db, attempt_id, question_id):
    """Ambil baris jawaban satu soal pada satu percobaan, bila ada."""
    return db.execute(
        "SELECT is_correct, selected_answer FROM quiz_answers "
        "WHERE attempt_id = ? AND question_id = ?",
        (attempt_id, question_id),
    ).fetchone()


def record_answer(db, attempt, question, selected_answer, points_per_correct):
    """Catat jawaban satu soal dan beri poin bila benar.

    Mengembalikan dict berisi is_correct, awarded, dan points. Bila soal ini
    sudah pernah dinilai pada percobaan yang sama, poin TIDAK ditambahkan lagi.
    """
    is_correct = selected_answer == question["answer"]
    points = points_per_correct if is_correct else 0

    cursor = db.execute(
        """
        INSERT INTO quiz_answers
            (attempt_id, question_id, selected_answer, is_correct, points_awarded)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (attempt_id, question_id) DO NOTHING
        """,
        (
            attempt["id"],
            question["id"],
            selected_answer,
            1 if is_correct else 0,
            points,
        ),
    )
    awarded = cursor.rowcount == 1

    if awarded:
        db.execute(
            "UPDATE quiz_attempts SET correct_count = correct_count + ?, "
            "score = score + ? WHERE id = ?",
            (1 if is_correct else 0, points, attempt["id"]),
        )
        if points:
            scoring.add_points(db, attempt["user_id"], attempt["subject"], points)

    db.commit()
    return {"is_correct": is_correct, "awarded": awarded, "points": points}


def finish_attempt(db, attempt_id):
    """Tandai percobaan selesai. Aman dipanggil berulang."""
    db.execute(
        "UPDATE quiz_attempts SET status = ?, finished_at = datetime('now') "
        "WHERE id = ? AND status != ?",
        (ATTEMPT_FINISHED, attempt_id, ATTEMPT_FINISHED),
    )
    db.commit()

def record_timeout(db, attempt, question):
    """Catat soal yang kehabisan waktu.

    Baris jawaban tetap dibuat tanpa pilihan jawaban dan tanpa poin, sehingga
    UNIQUE (attempt_id, question_id) mencegah soal yang sama dinilai lagi
    setelah waktu habis.
    """
    cursor = db.execute(
        """
        INSERT INTO quiz_answers
            (attempt_id, question_id, selected_answer, is_correct, points_awarded)
        VALUES (?, ?, NULL, 0, 0)
        ON CONFLICT (attempt_id, question_id) DO NOTHING
        """,
        (attempt["id"], question["id"]),
    )
    awarded = cursor.rowcount == 1
    db.commit()
    return {"awarded": awarded}

def revoke_answer(db, attempt_id, question_id):
    """Batalkan jawaban yang salah agar soal bisa dicoba lagi (Second Chance).

    Hanya berlaku untuk jawaban yang salah. Jawaban benar tidak pernah dihapus,
    jadi skor dan jumlah jawaban benar tidak pernah berkurang.
    """
    row = db.execute(
        "SELECT is_correct FROM quiz_answers WHERE attempt_id = ? AND question_id = ?",
        (attempt_id, question_id),
    ).fetchone()
    if row is None or row["is_correct"]:
        return False
    db.execute(
        "DELETE FROM quiz_answers WHERE attempt_id = ? AND question_id = ?",
        (attempt_id, question_id),
    )
    db.commit()
    return True
