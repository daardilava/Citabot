// DOM helpers. Text always goes through textContent/append, never innerHTML,
// so customer messages can never inject markup into the panel.

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key in el && key !== "list" && key !== "form") el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  el.append(...children.flat(Infinity).filter((child) => child != null && child !== false));
  return el;
}

export function replace(parent, ...children) {
  parent.replaceChildren(...children.flat(Infinity).filter(Boolean));
}

export function toast(message, kind = "ok") {
  const el = h("div", { class: `toast toast-${kind}` }, message);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.classList.add("toast-out"), 3200);
  setTimeout(() => el.remove(), 3600);
}

/** Run an async action from a click or submit: disables the control and reports errors. */
export async function act(control, action) {
  if (control) control.disabled = true;
  try {
    return await action();
  } catch (error) {
    toast(error.message ?? "Algo salió mal.", "error");
    return undefined;
  } finally {
    if (control) control.disabled = false;
  }
}

/** Modal dialog built on <dialog>: focus trap and Esc come from the browser. */
export function openModal(title, body, { wide = false } = {}) {
  const dialog = h(
    "dialog",
    { class: wide ? "modal modal-wide" : "modal" },
    h(
      "header",
      { class: "modal-head" },
      h("h2", null, title),
      h("button", { class: "icon-btn", type: "button", "aria-label": "Cerrar", onClick: () => dialog.close() }, "×"),
    ),
    h("div", { class: "modal-body" }, body),
  );
  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close(); // click on the backdrop
  });
  document.body.append(dialog);
  dialog.showModal();
  return dialog;
}

export function confirmDialog(title, message, confirmLabel, danger = true) {
  return new Promise((resolve) => {
    let answer = false;
    const dialog = openModal(
      title,
      h(
        "div",
        null,
        h("p", { class: "muted" }, message),
        h(
          "div",
          { class: "actions" },
          h("button", { class: "btn", type: "button", onClick: () => dialog.close() }, "Volver"),
          h(
            "button",
            {
              class: danger ? "btn btn-danger" : "btn btn-primary",
              type: "button",
              onClick: () => {
                answer = true;
                dialog.close();
              },
            },
            confirmLabel,
          ),
        ),
      ),
    );
    dialog.addEventListener("close", () => resolve(answer));
  });
}

export function field(label, control, hint) {
  return h("label", { class: "field" }, h("span", { class: "field-label" }, label), control, hint && h("small", { class: "muted" }, hint));
}

// ---------------------------------------------------------------- formatting

const dayFormat = new Intl.DateTimeFormat("es", { weekday: "long", day: "numeric", month: "long" });
const shortDayFormat = new Intl.DateTimeFormat("es", { weekday: "short", day: "numeric", month: "short" });
const timeFormat = new Intl.DateTimeFormat("es", { hour: "2-digit", minute: "2-digit", hour12: false });

export const fmtTime = (iso) => timeFormat.format(new Date(iso));
export const fmtDay = (iso) => capitalize(dayFormat.format(new Date(iso)));
export const fmtShortDay = (iso) => capitalize(shortDayFormat.format(new Date(iso)));
export const capitalize = (text) => text.charAt(0).toUpperCase() + text.slice(1);

/** Local YYYY-MM-DD (toISOString would shift the day in timezones behind UTC). */
export function isoDate(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function addDays(date, days) {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
}

export function relativeTime(iso) {
  const then = new Date(iso);
  const minutes = Math.round((Date.now() - then.getTime()) / 60000);
  if (minutes < 1) return "ahora";
  if (minutes < 60) return `hace ${minutes} min`;
  if (minutes < 60 * 24 && then.getDate() === new Date().getDate()) return fmtTime(iso);
  return fmtShortDay(iso);
}

export function initials(name) {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  return (parts.length ? parts.slice(0, 2).map((p) => p[0]).join("") : "?").toUpperCase();
}

export const displayName = (contact) => contact.name || contact.phone;
