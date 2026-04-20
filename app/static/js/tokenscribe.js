/**
 * TokenScribe — Main JavaScript
 * Author: Matteo Morreale
 */

"use strict";

/* ── Flash auto-dismiss ─────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  const flashes = document.querySelectorAll(".ts-flash");
  flashes.forEach((el) => {
    const btn = el.querySelector(".ts-flash-close");
    if (btn) {
      btn.addEventListener("click", () => dismissFlash(el));
    }
    setTimeout(() => dismissFlash(el), 5000);
  });

  /* ── Score bar animation ───────────────────────────────────────── */
  document.querySelectorAll(".ts-score-bar-fill").forEach((bar) => {
    const pct = parseFloat(bar.dataset.value || 0) * 100;
    bar.style.width = Math.min(pct, 100) + "%";
  });

  /* ── Confirm delete forms ──────────────────────────────────────── */
  document.querySelectorAll("[data-confirm]").forEach((el) => {
    el.addEventListener("submit", (e) => {
      const msg = el.dataset.confirm || "Are you sure?";
      if (!confirm(msg)) e.preventDefault();
    });
  });

  /* ── Active nav item ───────────────────────────────────────────── */
  const path = window.location.pathname;
  document.querySelectorAll(".ts-nav-item").forEach((item) => {
    const href = item.getAttribute("href");
    if (href && path.startsWith(href) && href !== "/") {
      item.classList.add("active");
    } else if (href === "/" && path === "/") {
      item.classList.add("active");
    }
  });

  /* ── Prompt template helper ────────────────────────────────────── */
  const insertBtn = document.getElementById("ts-insert-template");
  if (insertBtn) {
    insertBtn.addEventListener("click", () => {
      const ta = document.getElementById("base_text");
      if (ta) {
        ta.value = "[Instruction]\n<<<\n[Input]\n>>>\n[Expected Output]";
        ta.focus();
      }
    });
  }

  /* ── Reset DB confirm ──────────────────────────────────────────── */
  const resetForm = document.getElementById("ts-reset-db-form");
  if (resetForm) {
    resetForm.addEventListener("submit", (e) => {
      const input = resetForm.querySelector("input[name='confirm_reset']");
      if (!input || input.value !== "RESET") {
        e.preventDefault();
        alert('Type "RESET" in the confirmation field to proceed.');
      }
    });
  }
});

function dismissFlash(el) {
  el.style.opacity = "0";
  el.style.transform = "translateX(100%)";
  el.style.transition = "all 0.2s ease";
  setTimeout(() => el.remove(), 200);
}

/* ── Score color helper ─────────────────────────────────────────── */
function scoreColor(value) {
  if (value >= 0.85) return "var(--ts-success)";
  if (value >= 0.65) return "var(--ts-warning)";
  return "var(--ts-error)";
}
