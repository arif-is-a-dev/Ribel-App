"""Seed bank soal tambahan (Matematika dan Kosakata) ke database SQLite.

Sifat skrip ini:

* Idempoten: aman dijalankan berulang. Soal yang sudah ada (dicek lewat
  ``UNIQUE (subject, source_ref)``) dilewati, dan opsi keempat untuk soal lama
  hanya ditambahkan bila belum ada.
* Tidak menambah, mengubah, atau menghapus akun, skor, dan riwayat kuis.
* Hanya membaca berkas data di ``data/``. Berkas sumber lama
  (``soal_mtk.txt`` dan ``soal_kosakata.txt``) tidak pernah diubah.
* Keluarannya hanya agregat (jumlah soal/opsi), bukan isi data pribadi.

Contoh pemakaian dari direktori proyek:

    py -3.13 scripts/seed_bank.py --check
    py -3.13 scripts/seed_bank.py
"""

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from config import DATABASE_ENV, DEFAULT_DATABASE
from ribel import constants
from ribel.db import connect, init_db

from scripts import import_legacy

DATA_DIR = BASE_DIR / "data"

# Berkas bank soal per mata pelajaran.
BANK_FILES = {
    "matematika": "bank_matematika.txt",
    "kosakata": "bank_kosakata.txt",
}

# Berkas penambahan opsi keempat untuk soal lama. Dipakai supaya seluruh soal
# punya empat pilihan tanpa mengubah berkas sumber aslinya.
OPTION_PATCH_FILE = "patch_opsi_keempat.txt"

# Jumlah pilihan jawaban yang diwajibkan untuk setiap soal.
OPTIONS_PER_QUESTION = 4


def resolve_database(explicit=None):
    """Tentukan lokasi berkas SQLite: argumen, lalu env, lalu default."""
    return explicit or os.environ.get(DATABASE_ENV) or DEFAULT_DATABASE


def parse_bank(path, subject):
    """Baca bank soal. Format: pertanyaan;opsi1;opsi2;opsi3;opsi4;jawaban."""
    questions = []
    problems = []
    seen_prompts = {}
    if not path.exists():
        problems.append(f"{path.name}: berkas tidak ditemukan")
        return questions, problems

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) != OPTIONS_PER_QUESTION + 2:
            problems.append(
                f"{path.name} baris {lineno}: butuh pertanyaan, "
                f"{OPTIONS_PER_QUESTION} opsi, dan jawaban"
            )
            continue
        prompt, *options, answer = parts
        if not prompt:
            problems.append(f"{path.name} baris {lineno}: pertanyaan kosong")
            continue
        if any(not option for option in options):
            problems.append(f"{path.name} baris {lineno}: ada opsi yang kosong")
            continue
        if len(set(options)) != OPTIONS_PER_QUESTION:
            problems.append(
                f"{path.name} baris {lineno}: opsi harus {OPTIONS_PER_QUESTION} "
                "dan tidak boleh duplikat"
            )
            continue
        if answer not in options:
            problems.append(
                f"{path.name} baris {lineno}: jawaban tidak ada di daftar opsi"
            )
            continue
        key = prompt.casefold()
        if key in seen_prompts:
            problems.append(
                f"{path.name} baris {lineno}: pertanyaan duplikat dengan baris "
                f"{seen_prompts[key]}"
            )
            continue
        seen_prompts[key] = lineno
        questions.append(
            {
                "subject": subject,
                "prompt": prompt,
                "options": options,
                "answer": answer,
                "source_ref": f"{path.name}:{lineno}",
            }
        )
    return questions, problems


def parse_option_patch(path):
    """Baca penambahan opsi keempat. Format: source_ref;opsi_tambahan."""
    patch = []
    problems = []
    if not path.exists():
        problems.append(f"{path.name}: berkas tidak ditemukan")
        return patch, problems

    seen = set()
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(";")]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            problems.append(
                f"{path.name} baris {lineno}: format harus source_ref;opsi_tambahan"
            )
            continue
        source_ref, option = parts
        if source_ref in seen:
            problems.append(
                f"{path.name} baris {lineno}: {source_ref} tercantum lebih dari sekali"
            )
            continue
        seen.add(source_ref)
        patch.append({"source_ref": source_ref, "option": option})
    return patch, problems


def legacy_prompts(source_dir):
    """Kumpulkan pertanyaan dari berkas sumber lama (hanya dibaca)."""
    prompts = {}
    for subject, file_name in constants.LEGACY_QUESTION_FILES.items():
        parsed, _problems = import_legacy.parse_questions(
            Path(source_dir) / file_name, subject
        )
        for item in parsed:
            prompts.setdefault(item["prompt"].casefold(), item["source_ref"])
    return prompts


def load_bank(data_dir=None, source_dir=None):
    """Baca bank soal dan penambahan opsi. Kembalikan (bank, patch, problems)."""
    data_dir = Path(data_dir or DATA_DIR)
    source_dir = Path(source_dir or BASE_DIR)
    problems = []

    bank = {}
    for subject, file_name in BANK_FILES.items():
        parsed, found = parse_bank(data_dir / file_name, subject)
        problems.extend(found)
        bank[subject] = parsed

    patch, found = parse_option_patch(data_dir / OPTION_PATCH_FILE)
    problems.extend(found)

    # Bank soal tidak boleh mengulang pertanyaan dari berkas sumber lama.
    existing = legacy_prompts(source_dir)
    for subject, questions in bank.items():
        for question in questions:
            duplicate = existing.get(question["prompt"].casefold())
            if duplicate is not None:
                problems.append(
                    f"{question['source_ref']}: pertanyaan sama dengan soal lama "
                    f"{duplicate}"
                )

    return bank, patch, problems


def import_bank(conn, bank):
    """Tambahkan soal bank baru beserta opsinya. Soal yang sudah ada dilewati."""
    inserted = 0
    skipped = 0
    for subject, questions in bank.items():
        base = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM questions "
            "WHERE subject = ?",
            (subject,),
        ).fetchone()["next"]
        for offset, question in enumerate(questions):
            cursor = conn.execute(
                "INSERT INTO questions "
                "(subject, prompt, correct_answer, source_ref, position) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT (subject, source_ref) DO NOTHING",
                (
                    subject,
                    question["prompt"],
                    question["answer"],
                    question["source_ref"],
                    base + offset,
                ),
            )
            if cursor.rowcount != 1:
                skipped += 1
                continue
            inserted += 1
            question_id = cursor.lastrowid
            for option_position, option in enumerate(question["options"]):
                conn.execute(
                    "INSERT INTO question_options (question_id, option_text, position) "
                    "VALUES (?, ?, ?)",
                    (question_id, option, option_position),
                )
    conn.commit()
    return {"inserted": inserted, "skipped": skipped}


def apply_option_patch(conn, patch):
    """Lengkapi soal lama menjadi empat opsi tanpa mengubah berkas sumbernya."""
    added = 0
    skipped = 0
    missing = []
    file_map = {
        file_name: subject
        for subject, file_name in constants.LEGACY_QUESTION_FILES.items()
    }
    for entry in patch:
        file_name = entry["source_ref"].split(":", 1)[0]
        subject = file_map.get(file_name)
        row = None
        if subject is not None:
            row = conn.execute(
                "SELECT id FROM questions WHERE subject = ? AND source_ref = ?",
                (subject, entry["source_ref"]),
            ).fetchone()
        if row is None:
            missing.append(entry["source_ref"])
            continue
        exists = conn.execute(
            "SELECT 1 FROM question_options WHERE question_id = ? AND option_text = ?",
            (row["id"], entry["option"]),
        ).fetchone()
        if exists is not None:
            skipped += 1
            continue
        next_position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS next FROM question_options "
            "WHERE question_id = ?",
            (row["id"],),
        ).fetchone()["next"]
        conn.execute(
            "INSERT INTO question_options (question_id, option_text, position) "
            "VALUES (?, ?, ?)",
            (row["id"], entry["option"], next_position),
        )
        added += 1
    conn.commit()
    return {"added": added, "skipped": skipped, "missing": missing}


def verify(conn):
    """Ringkasan agregat. Tidak menampilkan isi soal maupun data pengguna."""
    lines = []
    for subject in constants.SUBJECTS:
        total = conn.execute(
            "SELECT COUNT(*) AS total FROM questions WHERE subject = ?", (subject,)
        ).fetchone()["total"]
        exact = conn.execute(
            "SELECT COUNT(*) AS total FROM ("
            "SELECT q.id FROM questions AS q "
            "JOIN question_options AS o ON o.question_id = q.id "
            "WHERE q.subject = ? GROUP BY q.id HAVING COUNT(*) = ?)",
            (subject, OPTIONS_PER_QUESTION),
        ).fetchone()["total"]
        valid = conn.execute(
            "SELECT COUNT(*) AS total FROM questions AS q "
            "WHERE q.subject = ? AND EXISTS ("
            "SELECT 1 FROM question_options AS o WHERE o.question_id = q.id "
            "AND o.option_text = q.correct_answer)",
            (subject,),
        ).fetchone()["total"]
        lines.append(
            f"soal {subject}: {total} soal, {exact} dengan tepat "
            f"{OPTIONS_PER_QUESTION} opsi, {valid} dengan kunci jawaban valid"
        )
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Seed bank soal Ribel ke database SQLite (idempoten)."
    )
    parser.add_argument("--database", default=None, help="lokasi berkas SQLite tujuan")
    parser.add_argument(
        "--data-dir", default=str(DATA_DIR), help="direktori berkas bank soal"
    )
    parser.add_argument(
        "--source-dir", default=str(BASE_DIR), help="direktori berkas soal lama"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="hanya validasi berkas bank soal, tanpa menulis ke database",
    )
    args = parser.parse_args(argv)

    bank, patch, problems = load_bank(args.data_dir, args.source_dir)

    print("== Pembacaan bank soal ==")
    for subject, questions in bank.items():
        options = sum(len(question["options"]) for question in questions)
        print(f"soal {subject}: {len(questions)} soal/{options} opsi")
    print(f"penambahan opsi keempat: {len(patch)} entri")

    if problems:
        print("")
        print("== BERHENTI: bank soal tidak lolos validasi ==")
        for problem in problems:
            print(f"- {problem}")
        print("Tidak ada perubahan yang ditulis ke database.")
        return 1

    if args.check:
        print("")
        print("Validasi lolos. Tidak ada perubahan yang ditulis (mode --check).")
        return 0

    conn = connect(resolve_database(args.database))
    try:
        init_db(conn)

        summary = import_bank(conn, bank)
        print("")
        print("== Hasil seed ==")
        print(
            f"soal baru: {summary['inserted']}, soal dilewati: {summary['skipped']}"
        )

        patch_summary = apply_option_patch(conn, patch)
        print(
            f"opsi keempat ditambahkan: {patch_summary['added']}, "
            f"sudah ada: {patch_summary['skipped']}"
        )
        if patch_summary["missing"]:
            print("soal lama yang tidak ditemukan:")
            for source_ref in patch_summary["missing"]:
                print(f"- {source_ref}")

        print("")
        print("== Verifikasi ==")
        for line in verify(conn):
            print(f"- {line}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())