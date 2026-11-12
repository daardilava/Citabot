// Public pages: mobile menu, pricing period switch and the signed-in shortcut.

import { api } from "./api.js";

const toggle = document.querySelector(".menu-toggle");
const menu = document.getElementById("site-menu");
toggle?.addEventListener("click", () => {
  const open = toggle.getAttribute("aria-expanded") !== "true";
  toggle.setAttribute("aria-expanded", String(open));
  menu.classList.toggle("open", open);
});
menu?.addEventListener("click", (event) => {
  if (event.target.closest("a")) {
    toggle.setAttribute("aria-expanded", "false");
    menu.classList.remove("open");
  }
});

// Pricing: monthly or yearly figures, kept in data attributes on each element.
const periods = document.querySelectorAll("[data-period]");
for (const button of periods) {
  button.addEventListener("click", () => {
    const period = button.dataset.period;
    for (const other of periods) {
      const active = other === button;
      other.classList.toggle("active", active);
      other.setAttribute("aria-pressed", String(active));
    }
    for (const el of document.querySelectorAll("[data-monthly]")) {
      el.textContent = el.dataset[period];
    }
  });
}

// Someone already signed in sees a way back to their panel instead of the sign-in buttons.
const links = document.querySelector("[data-account-links]");
if (links) {
  api
    .me()
    .then((account) => {
      const panel = document.createElement("a");
      panel.className = "btn btn-primary";
      panel.href = "/app";
      panel.textContent = `Ir al panel de ${account.business.name}`;
      links.replaceChildren(panel);
    })
    .catch(() => {
      // Not signed in: keep "Iniciar sesión" and "Crear cuenta".
    });
}
