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

  document.querySelectorAll("[data-ts-bulk-candidates='1']").forEach((card) => {
    const selectAll = card.querySelector("[data-ts-select-all]");
    const rowChecks = Array.from(
      card.querySelectorAll("input[type='checkbox'][data-ts-candidate-id]"),
    );
    const bulkForms = Array.from(card.querySelectorAll("form[data-ts-bulk-action]"));

    const updateState = () => {
      const selected = rowChecks.filter((c) => c.checked);
      const ids = selected.map((c) => c.dataset.tsCandidateId).filter(Boolean).join(",");

      bulkForms.forEach((f) => {
        const input = f.querySelector("input[name='candidate_ids']");
        const btn = f.querySelector("button[type='submit']");
        if (input) input.value = ids;
        if (btn) btn.disabled = selected.length === 0;
      });

      if (selectAll) {
        selectAll.checked = selected.length > 0 && selected.length === rowChecks.length;
        selectAll.indeterminate = selected.length > 0 && selected.length < rowChecks.length;
      }
    };

    if (selectAll) {
      selectAll.addEventListener("change", () => {
        rowChecks.forEach((c) => {
          c.checked = selectAll.checked;
        });
        updateState();
      });
    }

    rowChecks.forEach((c) => c.addEventListener("change", updateState));
    bulkForms.forEach((f) => {
      f.addEventListener("submit", (e) => {
        updateState();
        const input = f.querySelector("input[name='candidate_ids']");
        if (!input || !input.value) e.preventDefault();
      });
    });

    updateState();
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

  const langSelect = document.getElementById("language_ids");
  if (langSelect) {
    const presetButtons = Array.from(
      document.querySelectorAll("[data-ts-lang-preset-key][data-ts-lang-preset-value]"),
    );

    const setActivePresetButton = (btn) => {
      const key = btn.dataset.tsLangPresetKey;
      presetButtons
        .filter((b) => b.dataset.tsLangPresetKey === key)
        .forEach((b) => {
          b.classList.remove("ts-btn-primary");
          b.classList.add("ts-btn-secondary");
        });
      btn.classList.remove("ts-btn-secondary");
      btn.classList.add("ts-btn-primary");
    };

    presetButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.dataset.tsLangPresetKey;
        const value = btn.dataset.tsLangPresetValue;
        const options = Array.from(langSelect.options);
        const matchCount = options.filter((o) => (o.dataset[key] || "") === value).length;
        if (matchCount < 1) return;
        options.forEach((o) => {
          o.selected = (o.dataset[key] || "") === value;
        });
        setActivePresetButton(btn);
        langSelect.focus();
      });
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
