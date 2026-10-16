"""Query tabel questions dan question_options."""


def list_for_subject(db, subject):
    """Ambil soal satu mata pelajaran sesuai urutan tampil."""
    rows = db.execute(
        "SELECT id, prompt, correct_answer FROM questions "
        "WHERE subject = ? ORDER BY position, id",
        (subject,),
    ).fetchall()

    questions = []
    for row in rows:
        options = db.execute(
            "SELECT option_text FROM question_options "
            "WHERE question_id = ? ORDER BY position, id",
            (row["id"],),
        ).fetchall()
        questions.append(
            {
                "id": row["id"],
                "question": row["prompt"],
                "options": [option["option_text"] for option in options],
                "answer": row["correct_answer"],
            }
        )
    return questions


def count_for_subject(db, subject):
    row = db.execute(
        "SELECT COUNT(*) AS total FROM questions WHERE subject = ?", (subject,)
    ).fetchone()
    return row["total"]
