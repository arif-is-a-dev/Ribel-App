import os
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = os.environ.get("RIBEL_SECRET_KEY", "ribel-dev-secret-key-change-in-prod")

# ---------- Konstanta ----------
USERS_FILE = "users.txt"
QUESTION_FILES = {
    "matematika": "soal_mtk.txt",
    "kosakata": "soal_kosakata.txt",
}
SUBJECT_LABELS = {
    "matematika": "Matematika",
    "kosakata": "Kosakata",
}
POINTS_PER_CORRECT = 10


# ---------- Utility: User Storage ----------
def read_users():
    """Baca users.txt menjadi dict. Toleran terhadap baris kosong/format rusak."""
    users = {}
    if not os.path.exists(USERS_FILE):
        return users
    with open(USERS_FILE, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            username, email, password, mtk, kosa = parts[:5]
            try:
                mtk_score = int(mtk)
                kosa_score = int(kosa)
            except ValueError:
                mtk_score, kosa_score = 0, 0
            users[username] = {
                "email": email,
                "password": password,
                "scores": {
                    "matematika": mtk_score,
                    "kosakata": kosa_score,
                },
            }
    return users


def write_users(users):
    """Tulis seluruh dict users kembali ke file."""
    with open(USERS_FILE, "w", encoding="utf-8") as file:
        for user, data in users.items():
            file.write(
                f"{user},{data['email']},{data['password']},"
                f"{data['scores']['matematika']},{data['scores']['kosakata']}\n"
            )


def save_user(username, email, password):
    """Tambahkan user baru ke file."""
    with open(USERS_FILE, "a", encoding="utf-8") as file:
        file.write(f"{username},{email},{password},0,0\n")


def update_user_score(username, subject, score_increment):
    if not username or subject not in ("matematika", "kosakata"):
        return
    users = read_users()
    if username not in users:
        return
    users[username]["scores"][subject] += score_increment
    write_users(users)


# ---------- Utility: Soal ----------
def read_questions(file_name):
    """Baca soal dari file. Format: pertanyaan;opsi1;opsi2;opsi3;jawaban"""
    questions = []
    if not os.path.exists(file_name):
        return questions
    with open(file_name, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            parts = line.split(";")
            if len(parts) < 3:
                continue
            question, *options, answer = parts
            questions.append({
                "question": question,
                "options": options,
                "answer": answer,
            })
    return questions


# ---------- Decorator login ----------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("username"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


# ---------- Routes ----------
@app.route("/")
def home():
    if session.get("username"):
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users = read_users()
        if username in users and users[username]["password"] == password:
            session.clear()
            session["username"] = username
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Username atau password salah.")
    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        # Validasi: tidak boleh ada koma (karena delimiter), tidak boleh kosong
        if not username or not email or not password:
            return render_template("signup.html", error="Semua field wajib diisi.")
        if "," in username or "," in email:
            return render_template("signup.html", error="Username/email tidak boleh mengandung koma.")

        users = read_users()
        if username in users:
            return render_template("signup.html", error="Username sudah dipakai.")

        save_user(username, email, password)
        return redirect(url_for("login"))
    return render_template("signup.html")


@app.route("/dashboard")
@login_required
def dashboard():
    username = session["username"]
    users = read_users()

    scores = users.get(username, {}).get("scores", {"matematika": 0, "kosakata": 0})

    all_scores = []
    for user, data in users.items():
        total_score = sum(data.get("scores", {}).values())
        all_scores.append({"nama": user, "skor": total_score})

    top_scores = sorted(all_scores, key=lambda x: x["skor"], reverse=True)[:5]

    return render_template(
        "dashboard.html",
        username=username,
        scores=scores,
        top_scores=top_scores,
    )


def _quiz_handler(subject):
    """Handler generik untuk halaman quiz (matematika/kosakata)."""
    questions = read_questions(QUESTION_FILES[subject])
    total = len(questions)

    # Key session yang berbeda per subject -> tidak saling tabrakan
    idx_key = f"{subject}_index"
    fb_key = f"{subject}_feedback"
    correct_key = f"{subject}_correct"
    last_key = f"{subject}_last_correct"

    username = session["username"]

    # Tidak ada soal sama sekali
    if total == 0:
        return render_template(
            "quiz.html",
            subject=subject,
            subject_label=SUBJECT_LABELS[subject],
            question=None,
            feedback=None,
            current_num=0,
            total=0,
            finished=True,
            session_score=0,
            last_correct=None,
        )

    if request.method == "POST":
        action = request.form.get("action", "answer")

        if action == "next":
            # User menekan tombol "Lanjut"
            session.pop(fb_key, None)
            session.pop(last_key, None)
            return redirect(url_for(subject))

        if action == "restart":
            session.pop(idx_key, None)
            session.pop(fb_key, None)
            session.pop(correct_key, None)
            session.pop(last_key, None)
            return redirect(url_for(subject))

        # action == "answer"
        current_index = session.get(idx_key, 0)
        if current_index >= total:
            return redirect(url_for(subject))

        jawaban = request.form.get("jawaban")
        if not jawaban:
            # belum pilih jawaban -> render ulang
            return render_template(
                "quiz.html",
                subject=subject,
                subject_label=SUBJECT_LABELS[subject],
                question=questions[current_index],
                feedback=None,
                error="Silakan pilih salah satu jawaban dulu.",
                current_num=current_index + 1,
                total=total,
                finished=False,
                session_score=session.get(correct_key, 0) * POINTS_PER_CORRECT,
                last_correct=None,
            )

        correct_answer = questions[current_index]["answer"]
        is_correct = jawaban == correct_answer

        if is_correct:
            session[fb_key] = "Mantap! Jawaban kamu benar."
            session[last_key] = True
            session[correct_key] = session.get(correct_key, 0) + 1
            update_user_score(username, subject, POINTS_PER_CORRECT)
        else:
            session[fb_key] = f"Yah, kurang tepat. Jawaban yang benar: {correct_answer}."
            session[last_key] = False

        session[idx_key] = current_index + 1
        return redirect(url_for(subject))

    # GET request
    current_index = session.get(idx_key, 0)
    feedback = session.get(fb_key)
    last_correct = session.get(last_key)
    session_correct = session.get(correct_key, 0)

    # Selesai semua soal
    if current_index >= total:
        final_score = session_correct * POINTS_PER_CORRECT
        # bersihkan session quiz
        session.pop(idx_key, None)
        session.pop(fb_key, None)
        session.pop(correct_key, None)
        session.pop(last_key, None)
        return render_template(
            "quiz.html",
            subject=subject,
            subject_label=SUBJECT_LABELS[subject],
            question=None,
            feedback=feedback,
            current_num=total,
            total=total,
            finished=True,
            session_score=final_score,
            session_correct=session_correct,
            last_correct=last_correct,
        )

    # Kalau ada feedback yang belum dikonsumsi, tampilkan layar feedback dulu
    if feedback is not None:
        return render_template(
            "quiz.html",
            subject=subject,
            subject_label=SUBJECT_LABELS[subject],
            question=None,  # mode feedback, tidak tampilkan soal baru
            feedback=feedback,
            current_num=current_index,  # soal yang baru saja dijawab
            total=total,
            finished=False,
            show_next=True,
            session_score=session_correct * POINTS_PER_CORRECT,
            last_correct=last_correct,
        )

    # Tampilkan soal saat ini
    return render_template(
        "quiz.html",
        subject=subject,
        subject_label=SUBJECT_LABELS[subject],
        question=questions[current_index],
        feedback=None,
        current_num=current_index + 1,
        total=total,
        finished=False,
        session_score=session_correct * POINTS_PER_CORRECT,
        last_correct=None,
    )


@app.route("/matematika", methods=["GET", "POST"])
@login_required
def matematika():
    return _quiz_handler("matematika")


@app.route("/kosakata", methods=["GET", "POST"])
@login_required
def kosakata():
    return _quiz_handler("kosakata")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)
