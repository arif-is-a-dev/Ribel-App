"""Blueprint latihan kuis: Matematika dan Kosakata."""

import random

from flask import (
    Blueprint,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ribel.constants import SUBJECTS
from ribel.db import get_db
from ribel.repositories import questions as questions_repo
from ribel.security import login_required
from ribel.services import game, quiz

bp = Blueprint("practice", __name__)

# Label booster dipakai layar hasil untuk menampilkan booster yang terpakai.
BOOSTER_LABELS = {name: info["label"] for name, info in game.BOOSTER_INFO.items()}


def _current_attempt(db, keys, user_id, subject):
    """Ambil percobaan dari session, pastikan memang milik pengguna ini."""
    attempt = quiz.get_attempt(db, session.get(keys["attempt"]))
    if attempt is None:
        return None
    if attempt["user_id"] != user_id or attempt["subject"] != subject:
        return None
    return attempt


def _attempt_or_start(db, keys, user_id, subject):
    """Ambil percobaan aktif, atau mulai percobaan baru bila belum ada."""
    attempt = _current_attempt(db, keys, user_id, subject)
    if attempt is None:
        attempt = quiz.get_attempt(db, quiz.start_attempt(db, user_id, subject))
        session[keys["attempt"]] = attempt["id"]
    return attempt


def _active_index(keys, total):
    """Indeks soal yang sedang dikerjakan, atau None bila sesi sudah berakhir."""
    index = session.get(keys["index"], 0)
    if not isinstance(index, int) or index < 0 or index >= total:
        return None
    return index


def _session_questions(keys, all_questions, limit):
    """Pilih soal untuk satu sesi dan simpan pilihannya di session.

    Bila bank soal lebih banyak dari ``limit``, soal dipilih acak supaya tiap
    sesi terasa berbeda. Pilihan disimpan di session agar urutan soal tetap
    sama selama sesi berjalan, termasuk ketika halaman di-refresh.
    """
    if not all_questions:
        return []
    by_id = {question["id"]: question for question in all_questions}
    plan = session.get(keys["plan"])
    if not isinstance(plan, list) or not plan or any(qid not in by_id for qid in plan):
        selected = all_questions
        if limit and len(all_questions) > limit:
            selected = random.sample(all_questions, limit)
        plan = [question["id"] for question in selected]
        session[keys["plan"]] = plan
    return [by_id[qid] for qid in plan]


def _can_second_chance(db, attempt, question, timed_out):
    """Second Chance hanya berlaku untuk jawaban salah, bukan waktu habis."""
    if timed_out or attempt is None or question is None:
        return False
    answer = quiz.get_answer(db, attempt["id"], question["id"])
    return answer is not None and not answer["is_correct"]


def _render(subject, **context):
    """Render quiz.html dengan nilai default yang lengkap."""
    data = {
        "subject": subject,
        "subject_label": SUBJECTS[subject],
        # Dipakai header bersama "partials/_nav_app.html" agar sama dengan Dashboard.
        "username": session.get("username"),
        "question": None,
        "feedback": None,
        "error": None,
        "show_next": False,
        "last_correct": None,
        "current_num": 0,
        "total": 0,
        "finished": False,
        "session_score": 0,
        "session_correct": 0,
        # Fase 5: timer, booster, dan combo.
        "timer_seconds": current_app.config["QUIZ_TIMER_SECONDS"],
        "remaining": 0,
        "hidden_options": [],
        "boosters": [],
        "booster_labels": BOOSTER_LABELS,
        "notice": None,
        "combo": 0,
        "best_streak": 0,
        "best_streak_final": 0,
        "timed_out": False,
        "last_points": 0,
        "double_armed": False,
        "booster_used": [],
        "can_second_chance": False,
    }
    data.update(context)
    return render_template("quiz.html", **data)


def _mark_timeout(db, keys, attempt, question):
    """Catat waktu habis untuk soal aktif, lalu lanjut ke soal berikutnya."""
    quiz.record_timeout(db, attempt, question)
    session[keys["feedback"]] = game.TIMEOUT_FEEDBACK
    session[keys["last_correct"]] = False
    session[keys["timed_out"]] = True
    game.register_result(keys, False, 0)
    session[keys["index"]] = session.get(keys["index"], 0) + 1


def _handle_timeout(db, keys, user_id, subject, questions, total, grace, endpoint):
    """Tangani laporan waktu habis yang dikirim halaman kuis."""
    if session.get(keys["feedback"]) is not None:
        return redirect(url_for(endpoint))

    index = _active_index(keys, total)
    if index is None:
        return redirect(url_for(endpoint))

    # Server hanya menerima waktu habis bila tenggat benar-benar sudah lewat,
    # sehingga laporan dari browser tidak bisa dipakai untuk melewati soal.
    if game.deadline_for(keys, index) is None:
        return redirect(url_for(endpoint))
    if not game.deadline_expired(keys, index, grace):
        return redirect(url_for(endpoint))

    attempt = _attempt_or_start(db, keys, user_id, subject)
    _mark_timeout(db, keys, attempt, questions[index])
    return redirect(url_for(endpoint))


def _handle_booster(
    db, keys, user_id, subject, questions, total, min_options, freeze_seconds, endpoint
):
    """Aktifkan booster bila statusnya tersedia dan fasenya sesuai."""
    name = request.form.get("booster")
    if name not in game.BOOSTERS:
        return redirect(url_for(endpoint))

    index = _active_index(keys, total)
    if index is None:
        return redirect(url_for(endpoint))

    if game.booster_state(keys)[name] == "used":
        return redirect(url_for(endpoint))

    feedback_phase = session.get(keys["feedback"]) is not None
    # Saat umpan balik, indeks session sudah menunjuk soal berikutnya sehingga
    # soal yang baru dinilai berada di indeks sebelumnya.
    question_index = index - 1 if feedback_phase else index
    if question_index < 0:
        return redirect(url_for(endpoint))

    question = questions[question_index]
    timed_out = bool(session.get(keys["timed_out"]))
    attempt = _current_attempt(db, keys, user_id, subject)
    applied = False

    if name == "fifty":
        applied = not feedback_phase and game.apply_fifty(
            keys, index, question, min_options
        )
    elif name == "freeze":
        applied = not feedback_phase and game.extend_deadline(
            keys, index, freeze_seconds
        )
    elif name == "double":
        if not feedback_phase:
            game.arm_double(keys, index)
            applied = True
    elif name == "chance" and feedback_phase:
        if _can_second_chance(db, attempt, question, timed_out):
            if quiz.revoke_answer(db, attempt["id"], question["id"]):
                # Kembalikan sesi ke soal yang sama supaya bisa dijawab lagi.
                session[keys["index"]] = question_index
                session.pop(keys["feedback"], None)
                session.pop(keys["last_correct"], None)
                session.pop(keys["timed_out"], None)
                applied = True

    if applied:
        game.use_booster(keys, name)
        session[keys["notice"]] = game.BOOSTER_NOTICE[name]
    return redirect(url_for(endpoint))


def _quiz(subject):
    """Handler generik untuk halaman kuis Matematika dan Kosakata."""
    db = get_db()
    user_id = session["user_id"]
    keys = game.session_keys(subject)
    all_questions = questions_repo.list_for_subject(db, subject)
    questions = _session_questions(
        keys, all_questions, current_app.config["QUIZ_QUESTIONS_PER_SESSION"]
    )
    total = len(questions)
    points_per_correct = current_app.config["POINTS_PER_CORRECT"]
    timer_seconds = current_app.config["QUIZ_TIMER_SECONDS"]
    freeze_seconds = current_app.config["QUIZ_FREEZE_SECONDS"]
    grace = current_app.config["QUIZ_TIMER_GRACE_SECONDS"]
    min_options = current_app.config["QUIZ_FIFTY_MIN_OPTIONS"]
    endpoint = f"practice.{subject}"

    if total == 0:
        return _render(subject, total=0, finished=True)

    if request.method == "POST":
        action = request.form.get("action", "answer")

        if action == "next":
            session.pop(keys["feedback"], None)
            session.pop(keys["last_correct"], None)
            session.pop(keys["timed_out"], None)
            return redirect(url_for(endpoint))

        if action == "restart":
            game.clear(keys)
            return redirect(url_for(endpoint))

        if action == "booster":
            return _handle_booster(
                db,
                keys,
                user_id,
                subject,
                questions,
                total,
                min_options,
                freeze_seconds,
                endpoint,
            )

        if action == "timeout":
            return _handle_timeout(
                db, keys, user_id, subject, questions, total, grace, endpoint
            )

        # action == "answer"
        # Bila masih ada feedback yang belum dikonsumsi, soal terakhir sudah
        # dinilai. Abaikan pengiriman ulang (refresh atau kirim ulang form).
        if session.get(keys["feedback"]) is not None:
            return redirect(url_for(endpoint))

        index = _active_index(keys, total)
        if index is None:
            return redirect(url_for(endpoint))

        question = questions[index]
        # Tenggat hanya dipasang bila belum ada, jadi refresh tidak mengatur
        # ulang hitungan waktu yang sedang berjalan.
        game.ensure_deadline(keys, index, timer_seconds)

        # Jawaban yang tiba setelah tenggat tidak dinilai. Server memakai waktu
        # server, bukan angka hitung mundur yang dikirim browser.
        if game.deadline_expired(keys, index, grace):
            attempt = _attempt_or_start(db, keys, user_id, subject)
            _mark_timeout(db, keys, attempt, question)
            return redirect(url_for(endpoint))

        jawaban = request.form.get("jawaban")
        if not jawaban or jawaban not in question["options"]:
            attempt = _current_attempt(db, keys, user_id, subject)
            return _render(
                subject,
                question=question,
                error="Silakan pilih salah satu jawaban dulu.",
                current_num=index + 1,
                total=total,
                session_score=attempt["score"] if attempt else 0,
                session_correct=attempt["correct_count"] if attempt else 0,
                **game.question_context(keys, question, index, min_options),
            )

        attempt = _attempt_or_start(db, keys, user_id, subject)

        # Double Points menggandakan poin soal ini; perhitungannya di server.
        points = points_per_correct
        if game.is_double_armed(keys, index):
            points = points_per_correct * 2

        result = quiz.record_answer(db, attempt, question, jawaban, points)
        game.register_result(keys, result["is_correct"], result["points"])

        if result["is_correct"]:
            session[keys["feedback"]] = "Mantap! Jawaban kamu benar."
            session[keys["last_correct"]] = True
        else:
            session[keys["feedback"]] = (
                f"Yah, kurang tepat. Jawaban yang benar: {question['answer']}."
            )
            session[keys["last_correct"]] = False

        session[keys["index"]] = index + 1
        return redirect(url_for(endpoint))

    # GET
    index = session.get(keys["index"], 0)
    feedback = session.get(keys["feedback"])
    last_correct = session.get(keys["last_correct"])
    timed_out = bool(session.get(keys["timed_out"]))
    attempt = _current_attempt(db, keys, user_id, subject)
    session_score = attempt["score"] if attempt else 0
    session_correct = attempt["correct_count"] if attempt else 0
    best = game.best_streak(keys)

    if index >= total:
        if attempt is not None:
            quiz.finish_attempt(db, attempt["id"])
        booster_used = game.used_boosters(keys)
        game.clear(keys)
        return _render(
            subject,
            feedback=feedback,
            last_correct=last_correct,
            current_num=total,
            total=total,
            finished=True,
            session_score=session_score,
            session_correct=session_correct,
            best_streak_final=best,
            booster_used=booster_used,
        )

    # Simpan indeks aktif secara eksplisit supaya status sesi konsisten dan
    # dapat diverifikasi, misalnya saat menerima laporan waktu habis.
    session[keys["index"]] = index

    if feedback is not None:
        # Indeks session sudah menunjuk soal berikutnya; soal yang baru dinilai
        # berada di indeks sebelumnya.
        answered = questions[index - 1] if index - 1 >= 0 else None
        can_chance = _can_second_chance(db, attempt, answered, timed_out)
        return _render(
            subject,
            feedback=feedback,
            last_correct=last_correct,
            timed_out=timed_out,
            current_num=index,
            total=total,
            show_next=True,
            session_score=session_score,
            session_correct=session_correct,
            combo=game.current_streak(keys),
            best_streak=best,
            last_points=session.get(keys["last_points"], 0),
            can_second_chance=can_chance,
            boosters=game.booster_view(
                keys, answered, min_options, "feedback", can_chance
            ),
        )

    question = questions[index]
    game.ensure_deadline(keys, index, timer_seconds)
    return _render(
        subject,
        question=question,
        current_num=index + 1,
        total=total,
        session_score=session_score,
        session_correct=session_correct,
        **game.question_context(keys, question, index, min_options),
    )


@bp.route("/matematika", methods=["GET", "POST"])
@login_required
def matematika():
    return _quiz("matematika")


@bp.route("/kosakata", methods=["GET", "POST"])
@login_required
def kosakata():
    return _quiz("kosakata")
