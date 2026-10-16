"""Query tabel users dan agregat skor untuk leaderboard."""


def get_by_username(db, username):
    return db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def get_by_id(db, user_id):
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create(db, username, email, password_hash):
    """Buat pengguna baru. Mengembalikan id pengguna."""
    cursor = db.execute(
        "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
        (username, email, password_hash),
    )
    db.commit()
    return cursor.lastrowid


def leaderboard(db, limit=5):
    """Peringkat berdasarkan total skor. Hanya username dan skor."""
    rows = db.execute(
        """
        SELECT u.username AS nama, COALESCE(SUM(s.score), 0) AS skor
        FROM users AS u
        LEFT JOIN user_scores AS s ON s.user_id = u.id
        GROUP BY u.id
        ORDER BY skor DESC, u.username ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [{"nama": row["nama"], "skor": row["skor"]} for row in rows]
