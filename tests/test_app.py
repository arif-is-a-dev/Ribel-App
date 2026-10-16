"""Pengujian aplikasi Ribel memakai unittest (tanpa dependensi tambahan)."""

import io
import os
import pathlib
import re
import tempfile
import time
import unittest
import uuid
from contextlib import redirect_stdout
from unittest import mock

import config
from ribel import constants, create_app
from ribel.db import connect, get_db, init_db
from ribel.repositories import users as users_repo
from ribel.services import quiz, scoring

from scripts import import_legacy, seed_bank

CSRF_RE = re.compile(rb'name="csrf_token"[^>]*value="([^"]+)"')


def csrf_token(client, path):
    """Ambil token CSRF dari halaman yang dirender."""
    response = client.get(path)
    if response.status_code != 200:
        raise AssertionError(f"GET {path} mengembalikan {response.status_code}")
    match = CSRF_RE.search(response.data)
    if match is None:
        raise AssertionError(f"token CSRF tidak ditemukan pada {path}")
    return match.group(1).decode("utf-8")


class RibelTestCase(unittest.TestCase):
    """Dasar pengujian: aplikasi dengan database sementara."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "ribel-test.sqlite3")
        self.app = create_app("testing", overrides={"DATABASE": self.db_path})
        with self.app.app_context():
            init_db(get_db())
        self.client = self.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def signup(self, username, password, email=None):
        token = csrf_token(self.client, "/signup")
        return self.client.post(
            "/signup",
            data={
                "csrf_token": token,
                "username": username,
                "email": email if email is not None else f"{username}@example.com",
                "password": password,
            },
            follow_redirects=False,
        )

    def login(self, username, password):
        token = csrf_token(self.client, "/login")
        return self.client.post(
            "/login",
            data={"csrf_token": token, "username": username, "password": password},
            follow_redirects=False,
        )

    def logout(self):
        token = csrf_token(self.client, "/dashboard")
        return self.client.post(
            "/logout", data={"csrf_token": token}, follow_redirects=False
        )

    def register_and_login(self, username="budi", password="rahasia123"):
        self.signup(username, password)
        self.login(username, password)

    def seed_question(self, subject="matematika", prompt="Soal uji?", correct="benar"):
        conn = connect(self.db_path)
        try:
            cursor = conn.execute(
                "INSERT INTO questions "
                "(subject, prompt, correct_answer, source_ref, position) "
                "VALUES (?, ?, ?, ?, 0)",
                (subject, prompt, correct, f"uji:{uuid.uuid4().hex}"),
            )
            question_id = cursor.lastrowid
            for position, option in enumerate(["salah", "benar", "lainnya"]):
                conn.execute(
                    "INSERT INTO question_options (question_id, option_text, position) "
                    "VALUES (?, ?, ?)",
                    (question_id, option, position),
                )
            conn.commit()
            return question_id
        finally:
            conn.close()

    def score_of(self, username, subject):
        conn = connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT s.score AS score FROM user_scores AS s "
                "JOIN users AS u ON u.id = s.user_id "
                "WHERE u.username = ? AND s.subject = ?",
                (username, subject),
            ).fetchone()
            return row["score"] if row is not None else 0
        finally:
            conn.close()


class AuthTests(RibelTestCase):
    def test_signup_menyimpan_password_sebagai_hash(self):
        response = self.signup("budi", "rahasia123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/login")

        conn = connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username = ?", ("budi",)
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["password_hash"], "rahasia123")
        self.assertIn(
            row["password_hash"].split(":")[0], {"scrypt", "pbkdf2", "argon2"}
        )

    def test_login_berhasil_dan_gagal(self):
        self.signup("budi", "rahasia123")

        gagal = self.login("budi", "password-salah")
        self.assertEqual(gagal.status_code, 200)
        self.assertIn(b"Username atau password salah.", gagal.data)

        berhasil = self.login("budi", "rahasia123")
        self.assertEqual(berhasil.status_code, 302)
        self.assertEqual(berhasil.headers["Location"], "/dashboard")

    def test_username_duplikat_ditolak(self):
        self.signup("budi", "rahasia123")
        response = self.signup("budi", "rahasia456")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Username sudah dipakai.", response.data)

    def test_password_pendek_ditolak(self):
        response = self.signup("siti", "abc")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Password minimal 4 karakter.", response.data)

    def test_email_tidak_valid_ditolak(self):
        response = self.signup("siti", "rahasia123", email="bukan-email")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Format email tidak valid.", response.data)

    def test_koma_ditolak(self):
        response = self.signup("bu,di", "rahasia123")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"tidak boleh mengandung koma", response.data)


class RouteProtectionTests(RibelTestCase):
    def test_halaman_terlindungi_butuh_login(self):
        for path in ["/dashboard", "/matematika", "/kosakata"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertEqual(response.headers["Location"], "/login", path)

    def test_halaman_publik_tetap_terbuka(self):
        for path in ["/", "/login", "/signup"]:
            self.assertEqual(self.client.get(path).status_code, 200, path)


class CsrfTests(RibelTestCase):
    def test_post_tanpa_token_ditolak(self):
        response = self.client.post(
            "/login", data={"username": "budi", "password": "rahasia123"}
        )
        self.assertEqual(response.status_code, 400)

    def test_registrasi_tanpa_token_ditolak(self):
        response = self.client.post(
            "/signup",
            data={
                "username": "budi",
                "email": "b@example.com",
                "password": "rahasia123",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_jawaban_kuis_tanpa_token_ditolak(self):
        self.register_and_login()
        self.seed_question()
        response = self.client.post(
            "/matematika", data={"action": "answer", "jawaban": "benar"}
        )
        self.assertEqual(response.status_code, 400)

    def test_logout_tanpa_token_ditolak(self):
        self.register_and_login()
        self.assertEqual(self.client.post("/logout").status_code, 400)

    def test_logout_harus_post(self):
        self.register_and_login()
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_logout_post_dengan_token(self):
        self.register_and_login()
        response = self.logout()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")
        self.assertEqual(self.client.get("/dashboard").status_code, 302)


class QuizTests(RibelTestCase):
    def setUp(self):
        super().setUp()
        self.register_and_login()
        self.seed_question("matematika")
        self.seed_question("kosakata")

    def answer(self, subject, jawaban, token=None):
        if token is None:
            token = csrf_token(self.client, f"/{subject}")
        return self.client.post(
            f"/{subject}",
            data={"csrf_token": token, "action": "answer", "jawaban": jawaban},
            follow_redirects=False,
        )

    def test_jawaban_benar_menambah_skor(self):
        response = self.answer("matematika", "benar")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.score_of("budi", "matematika"), 10)

    def test_jawaban_salah_tidak_menambah_skor(self):
        self.answer("matematika", "salah")
        self.assertEqual(self.score_of("budi", "matematika"), 0)

    def test_pengiriman_ulang_tidak_menambah_skor_ganda(self):
        token = csrf_token(self.client, "/matematika")
        self.answer("matematika", "benar", token=token)
        self.assertEqual(self.score_of("budi", "matematika"), 10)

        for _ in range(2):
            self.answer("matematika", "benar", token=token)
            self.assertEqual(self.score_of("budi", "matematika"), 10)

        conn = connect(self.db_path)
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS total FROM quiz_answers"
            ).fetchone()["total"]
        finally:
            conn.close()
        self.assertEqual(total, 1)

    def test_tanpa_memilih_jawaban_tidak_menambah_skor(self):
        token = csrf_token(self.client, "/matematika")
        response = self.client.post(
            "/matematika",
            data={"csrf_token": token, "action": "answer", "jawaban": ""},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Silakan pilih salah satu jawaban dulu.", response.data)
        self.assertEqual(self.score_of("budi", "matematika"), 0)

    def test_skor_terpisah_per_mata_pelajaran(self):
        self.answer("matematika", "benar")
        self.answer("kosakata", "benar")
        self.assertEqual(self.score_of("budi", "matematika"), 10)
        self.assertEqual(self.score_of("budi", "kosakata"), 10)

    def test_alur_feedback_lalu_selesai(self):
        self.seed_question("matematika", prompt="Soal kedua?")

        self.answer("matematika", "benar")
        halaman_feedback = self.client.get("/matematika")
        self.assertIn(b"Mantap! Jawaban kamu benar.", halaman_feedback.data)
        self.assertIn(b"Soal Berikutnya", halaman_feedback.data)

        next_token = csrf_token(self.client, "/matematika")
        self.client.post(
            "/matematika", data={"csrf_token": next_token, "action": "next"}
        )
        soal_kedua = self.client.get("/matematika")
        self.assertIn(b"Soal 2 dari 2", soal_kedua.data)

        self.answer("matematika", "salah")
        selesai = self.client.get("/matematika")
        self.assertIn(b"Mantap! Kamu selesai.", selesai.data)
        self.assertEqual(self.score_of("budi", "matematika"), 10)

    def test_restart_membuat_percobaan_baru(self):
        self.answer("matematika", "benar")
        restart_token = csrf_token(self.client, "/matematika")
        self.client.post(
            "/matematika", data={"csrf_token": restart_token, "action": "restart"}
        )
        self.assertEqual(self.client.get("/matematika").status_code, 200)
        self.answer("matematika", "benar")
        self.assertEqual(self.score_of("budi", "matematika"), 20)


class GameplayTests(RibelTestCase):
    """Fase 5: timer server, booster, combo, dan integritas skor."""

    def setUp(self):
        super().setUp()
        self.register_and_login()
        self.seed_question("matematika")
        self.seed_question("matematika", prompt="Soal kedua?")
        self.seed_four_option_question()

    def seed_four_option_question(self, subject="kosakata", prompt="Soal empat pilihan?"):
        """Soal dengan empat pilihan, dipakai untuk menguji booster 50:50."""
        conn = connect(self.db_path)
        try:
            cursor = conn.execute(
                "INSERT INTO questions "
                "(subject, prompt, correct_answer, source_ref, position) "
                "VALUES (?, ?, ?, ?, 0)",
                (subject, prompt, "benar", f"uji:{uuid.uuid4().hex}"),
            )
            question_id = cursor.lastrowid
            for position, option in enumerate(["salah", "benar", "lainnya", "ngawur"]):
                conn.execute(
                    "INSERT INTO question_options (question_id, option_text, position) "
                    "VALUES (?, ?, ?)",
                    (question_id, option, position),
                )
            conn.commit()
            return question_id
        finally:
            conn.close()

    def post_quiz(self, subject, data, token=None):
        if token is None:
            token = csrf_token(self.client, f"/{subject}")
        payload = {"csrf_token": token}
        payload.update(data)
        return self.client.post(f"/{subject}", data=payload, follow_redirects=False)

    def answer(self, subject, jawaban, token=None):
        return self.post_quiz(
            subject, {"action": "answer", "jawaban": jawaban}, token=token
        )

    def booster(self, subject, name, token=None):
        return self.post_quiz(
            subject, {"action": "booster", "booster": name}, token=token
        )

    def session_data(self):
        with self.client.session_transaction() as sess:
            return dict(sess)

    def expire_deadline(self, subject, index=0, seconds_ago=5):
        """Paksa tenggat soal sudah lewat, meniru waktu yang benar-benar habis."""
        with self.client.session_transaction() as sess:
            sess[f"{subject}_deadline"] = {
                "index": index,
                "at": time.time() - seconds_ago,
            }

    def test_timer_dan_booster_tampil_di_halaman_soal(self):
        halaman = self.client.get("/matematika")
        self.assertIn(b"Sisa waktu", halaman.data)
        self.assertIn(b"data-quiz-timer", halaman.data)
        for label in [b"50:50", b"Time Freeze", b"Double Points", b"Second Chance"]:
            self.assertIn(label, halaman.data)

    def test_refresh_tidak_mengatur_ulang_timer(self):
        self.client.get("/matematika")
        pertama = self.session_data()["matematika_deadline"]["at"]
        self.client.get("/matematika")
        self.client.get("/matematika")
        self.assertEqual(self.session_data()["matematika_deadline"]["at"], pertama)

    def test_jawaban_kosong_tidak_mengatur_ulang_timer(self):
        self.client.get("/matematika")
        pertama = self.session_data()["matematika_deadline"]["at"]
        halaman = self.answer("matematika", "")
        self.assertEqual(halaman.status_code, 200)
        self.assertEqual(self.session_data()["matematika_deadline"]["at"], pertama)

    def test_jawaban_setelah_tenggat_dicatat_waktu_habis(self):
        self.expire_deadline("matematika")
        self.answer("matematika", "benar")
        self.assertEqual(self.score_of("budi", "matematika"), 0)

        halaman = self.client.get("/matematika")
        self.assertIn(b"Waktu habis", halaman.data)

        conn = connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT selected_answer, is_correct, points_awarded FROM quiz_answers"
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNone(row["selected_answer"])
        self.assertEqual(row["is_correct"], 0)
        self.assertEqual(row["points_awarded"], 0)

    def test_laporan_waktu_habis_dari_client_ditolak_bila_belum_lewat(self):
        self.client.get("/matematika")
        self.post_quiz("matematika", {"action": "timeout"})
        self.assertEqual(self.session_data()["matematika_index"], 0)
        self.assertEqual(self.score_of("budi", "matematika"), 0)

    def test_soal_yang_sudah_waktu_habis_tidak_dinilai_dua_kali(self):
        self.expire_deadline("matematika")
        token = csrf_token(self.client, "/matematika")
        self.post_quiz("matematika", {"action": "timeout"}, token=token)
        self.post_quiz("matematika", {"action": "timeout"}, token=token)
        self.answer("matematika", "benar", token=token)
        self.assertEqual(self.score_of("budi", "matematika"), 0)

        conn = connect(self.db_path)
        try:
            total = conn.execute(
                "SELECT COUNT(*) AS total FROM quiz_answers"
            ).fetchone()["total"]
        finally:
            conn.close()
        self.assertEqual(total, 1)

    def test_skor_normal_tanpa_booster(self):
        self.answer("matematika", "benar")
        self.assertEqual(self.score_of("budi", "matematika"), 10)

    def test_double_points_dihitung_server(self):
        self.client.get("/matematika")
        self.booster("matematika", "double")
        self.answer("matematika", "benar")
        self.assertEqual(self.score_of("budi", "matematika"), 20)

    def test_double_points_hanya_untuk_soal_aktif(self):
        self.client.get("/matematika")
        self.booster("matematika", "double")
        self.answer("matematika", "benar")
        self.assertEqual(self.score_of("budi", "matematika"), 20)

        token = csrf_token(self.client, "/matematika")
        self.post_quiz("matematika", {"action": "next"}, token=token)
        self.client.get("/matematika")
        self.answer("matematika", "benar", token=token)
        self.assertEqual(self.score_of("budi", "matematika"), 30)

    def test_booster_hanya_bisa_dipakai_sekali_per_sesi(self):
        token = csrf_token(self.client, "/matematika")
        self.booster("matematika", "double", token=token)
        self.booster("matematika", "double", token=token)
        self.assertEqual(self.session_data()["matematika_boosters"]["double"], "used")
        self.answer("matematika", "benar", token=token)
        self.assertEqual(self.score_of("budi", "matematika"), 20)

    def test_booster_tidak_dikenal_tidak_mengubah_status(self):
        token = csrf_token(self.client, "/matematika")
        response = self.post_quiz(
            "matematika", {"action": "booster", "booster": "curang"}, token=token
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("matematika_boosters", self.session_data())

    def test_aksi_booster_tanpa_token_ditolak(self):
        response = self.client.post(
            "/matematika", data={"action": "booster", "booster": "double"}
        )
        self.assertEqual(response.status_code, 400)

    def test_time_freeze_menambah_tenggat(self):
        self.client.get("/matematika")
        sebelum = self.session_data()["matematika_deadline"]["at"]
        self.booster("matematika", "freeze")
        sesudah = self.session_data()["matematika_deadline"]["at"]
        self.assertAlmostEqual(sesudah - sebelum, 5, delta=1)

    def test_time_freeze_ditolak_pada_layar_umpan_balik(self):
        self.client.get("/matematika")
        sebelum = self.session_data()["matematika_deadline"]["at"]
        self.answer("matematika", "benar")
        token = csrf_token(self.client, "/matematika")
        self.booster("matematika", "freeze", token=token)
        self.assertEqual(self.session_data()["matematika_deadline"]["at"], sebelum)

    def test_50_50_menyembunyikan_dua_opsi_salah(self):
        self.booster("kosakata", "fifty")
        data = self.session_data()
        hidden = data["kosakata_fifty_hidden"]["options"]
        self.assertEqual(len(hidden), 2)
        self.assertNotIn("benar", hidden)
        self.assertEqual(data["kosakata_boosters"]["fifty"], "used")

        halaman = self.client.get("/kosakata")
        self.assertIn(b'value="benar"', halaman.data)
        for option in hidden:
            self.assertNotIn(f'value="{option}"'.encode(), halaman.data)

    def test_50_50_nonaktif_bila_opsi_kurang_dari_empat(self):
        self.booster("matematika", "fifty")
        data = self.session_data()
        self.assertNotIn("matematika_fifty_hidden", data)
        self.assertNotEqual(data.get("matematika_boosters", {}).get("fifty"), "used")

    def test_second_chance_memberi_percobaan_kedua(self):
        self.client.get("/matematika")
        self.answer("matematika", "salah")
        self.assertEqual(self.score_of("budi", "matematika"), 0)

        umpan = self.client.get("/matematika")
        self.assertIn(b"Second Chance", umpan.data)

        self.booster("matematika", "chance")
        self.assertEqual(self.session_data()["matematika_index"], 0)
        self.assertIn(b"Soal 1 dari 2", self.client.get("/matematika").data)

        self.answer("matematika", "benar")
        self.assertEqual(self.score_of("budi", "matematika"), 10)

    def test_second_chance_hanya_sekali_per_sesi(self):
        self.client.get("/matematika")
        self.answer("matematika", "salah")
        self.booster("matematika", "chance")
        self.assertEqual(self.session_data()["matematika_index"], 0)

        self.answer("matematika", "salah")
        self.assertEqual(self.session_data()["matematika_index"], 1)
        self.booster("matematika", "chance")
        self.assertEqual(self.session_data()["matematika_index"], 1)

    def test_second_chance_tidak_berlaku_saat_waktu_habis(self):
        self.expire_deadline("matematika")
        self.answer("matematika", "benar")
        self.assertEqual(self.session_data()["matematika_index"], 1)
        self.booster("matematika", "chance")
        self.assertEqual(self.session_data()["matematika_index"], 1)

    def test_combo_terbaik_tercatat_di_layar_hasil(self):
        self.answer("matematika", "benar")
        token = csrf_token(self.client, "/matematika")
        self.post_quiz("matematika", {"action": "next"}, token=token)
        self.client.get("/matematika")
        self.answer("matematika", "benar", token=token)

        selesai = self.client.get("/matematika")
        self.assertIn(b"Mantap! Kamu selesai.", selesai.data)
        self.assertIn(b"Combo terbaik", selesai.data)

    def test_percobaan_selesai_ditandai_dan_tidak_dinilai_ulang(self):
        self.answer("matematika", "benar")
        token = csrf_token(self.client, "/matematika")
        self.post_quiz("matematika", {"action": "next"}, token=token)
        self.client.get("/matematika")
        self.answer("matematika", "benar", token=token)
        self.assertEqual(self.score_of("budi", "matematika"), 20)

        selesai = self.client.get("/matematika")
        self.assertIn(b"Mantap! Kamu selesai.", selesai.data)

        conn = connect(self.db_path)
        try:
            attempts = conn.execute(
                "SELECT id, status, score FROM quiz_attempts ORDER BY id"
            ).fetchall()
            jawaban = conn.execute(
                "SELECT COUNT(*) AS total FROM quiz_answers"
            ).fetchone()["total"]
        finally:
            conn.close()
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["status"], "finished")
        self.assertEqual(attempts[0]["score"], 20)
        self.assertEqual(jawaban, 2)


class ScoringServiceTests(RibelTestCase):
    def _attempt_with_question(self, db):
        user_id = users_repo.create(db, "uji", "uji@example.com", "hash")
        question_id = self.seed_question()
        question = {
            "id": question_id,
            "answer": "benar",
            "options": ["salah", "benar", "lainnya"],
        }
        attempt = quiz.get_attempt(db, quiz.start_attempt(db, user_id, "matematika"))
        return user_id, question, attempt

    def test_record_answer_idempoten(self):
        with self.app.app_context():
            db = get_db()
            user_id, question, attempt = self._attempt_with_question(db)

            pertama = quiz.record_answer(db, attempt, question, "benar", 10)
            kedua = quiz.record_answer(db, attempt, question, "benar", 10)

            self.assertTrue(pertama["awarded"])
            self.assertFalse(kedua["awarded"])
            self.assertEqual(scoring.get_scores(db, user_id)["matematika"], 10)
            self.assertEqual(scoring.total_score(db, user_id), 10)
            total = db.execute("SELECT COUNT(*) AS total FROM quiz_answers").fetchone()
            self.assertEqual(total["total"], 1)

    def test_jawaban_salah_tidak_memberi_poin(self):
        with self.app.app_context():
            db = get_db()
            user_id, question, attempt = self._attempt_with_question(db)
            hasil = quiz.record_answer(db, attempt, question, "salah", 10)
            self.assertFalse(hasil["is_correct"])
            self.assertEqual(hasil["points"], 0)
            self.assertEqual(scoring.total_score(db, user_id), 0)

    def test_leaderboard_tanpa_data_pribadi(self):
        with self.app.app_context():
            db = get_db()
            user_id = users_repo.create(db, "budi", "budi@example.com", "hash")
            scoring.add_points(db, user_id, "matematika", 25)
            db.commit()
            board = users_repo.leaderboard(db, 5)
        self.assertEqual(len(board), 1)
        self.assertEqual(set(board[0]), {"nama", "skor"})
        self.assertEqual(board[0]["skor"], 25)


class ConfigTests(unittest.TestCase):
    def test_secret_key_tidak_punya_nilai_bawaan(self):
        self.assertIsNone(config.BaseConfig.SECRET_KEY)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(config.read_secret_key())
        with mock.patch.dict(os.environ, {"RIBEL_SECRET_KEY": "nilai-dari-env"}):
            self.assertEqual(config.read_secret_key(), "nilai-dari-env")

    def test_produksi_menolak_tanpa_secret_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError):
                    create_app(
                        "production",
                        overrides={"DATABASE": os.path.join(tmpdir, "ribel.sqlite3")},
                    )

    def test_produksi_memakai_secret_key_dari_environment(self):
        with mock.patch.dict(os.environ, {"RIBEL_SECRET_KEY": "nilai-dari-env"}):
            app = create_app("production", overrides={"DATABASE": ":memory:"})
        self.assertEqual(app.config["SECRET_KEY"], "nilai-dari-env")
        self.assertFalse(app.config["DEBUG"])
        self.assertTrue(app.config["SESSION_COOKIE_SECURE"])


class LegacyImportTests(RibelTestCase):
    def write_legacy(self, source_dir, users_text, mtk_text, kosakata_text):
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "users.txt").write_text(users_text, encoding="utf-8")
        (source_dir / "soal_mtk.txt").write_text(mtk_text, encoding="utf-8")
        (source_dir / "soal_kosakata.txt").write_text(kosakata_text, encoding="utf-8")

    def test_impor_idempoten_dan_password_lama_masih_bisa_login(self):
        source_dir = pathlib.Path(self.tmpdir.name) / "legacy"
        self.write_legacy(
            source_dir,
            "budi,budi@example.com,rahasialama,30,40\n"
            "siti,siti@example.com,rahasia2,0,10\n",
            "2+2?;4;3;5;4\n",
            "Kata?;a;b;a\n",
        )

        users, questions, problems = import_legacy.load_legacy(source_dir)
        self.assertEqual(problems, [])
        self.assertEqual(len(users), 2)

        conn = connect(self.db_path)
        try:
            init_db(conn)
            pertama = import_legacy.import_all(conn, users, questions)
            self.assertEqual(pertama["users"]["inserted"], 2)
            self.assertEqual(pertama["questions"]["inserted"], 2)

            kedua = import_legacy.import_all(conn, users, questions)
            self.assertEqual(kedua["users"]["inserted"], 0)
            self.assertEqual(kedua["users"]["skipped"], 2)
            self.assertEqual(kedua["questions"]["inserted"], 0)
            self.assertEqual(kedua["questions"]["skipped"], 2)

            laporan = import_legacy.verify(conn, users, questions)
            self.assertTrue(
                any("password belum ter-hash: 0" in baris for baris in laporan)
            )
            jumlah = conn.execute("SELECT COUNT(*) AS t FROM users").fetchone()["t"]
            self.assertEqual(jumlah, 2)
        finally:
            conn.close()

        response = self.login("budi", "rahasialama")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/dashboard")

        self.assertEqual(self.score_of("budi", "matematika"), 30)
        self.assertEqual(self.score_of("budi", "kosakata"), 40)

        token = csrf_token(self.client, "/matematika")
        self.client.post(
            "/matematika",
            data={"csrf_token": token, "action": "answer", "jawaban": "4"},
        )
        self.assertEqual(self.score_of("budi", "matematika"), 40)

    def test_data_rusak_menghentikan_impor(self):
        source_dir = pathlib.Path(self.tmpdir.name) / "legacy-rusak"
        self.write_legacy(
            source_dir,
            "budi,budi@example.com,rahasialama,30\n",
            "2+2?;4;3;5;4\n",
            "Kata?;a;b;a\n",
        )

        users, questions, problems = import_legacy.load_legacy(source_dir)
        self.assertEqual(users, [])
        self.assertTrue(problems)

        keluaran = io.StringIO()
        with redirect_stdout(keluaran):
            kode = import_legacy.main(
                ["--source-dir", str(source_dir), "--database", self.db_path]
            )
        self.assertEqual(kode, 1)
        self.assertIn("BERHENTI", keluaran.getvalue())

        conn = connect(self.db_path)
        try:
            jumlah = conn.execute("SELECT COUNT(*) AS t FROM users").fetchone()["t"]
        finally:
            conn.close()
        self.assertEqual(jumlah, 0)


class BankSoalTests(RibelTestCase):
    """Bank soal tambahan: empat opsi unik, satu jawaban benar, idempoten."""

    MIN_SOAL = 50

    def setUp(self):
        super().setUp()
        self.bank, self.patch, self.problems = seed_bank.load_bank()

    def test_bank_soal_lolos_validasi(self):
        self.assertEqual(self.problems, [])

    def test_minimal_lima_puluh_soal_per_mata_pelajaran(self):
        for subject, questions in self.bank.items():
            self.assertGreaterEqual(len(questions), self.MIN_SOAL, subject)

    def test_setiap_soal_punya_empat_opsi_unik_dan_satu_jawaban_benar(self):
        for _subject, questions in self.bank.items():
            for question in questions:
                with self.subTest(ref=question["source_ref"]):
                    options = question["options"]
                    self.assertEqual(len(options), 4)
                    self.assertEqual(len(set(options)), 4)
                    self.assertIn(question["answer"], options)

    def test_posisi_jawaban_benar_bervariasi(self):
        for subject, questions in self.bank.items():
            positions = {
                question["options"].index(question["answer"])
                for question in questions
            }
            self.assertGreaterEqual(len(positions), 2, subject)

    def test_pertanyaan_tidak_duplikat_dalam_satu_mapel(self):
        for subject, questions in self.bank.items():
            prompts = [question["prompt"].casefold() for question in questions]
            self.assertEqual(len(prompts), len(set(prompts)), subject)

    def test_seed_idempoten_dan_soal_lama_jadi_empat_opsi(self):
        conn = connect(self.db_path)
        try:
            init_db(conn)
            # Impor soal lama seperti Fase 1, lalu lengkapi opsi keempatnya.
            legacy = {}
            for subject, file_name in constants.LEGACY_QUESTION_FILES.items():
                parsed, problems = import_legacy.parse_questions(
                    seed_bank.BASE_DIR / file_name, subject
                )
                self.assertEqual(problems, [])
                legacy[subject] = parsed
            import_legacy.import_questions(conn, legacy)

            pertama = seed_bank.import_bank(conn, self.bank)
            self.assertEqual(pertama["inserted"], 2 * self.MIN_SOAL)
            self.assertEqual(pertama["skipped"], 0)

            patch_pertama = seed_bank.apply_option_patch(conn, self.patch)
            self.assertEqual(patch_pertama["added"], len(self.patch))
            self.assertEqual(patch_pertama["missing"], [])

            # Dijalankan ulang: tidak boleh menambah soal atau opsi lagi.
            kedua = seed_bank.import_bank(conn, self.bank)
            self.assertEqual(kedua["inserted"], 0)
            self.assertEqual(kedua["skipped"], 2 * self.MIN_SOAL)
            patch_kedua = seed_bank.apply_option_patch(conn, self.patch)
            self.assertEqual(patch_kedua["added"], 0)
            self.assertEqual(patch_kedua["skipped"], len(self.patch))

            for subject in constants.SUBJECTS:
                total = conn.execute(
                    "SELECT COUNT(*) AS total FROM questions WHERE subject = ?",
                    (subject,),
                ).fetchone()["total"]
                self.assertEqual(total, len(legacy[subject]) + self.MIN_SOAL)
                bukan_empat = conn.execute(
                    "SELECT COUNT(*) AS total FROM ("
                    "SELECT q.id FROM questions AS q "
                    "JOIN question_options AS o ON o.question_id = q.id "
                    "WHERE q.subject = ? GROUP BY q.id HAVING COUNT(*) != 4)",
                    (subject,),
                ).fetchone()["total"]
                self.assertEqual(bukan_empat, 0, subject)
        finally:
            conn.close()


class SessionVariationTests(RibelTestCase):
    """Variasi soal per sesi: batas jumlah soal dan pilihan yang stabil."""

    def setUp(self):
        super().setUp()
        self.register_and_login()
        self.limit = self.app.config["QUIZ_QUESTIONS_PER_SESSION"]
        for index in range(self.limit * 3):
            self.seed_question("matematika", prompt=f"Soal variasi {index}?")

    def session_data(self):
        with self.client.session_transaction() as sess:
            return dict(sess)

    def question_ids(self, subject):
        conn = connect(self.db_path)
        try:
            return {
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM questions WHERE subject = ?", (subject,)
                ).fetchall()
            }
        finally:
            conn.close()

    def test_sesi_memakai_jumlah_soal_yang_masuk_akal(self):
        self.client.get("/matematika")
        plan = self.session_data().get("matematika_plan")
        self.assertIsNotNone(plan)
        self.assertEqual(len(plan), self.limit)
        self.assertEqual(len(set(plan)), self.limit)
        self.assertTrue(set(plan).issubset(self.question_ids("matematika")))

    def test_pilihan_soal_tetap_sama_selama_sesi_berjalan(self):
        self.client.get("/matematika")
        pertama = list(self.session_data()["matematika_plan"])
        self.client.get("/matematika")
        self.client.get("/matematika")
        self.assertEqual(self.session_data()["matematika_plan"], pertama)

    def test_soal_tidak_terulang_dalam_satu_sesi(self):
        self.client.get("/matematika")
        plan = self.session_data()["matematika_plan"]
        self.assertEqual(len(plan), len(set(plan)))

    def test_restart_membuat_pilihan_soal_baru(self):
        self.client.get("/matematika")
        token = csrf_token(self.client, "/matematika")
        self.client.post(
            "/matematika", data={"csrf_token": token, "action": "restart"}
        )
        self.assertNotIn("matematika_plan", self.session_data())
        self.client.get("/matematika")
        plan = self.session_data()["matematika_plan"]
        self.assertEqual(len(plan), self.limit)

    def test_bank_kecil_tetap_memakai_semua_soal(self):
        self.seed_question("kosakata", prompt="Satu-satunya soal kosakata?")
        self.client.get("/kosakata")
        plan = self.session_data()["kosakata_plan"]
        self.assertEqual(len(plan), 1)
        halaman = self.client.get("/kosakata")
        self.assertIn(b"Soal 1 dari 1", halaman.data)


class SkillToolbarTests(RibelTestCase):
    """Toolbar skill ringkas dan booster 50:50 di soal empat opsi."""

    def setUp(self):
        super().setUp()
        self.register_and_login()
        conn = connect(self.db_path)
        try:
            cursor = conn.execute(
                "INSERT INTO questions "
                "(subject, prompt, correct_answer, source_ref, position) "
                "VALUES ('kosakata', 'Soal empat opsi?', 'benar', 'uji:fifty', 0)"
            )
            self.question_id = cursor.lastrowid
            for position, option in enumerate(["salah", "benar", "lainnya", "ngawur"]):
                conn.execute(
                    "INSERT INTO question_options (question_id, option_text, position) "
                    "VALUES (?, ?, ?)",
                    (self.question_id, option, position),
                )
            conn.commit()
        finally:
            conn.close()

    def booster(self, name):
        token = csrf_token(self.client, "/kosakata")
        return self.client.post(
            "/kosakata",
            data={"csrf_token": token, "action": "booster", "booster": name},
            follow_redirects=False,
        )

    def test_tanpa_booster_empat_opsi_tampil(self):
        halaman = self.client.get("/kosakata")
        self.assertEqual(halaman.data.count(b'name="jawaban"'), 4)

    def test_50_50_menyisakan_dua_opsi_termasuk_jawaban_benar(self):
        self.booster("fifty")
        halaman = self.client.get("/kosakata")
        self.assertEqual(halaman.data.count(b'name="jawaban"'), 2)
        self.assertIn(b'value="benar"', halaman.data)

    def test_50_50_tidak_dinilai_sebagai_kartu_besar(self):
        halaman = self.client.get("/kosakata")
        self.assertIn(b"quiz-skillbar", halaman.data)
        self.assertNotIn(b"quiz-boosters", halaman.data)
        for label in [b"50:50", b"Time Freeze", b"Double Points", b"Second Chance"]:
            self.assertIn(label, halaman.data)
        # Toolbar skill berada setelah area jawaban, bukan di antara timer dan soal.
        self.assertGreater(
            halaman.data.index(b"quiz-skillbar"),
            halaman.data.index(b"Kirim jawaban"),
        )


if __name__ == "__main__":
    unittest.main()
