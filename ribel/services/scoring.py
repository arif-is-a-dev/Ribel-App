"""Layanan skor pengguna."""

from ribel.constants import SUBJECTS


def get_scores(db, user_id):
    """Skor per mata pelajaran milik satu pengguna."""
    scores = {subject: 0 for subject in SUBJECTS}
    rows = db.execute(
        "SELECT subject, score FROM user_scores WHERE user_id = ?", (user_id,)
    ).fetchall()
    for row in rows:
        scores[row["subject"]] = row["score"]
    return scores


def total_score(db, user_id):
    row = db.execute(
        "SELECT COALESCE(SUM(score), 0) AS total FROM user_scores WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    return row["total"]


def add_points(db, user_id, subject, points):
    """Tambah skor pengguna. Tanpa commit; pemanggil yang menutup transaksi."""
    if points <= 0:
        return
    db.execute(
        """
        INSERT INTO user_scores (user_id, subject, score) VALUES (?, ?, ?)
        ON CONFLICT (user_id, subject) DO UPDATE SET score = score + excluded.score
        """,
        (user_id, subject, points),
    )
