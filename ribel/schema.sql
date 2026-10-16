-- Skema database Ribel (SQLite).
-- Memakai CREATE TABLE IF NOT EXISTS sehingga aman dijalankan berulang.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    email         TEXT    NOT NULL,
    password_hash TEXT    NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    subject        TEXT    NOT NULL,
    prompt         TEXT    NOT NULL,
    correct_answer TEXT    NOT NULL,
    source_ref     TEXT    NOT NULL,
    position       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (subject, source_ref)
);

CREATE TABLE IF NOT EXISTS question_options (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    option_text TEXT    NOT NULL,
    position    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_question_options_question
    ON question_options (question_id, position);

CREATE TABLE IF NOT EXISTS user_scores (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT    NOT NULL,
    score   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, subject)
);

CREATE TABLE IF NOT EXISTS quiz_attempts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject       TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'in_progress',
    correct_count INTEGER NOT NULL DEFAULT 0,
    score         INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    finished_at   TEXT
);

CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user
    ON quiz_attempts (user_id, subject, status);

-- UNIQUE (attempt_id, question_id) adalah kunci pencegahan skor ganda:
-- satu soal hanya boleh dinilai sekali dalam satu percobaan.
CREATE TABLE IF NOT EXISTS quiz_answers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id      INTEGER NOT NULL REFERENCES quiz_attempts(id) ON DELETE CASCADE,
    question_id     INTEGER NOT NULL REFERENCES questions(id),
    selected_answer TEXT,
    is_correct      INTEGER NOT NULL DEFAULT 0,
    points_awarded  INTEGER NOT NULL DEFAULT 0,
    answered_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (attempt_id, question_id)
);
