// App shell: hash router, sidebar state and the "needs attention" badge.

import { api } from "./api.js";
import { h, replace } from "./dom.js";
import * as calendar from "./views/calendar.js";
import * as dashboard from "./views/dashboard.js";
import * as inbox from "./views/inbox.js";
import * as knowledge from "./views/knowledge.js";
import * as settings from "./views/settings.js";
import * as simulator from "./views/simulator.js";

const ROUTES = {
  resumen: dashboard,
  conversaciones: inbox,
  agenda: calendar,
  conocimiento: knowledge,
  configuracion: settings,
  simulador: simulator,
};
const BADGE_REFRESH_MS = 5000;

const view = document.getElementById("view");
let cleanup = null;
let renderToken = 0;

/** Each view exports `mount(root, param)` and may return a cleanup function. */
async function render() {
  const [, name = "resumen", param] = location.hash.split("/");
  const module = ROUTES[name] ?? dashboard;
  const token = ++renderToken;

  cleanup?.();
  cleanup = null;
  for (const link of document.querySelectorAll("[data-route]")) {
    const active = link.dataset.route === name;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }

  const root = h("div", { class: `page page-${name}` });
  replace(view, root);
  try {
    const result = await module.mount(root, param);
    // The user may have navigated away while the view was loading.
    if (token === renderToken) cleanup = result ?? null;
    else result?.();
  } catch (error) {
    if (token !== renderToken) return;
    replace(
      root,
      h(
        "div",
        { class: "empty" },
        h("h2", null, "No se pudo cargar esta sección"),
        h("p", { class: "muted" }, error.message),
        h("button", { class: "btn", onClick: render }, "Reintentar"),
      ),
    );
  }
}

export async function refreshShell() {
  try {
    const { business, metrics } = await api.dashboard();
    document.getElementById("business-name").textContent = business.name;
    const badge = document.getElementById("attention-badge");
    badge.hidden = metrics.needs_attention === 0;
    badge.textContent = metrics.needs_attention;
    badge.setAttribute("aria-label", `${metrics.needs_attention} por atender`);
  } catch {
    // The view itself reports connection problems; the badge just waits.
  }
}

window.addEventListener("hashchange", render);
document.addEventListener("citabot:changed", refreshShell);
setInterval(refreshShell, BADGE_REFRESH_MS);
refreshShell();
render();
