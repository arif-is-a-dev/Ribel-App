"""Aturan permainan kuis: timer, booster, dan combo.

Seluruh fungsi di berkas ini membaca dan menulis dict session milik Flask.
Session adalah cookie bertanda tangan dengan secret key server, sehingga nilai
di dalamnya tidak dapat diubah dari browser tanpa kunci tersebut. JavaScript
di halaman kuis hanya menampilkan hitung mundur dan animasi; keputusan akhir
tetap berada di server.
"""

import random
import time

from flask import session

# Nama booster yang dikenali aplikasi.
BOOSTERS = ("fifty", "freeze", "double", "chance")

# Teks yang ditampilkan di area booster.
BOOSTER_INFO = {
    "fifty": {
        "label": "50:50",
        "hint": "Sembunyikan dua pilihan jawaban yang salah.",
    },
    "freeze": {
        "label": "Time Freeze",
        "hint": "Tambahkan 5 detik untuk soal ini.",
    },
    "double": {
        "label": "Double Points",
        "hint": "Poin jawaban benar menjadi dua kali lipat.",
    },
    "chance": {
        "label": "Second Chance",
        "hint": "Ulangi satu jawaban yang belum tepat.",
    },
}

# Pesan singkat setelah booster diaktifkan.
BOOSTER_NOTICE = {
    "fifty": "50:50 aktif. Dua pilihan yang salah sudah disembunyikan.",
    "freeze": "Time Freeze aktif. Waktu untuk soal ini bertambah 5 detik.",
    "double": "Double Points aktif. Poin jawaban benar menjadi dua kali lipat.",
    "chance": "Second Chance aktif. Coba lagi soal yang sama.",
}

# Umpan balik saat waktu habis.
TIMEOUT_FEEDBACK = "Waktu habis. Soal ini lanjut ke berikutnya."

def session_keys(subject):
    """Kunci session per mata pelajaran supaya tidak saling tabrakan."""
    return {
        "index": f"{subject}_index",
        "plan": f"{subject}_plan",
        "feedback": f"{subject}_feedback",
        "last_correct": f"{subject}_last_correct",
        "timed_out": f"{subject}_timed_out",
        "attempt": f"{subject}_attempt",
        "deadline": f"{subject}_deadline",
        "boosters": f"{subject}_boosters",
        "fifty_hidden": f"{subject}_fifty_hidden",
        "double_for": f"{subject}_double_for",
        "streak": f"{subject}_streak",
        "best_streak": f"{subject}_best_streak",
        "notice": f"{subject}_notice",
        "last_points": f"{subject}_last_points",
    }

def clear(keys):
    """Hapus seluruh state permainan untuk satu mata pelajaran."""
    for key in keys.values():
        session.pop(key, None)

# ---------- Booster ----------

def booster_state(keys):
    """Status tiap booster pada sesi ini: ``available`` atau ``used``."""
    stored = session.get(keys["boosters"])
    if not isinstance(stored, dict):
        stored = {}
    return {
        name: "used" if stored.get(name) == "used" else "available"
        for name in BOOSTERS
    }

def use_booster(keys, name):
    """Tandai satu booster sudah dipakai pada sesi ini."""
    state = booster_state(keys)
    state[name] = "used"
    session[keys["boosters"]] = state

def used_boosters(keys):
    """Daftar nama booster yang sudah dipakai, urut sesuai BOOSTERS."""
    state = booster_state(keys)
    return [name for name in BOOSTERS if state[name] == "used"]

def fifty_hidden_options(keys, index):
    """Daftar opsi yang disembunyikan 50:50 untuk soal aktif."""
    data = session.get(keys["fifty_hidden"])
    if isinstance(data, dict) and data.get("index") == index:
        return list(data.get("options", []))
    return []

def apply_fifty(keys, index, question, min_options):
    """Sembunyikan dua opsi salah. Kembalikan True bila berhasil.

    Jawaban benar tidak pernah ikut disembunyikan, jadi booster ini tidak
    membocorkan kunci jawaban.
    """
    options = list(question["options"])
    if len(options) < min_options:
        return False
    wrong = [option for option in options if option != question["answer"]]
    if len(wrong) < 2:
        return False
    hidden = random.sample(wrong, 2)
    session[keys["fifty_hidden"]] = {"index": index, "options": hidden}
    return True

def is_double_armed(keys, index):
    """True bila Double Points aktif untuk soal pada indeks ini."""
    data = session.get(keys["double_for"])
    return isinstance(data, dict) and data.get("index") == index

def arm_double(keys, index):
    session[keys["double_for"]] = {"index": index}

# ---------- Timer ----------

def deadline_for(keys, index):
    """Tenggat yang tersimpan, hanya bila memang milik indeks ini."""
    data = session.get(keys["deadline"])
    if isinstance(data, dict) and data.get("index") == index:
        return data
    return None

def ensure_deadline(keys, index, seconds):
    """Pasang tenggat baru hanya bila belum ada untuk soal ini.

    Refresh halaman tidak mengatur ulang waktu karena tenggat disimpan per
    indeks soal di session, bukan dihitung ulang dari browser.
    """
    if deadline_for(keys, index) is None:
        session[keys["deadline"]] = {"index": index, "at": time.time() + seconds}

def extend_deadline(keys, index, seconds):
    """Tambahkan waktu pada tenggat soal aktif (Time Freeze)."""
    data = deadline_for(keys, index)
    if data is None:
        return False
    session[keys["deadline"]] = {"index": index, "at": float(data["at"]) + seconds}
    return True

def remaining_seconds(keys, index):
    data = deadline_for(keys, index)
    if data is None:
        return 0.0
    return max(0.0, float(data["at"]) - time.time())

def deadline_expired(keys, index, grace):
    """True bila soal sudah melewati tenggat.

    Tenggat yang tidak ada dianggap sudah lewat: setiap soal selalu dipasangi
    tenggat saat pertama kali ditampilkan, jadi permintaan yang datang tanpa
    tenggat tidak boleh dinilai.
    """
    data = deadline_for(keys, index)
    if data is None:
        return True
    return time.time() > float(data["at"]) + grace

# ---------- Combo ----------

def current_streak(keys):
    return int(session.get(keys["streak"], 0) or 0)

def best_streak(keys):
    return int(session.get(keys["best_streak"], 0) or 0)

def register_result(keys, is_correct, points):
    """Perbarui combo dan poin terakhir setelah jawaban dinilai server."""
    session[keys["last_points"]] = points
    if is_correct:
        streak = current_streak(keys) + 1
        session[keys["streak"]] = streak
        if streak > best_streak(keys):
            session[keys["best_streak"]] = streak
    else:
        session[keys["streak"]] = 0

# ---------- Tampilan ----------

def booster_view(keys, question, min_options, phase, can_second_chance):
    """Bangun daftar booster siap render untuk template.

    ``phase`` bernilai "question" saat soal sedang dikerjakan atau "feedback"
    saat umpan balik jawaban ditampilkan.
    """
    state = booster_state(keys)
    view = []
    for name in BOOSTERS:
        info = BOOSTER_INFO[name]
        enabled = False
        note = ""

        if state[name] == "used":
            note = "Sudah dipakai."
        elif name == "fifty":
            enough = question is not None and len(question["options"]) >= min_options
            if not enough:
                note = f"Butuh minimal {min_options} pilihan jawaban."
            elif phase == "question":
                enabled = True
            else:
                note = "Dipakai saat soal sedang berjalan."
        elif name in ("freeze", "double"):
            if phase == "question":
                enabled = True
            else:
                note = "Dipakai sebelum menjawab soal."
        elif name == "chance":
            if phase == "question":
                note = "Tersedia setelah jawaban belum tepat."
            elif can_second_chance:
                enabled = True
            else:
                note = "Tidak berlaku untuk soal ini."

        view.append(
            {
                "name": name,
                "label": info["label"],
                "hint": info["hint"],
                "state": state[name],
                "enabled": enabled,
                "note": note,
            }
        )
    return view

def question_context(keys, question, index, min_options):
    """Konteks tambahan untuk layar soal: timer, booster, combo, notifikasi."""
    return {
        "remaining": round(remaining_seconds(keys, index), 1),
        "hidden_options": fifty_hidden_options(keys, index),
        "double_armed": is_double_armed(keys, index),
        "boosters": booster_view(keys, question, min_options, "question", False),
        "combo": current_streak(keys),
        "best_streak": best_streak(keys),
        "notice": session.pop(keys["notice"], None),
    }
