/* ==========================================================================
   Interaksi halaman kuis Ribel.

   Berkas ini hanya mengatur tampilan dan interaksi: hitung mundur, animasi
   pilihan, pencegahan pengiriman ganda, dan confetti di layar hasil.
   Penilaian jawaban, batas waktu, dan penggunaan booster tetap diputuskan
   server (Flask). Tidak ada kunci jawaban yang disimpan di sini.
   ========================================================================== */

(function () {
  "use strict";

  var reduceMotion =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function ready(callback) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback);
    } else {
      callback();
    }
  }

  /* ---------- Hitung mundur ---------- */
  function setupTimer() {
    var timer = document.querySelector("[data-quiz-timer]");
    if (!timer) return;

    var valueNode = timer.querySelector("[data-timer-value]");
    var barNode = timer.querySelector("[data-timer-bar]");
    var announceNode = timer.querySelector("[data-timer-announce]");
    var timeoutForm = document.querySelector("[data-timeout-form]");

    var total = parseFloat(timer.getAttribute("data-total"));
    if (isNaN(total) || total <= 0) total = 30;

    var start = parseFloat(timer.getAttribute("data-remaining"));
    if (isNaN(start) || start < 0) start = total;

    var deadline = Date.now() + start * 1000;
    var handle = null;
    var finished = false;
    var announced = false;

    function announce(text) {
      if (announceNode && !announced) {
        announced = true;
        announceNode.textContent = text;
      }
    }

    function paint() {
      var left = Math.max(0, (deadline - Date.now()) / 1000);
      if (valueNode) valueNode.textContent = Math.ceil(left) + " detik";
      if (barNode) {
        barNode.style.width = Math.max(0, Math.min(100, (left / total) * 100)) + "%";
      }
      timer.classList.toggle("is-warning", left <= 5.5);
      if (left <= 10) announce("Sisa waktu sepuluh detik atau kurang.");
      return left;
    }

    function submitTimeout() {
      if (finished || !timeoutForm) return;
      finished = true;
      window.clearInterval(handle);
      timeoutForm.submit();
    }

    paint();
    handle = window.setInterval(function () {
      if (paint() <= 0) {
        window.clearInterval(handle);
        /* Jeda kecil supaya tenggat di server benar-benar sudah lewat. */
        window.setTimeout(submitTimeout, 900);
      }
    }, 200);
  }

  /* ---------- Pilihan jawaban dan pengiriman form ---------- */
  function setupAnswerForm() {
    var form = document.querySelector("[data-quiz-form]");
    if (!form) return;

    var options = Array.prototype.slice.call(form.querySelectorAll(".quiz-option"));
    var submitting = false;

    options.forEach(function (label) {
      var input = label.querySelector(".quiz-option__input");
      if (!input) return;
      input.addEventListener("change", function () {
        options.forEach(function (other) {
          other.classList.remove("is-chosen");
        });
        label.classList.add("is-chosen");
      });
    });

    form.addEventListener("submit", function (event) {
      /* Cegah jawaban terkirim dua kali karena klik ganda atau tombol Enter. */
      if (submitting) {
        event.preventDefault();
        return;
      }
      submitting = true;
      form.classList.add("is-sending");
      var button = form.querySelector("[data-submit]");
      if (button) {
        button.disabled = true;
        button.textContent = "Mengirim...";
      }
    });
  }

  /* ---------- Confetti sederhana di layar hasil ---------- */
  function setupConfetti() {
    var host = document.querySelector("[data-confetti]");
    if (!host || reduceMotion) return;

    var colors = ["#E8B931", "#2449D8", "#20201D"];
    for (var i = 0; i < 18; i++) {
      var piece = document.createElement("span");
      piece.className = "quiz-confetti__piece";
      piece.style.left = Math.round(Math.random() * 96) + "%";
      piece.style.backgroundColor = colors[i % colors.length];
      piece.style.animationDelay = (Math.random() * 0.7).toFixed(2) + "s";
      piece.style.animationDuration = (1.6 + Math.random() * 1.1).toFixed(2) + "s";
      host.appendChild(piece);
    }
  }

  ready(function () {
    setupTimer();
    setupAnswerForm();
    setupConfetti();
  });
})();
