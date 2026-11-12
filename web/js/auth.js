// Sign-in and sign-up pages.

import { api } from "./api.js";

const PANEL = "/app";
const form = document.querySelector("[data-auth-form]");
const errorBox = form.querySelector(".form-error");
const submit = form.querySelector("[type=submit]");
const demoButton = document.querySelector("[data-demo-button]");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

async function run(control, action) {
  errorBox.hidden = true;
  control.disabled = true;
  try {
    await action();
  } catch (error) {
    showError(error.message ?? "Algo salió mal. Intenta de nuevo.");
    control.disabled = false;
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  const data = Object.fromEntries(new FormData(form));
  run(submit, async () => {
    if (form.dataset.authForm === "signup") {
      await api.signup(data);
      // A new business has no services yet: start where they are set up.
      location.assign(`${PANEL}#/configuracion`);
    } else {
      await api.login(data);
      location.assign(PANEL);
    }
  });
});

function enterDemo() {
  return run(demoButton ?? submit, async () => {
    await api.loginDemo();
    location.assign(PANEL);
  });
}

demoButton?.addEventListener("click", enterDemo);

async function start() {
  // Already signed in: there is nothing to do here.
  try {
    await api.me();
    return location.replace(PANEL);
  } catch {
    // Not signed in.
  }
  if (!demoButton) return;
  const { demo_login: demoAvailable } = await api.health().catch(() => ({ demo_login: false }));
  for (const el of document.querySelectorAll("[data-demo]")) el.hidden = !demoAvailable;
  // "Ver la demo" links land here with ?demo=1: go straight in.
  if (demoAvailable && new URLSearchParams(location.search).has("demo")) enterDemo();
}

start();
