from flask import Flask, render_template, request, redirect, url_for, session
import random

app = Flask(__name__)
app.secret_key = "some_secret_key"

def read_users():
    users = {}
    try:
        with open("users.txt", "r") as file:
            for line in file:
                username, email, password, matematika_score, kosakata_score = line.strip().split(",")
                users[username] = {
                    "email": email,
                    "password": password,
                    "scores": {
                        "matematika": int(matematika_score),
                        "kosakata": int(kosakata_score)
                    }
                }
    except FileNotFoundError:
        pass
    return users

def update_user_score(username, subject, score_increment):
    users = read_users()
    if username in users:
        # Perbarui skor untuk mata pelajaran tertentu
        users[username]["scores"][subject] += score_increment

        # Debugging: Cetak skor pengguna
        print(f"Skor baru {username} untuk {subject}: {users[username]['scores'][subject]}")

        # Tulis kembali file users.txt
        with open("users.txt", "w") as file:
            for user, data in users.items():
                file.write(f"{user},{data['email']},{data['password']},{data['scores']['matematika']},{data['scores']['kosakata']}\n")


def read_questions(file_name):
    questions = []
    try:
        with open(file_name, "r") as file:
            for line in file:
                question, *options, answer = line.strip().split(";")
                questions.append({
                    "question": question,
                    "options": options,
                    "answer": answer
                })
    except FileNotFoundError:
        print("File soal_mtk.txt tidak ditemukan!")
    return questions

@app.route("/")
def home():
    return render_template("index.html")
    
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        users = read_users()
        if username in users and users[username]["password"] == password:
            session["username"] = username  # Simpan username ke session
            return redirect(url_for("dashboard", username=username))
        else:
            return render_template("login.html", error="Username atau password salah.")
    return render_template("login.html")

def save_user(username, email, password):
    # Skor default untuk pengguna baru
    matematika_score = 0
    kosakata_score = 0
    with open("users.txt", "a") as file:
        file.write(f"{username},{email},{password},{matematika_score},{kosakata_score}\n")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        # Simpan data pengguna baru
        save_user(username, email, password)
        return redirect(url_for("login"))
    return render_template("signup.html")

@app.route("/dashboard")
def dashboard():
    username = request.args.get("username", "Guest")
    users = read_users()  # Fungsi untuk membaca data pengguna
    
    # Ambil skor pengguna yang sedang login
    scores = users.get(username, {}).get("scores", {"matematika": 0, "kosakata": 0})
    
    # Buat daftar top scores berdasarkan skor dari semua pengguna
    all_scores = []
    for user, data in users.items():
        total_score = sum(data.get("scores", {}).values())  #total skor
        all_scores.append({"nama": user, "skor": total_score})
    
    top_scores = sorted(all_scores, key=lambda x: x["skor"], reverse=True)[:3]
    
    return render_template(
        "dashboard.html",
        username=username,
        scores=scores,
        top_scores=top_scores,
    )

@app.route("/matematika", methods=["GET", "POST"])
def matematika():
    questions = read_questions("soal_mtk.txt")  # Baca daftar soal dari file
    current_index = session.get("current_index", 0)  # Ambil index soal dari session
    show_feedback = session.get("show_feedback", False)  # Flag untuk feedback
    feedback = session.get("feedback", None)  # Simpan feedback sementara
    username = session.get("username")  # Ambil username dari session

    # Pastikan current_index tidak melebihi jumlah soal
    if current_index >= len(questions):
        session.pop("current_index", None)
        session.pop("show_feedback", None)
        session.pop("feedback", None)
        return redirect(url_for("dashboard", username=username))  # Kembali ke dashboard

    if request.method == "POST":
        # Ambil jawaban pengguna dan validasi
        jawaban = request.form.get("jawaban")
        correct_answer = questions[current_index]["answer"]

        if jawaban:
            if jawaban == correct_answer:
                feedback = "Jawaban Anda benar!"
                update_user_score(username, "matematika", 10)  # Tambahkan skor
            else:
                feedback = f"Jawaban Anda salah! Jawaban yang benar adalah {correct_answer}."

            # Set flag untuk menampilkan feedback
            session["show_feedback"] = True
            session["feedback"] = feedback

            # Pindah ke soal berikutnya setelah feedback ditampilkan
            current_index += 1
            session["current_index"] = current_index

            # Cek jika soal sudah selesai
            if current_index >= len(questions):
                session.pop("current_index", None)
                return redirect(url_for("dashboard", username=username))  # Kembali ke dashboard

        return redirect(url_for("matematika"))  # Refresh halaman untuk menampilkan feedback dan soal berikutnya

    # Ambil soal saat ini
    if current_index < len(questions):
        current_question = questions[current_index]
        print("Current Question:", current_question)  # Debug
    else:
        current_question = None
        print("No more questions!")

    return render_template("matematika.html", question=current_question, feedback=feedback)

@app.route("/kosakata", methods=["GET", "POST"])
def kosakata():
    questions = read_questions("soal_kosakata.txt")  # Baca daftar soal dari file
    current_index = session.get("current_index", 0)  # Ambil index soal dari session
    show_feedback = session.get("show_feedback", False)  # Flag untuk feedback
    feedback = session.get("feedback", None)  # Simpan feedback sementara
    username = session.get("username")  # Ambil username dari session

    # Pastikan current_index tidak melebihi jumlah soal
    if current_index >= len(questions):
        session.pop("current_index", None)
        session.pop("show_feedback", None)
        session.pop("feedback", None)
        return redirect(url_for("dashboard", username=username))  # Kembali ke dashboard

    if request.method == "POST":
        # Ambil jawaban pengguna dan validasi
        jawaban = request.form.get("jawaban")
        correct_answer = questions[current_index]["answer"]

        if jawaban:
            if jawaban == correct_answer:
                feedback = "Jawaban Anda benar!"
                update_user_score(username, "kosakata", 10)  # Tambahkan skor
            else:
                feedback = f"Jawaban Anda salah! Jawaban yang benar adalah {correct_answer}."

            # Set flag untuk menampilkan feedback
            session["show_feedback"] = True
            session["feedback"] = feedback

            # Pindah ke soal berikutnya setelah feedback ditampilkan
            current_index += 1
            session["current_index"] = current_index

            # Cek jika soal sudah selesai
            if current_index >= len(questions):
                session.pop("current_index", None)
                return redirect(url_for("dashboard", username=username))  # Kembali ke dashboard

        return redirect(url_for("kosakata"))  # Refresh halaman untuk menampilkan feedback dan soal berikutnya

    # Ambil soal saat ini
    if current_index < len(questions):
        current_question = questions[current_index]
        print("Current Question:", current_question)  # Debug
    else:
        current_question = None
        print("No more questions!")

    return render_template("kosakata.html", question=current_question, feedback=feedback)

def read_questions(file_name):
    questions = []
    try:
        with open(file_name, "r") as file:
            for line in file:
                question, *options, answer = line.strip().split(";")
                questions.append({
                    "question": question,
                    "options": options,
                    "answer": answer
                })
    except FileNotFoundError:
        print(f"File {file_name} tidak ditemukan!")
    except Exception as e:
        print(f"Kesalahan saat membaca file {file_name}: {e}")
    return questions

@app.route("/logout")
def logout():
    # Hapus semua data di session
    session.clear()
    # Arahkan pengguna kembali ke halaman login atau beranda
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(debug=True)