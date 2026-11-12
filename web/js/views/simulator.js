import { api } from "../api.js";
import { act, fmtTime, h, replace } from "../dom.js";

const REFRESH_MS = 3000;
const STORAGE_KEY = "citabot.simulator.persona";
const PERSONAS = [
  { name: "Valentina Rojas", phone: "+57 301 555 0199" },
  { name: "Mateo Herrera", phone: "+57 315 555 0142" },
  { name: "", phone: "+57 318 555 0177", label: "Número sin nombre" },
];
const SUGGESTIONS = [
  "Hola",
  "Quiero agendar una limpieza mañana a las 9",
  "¿Tienen parqueadero?",
  "¿Aceptan tarjeta?",
  "Ver mis citas",
  "Cancelar cita",
  "¿Hacen carillas de porcelana?",
  "Hablar con una persona",
];

function loadPersona() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (saved?.phone) return saved;
  } catch {
    // Storage can be unavailable (private mode); the default persona is fine.
  }
  return PERSONAS[0];
}

function savePersona(persona) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(persona));
  } catch {
    // Not essential.
  }
}

export async function mount(root) {
  let persona = loadPersona();
  let conversationId = null;
  let lastJson = "";
  let sending = false;

  const messages = h("div", { class: "phone-messages", "aria-live": "polite" });
  const quick = h("div", { class: "phone-quick" });
  const status = h("div", { class: "sim-status" });
  const personaBox = h("div", { class: "personas" });
  const input = h("input", { type: "text", maxLength: 2000, placeholder: "Escribe un mensaje", "aria-label": "Mensaje", autocomplete: "off" });
  const form = h(
    "form",
    {
      class: "phone-composer",
      onSubmit: (event) => {
        event.preventDefault();
        send(input.value);
      },
    },
    input,
    h("button", { type: "submit", "aria-label": "Enviar" }, "➤"),
  );
  const businessTitle = h("strong", null, "Negocio");

  replace(
    root,
    h("header", { class: "page-head" }, h("div", null, h("h1", null, "Simulador de WhatsApp"), h("p", { class: "muted" }, "Escribe como cliente. Pasa por el mismo agente que usaría el webhook real de WhatsApp."))),
    h(
      "div",
      { class: "sim" },
      h(
        "div",
        { class: "card" },
        h("h2", null, "¿Quién escribe?"),
        personaBox,
        h("h2", { class: "mt" }, "Mensajes para probar"),
        h("div", { class: "chips" }, SUGGESTIONS.map((text) => h("button", { class: "chip", type: "button", onClick: () => send(text) }, text))),
      ),
      h(
        "div",
        { class: "phone" },
        h("header", { class: "phone-head" }, h("span", { class: "avatar avatar-dark" }, "✓"), h("div", null, businessTitle, h("small", null, "Cuenta de empresa"))),
        messages,
        quick,
        form,
      ),
      h("div", { class: "card" }, h("h2", null, "Qué pasa en el panel"), status),
    ),
  );

  api.business().then((business) => (businessTitle.textContent = business.name)).catch(() => {});

  function renderPersonas() {
    replace(
      personaBox,
      PERSONAS.map((p) =>
        h(
          "button",
          {
            class: p.phone === persona.phone ? "persona selected" : "persona",
            type: "button",
            "aria-pressed": String(p.phone === persona.phone),
            onClick: () => switchPersona(p),
          },
          h("strong", null, p.name || p.label),
          h("small", { class: "muted" }, p.phone),
        ),
      ),
    );
  }

  async function switchPersona(next) {
    persona = next;
    savePersona(persona);
    conversationId = null;
    lastJson = "";
    renderPersonas();
    await findConversation();
    await refresh();
    input.focus();
  }

  async function findConversation() {
    const conversations = await api.conversations();
    conversationId = conversations.find((c) => c.contact.phone === persona.phone)?.id ?? null;
  }

  async function refresh() {
    const conversation = conversationId ? await api.conversation(conversationId) : null;
    const json = JSON.stringify(conversation);
    if (json === lastJson) return;
    lastJson = json;
    const items = conversation?.messages ?? [];
    replace(
      messages,
      items.length
        ? items.map((m) => h("div", { class: m.sender === "customer" ? "msg msg-out" : "msg msg-in" }, h("p", null, m.text), h("small", null, fmtTime(m.created_at))))
        : h("p", { class: "phone-empty" }, "Este número aún no ha escrito. Envía «Hola» para empezar."),
    );
    messages.scrollTop = messages.scrollHeight;

    // Quick replies of the latest bot message, like WhatsApp buttons.
    const last = items[items.length - 1];
    const options = last && last.sender !== "customer" ? last.options : [];
    replace(quick, options.map((option) => h("button", { type: "button", onClick: () => send(option) }, option)));
    renderStatus(conversation);
  }

  function renderStatus(conversation) {
    if (!conversation) {
      replace(status, h("p", { class: "muted" }, "Cuando escribas, la conversación aparecerá en Conversaciones y las citas en Agenda."));
      return;
    }
    const human = conversation.mode === "human";
    replace(
      status,
      h(
        "ul",
        { class: "facts" },
        h("li", null, h("span", { class: human ? "tag tag-human" : "tag tag-whatsapp" }, human ? "Atiende una persona" : "Atiende el bot"), human && h("p", { class: "muted" }, "El bot está en pausa. Responde desde Conversaciones o devuélvele el chat al bot.")),
        conversation.needs_attention && h("li", null, h("span", { class: "tag tag-alert" }, "Por atender"), h("p", { class: "muted" }, "El equipo ve este chat resaltado.")),
      ),
      h("div", { class: "actions actions-start" }, h("a", { class: "btn btn-small", href: `#/conversaciones/${conversation.id}` }, "Ver en Conversaciones"), h("a", { class: "btn btn-small", href: "#/agenda" }, "Ver Agenda")),
    );
  }

  async function send(text) {
    text = text.trim();
    if (!text || sending) return;
    sending = true;
    input.value = "";
    replace(quick);
    messages.append(h("div", { class: "msg msg-out msg-pending" }, h("p", null, text)));
    messages.scrollTop = messages.scrollHeight;
    await act(null, async () => {
      const result = await api.simulate({ phone: persona.phone, name: persona.name, text });
      conversationId = result.conversation_id;
      document.dispatchEvent(new Event("citabot:changed"));
    });
    sending = false;
    lastJson = "";
    await refresh().catch(() => {});
    input.focus();
  }

  renderPersonas();
  await findConversation();
  await refresh();
  const timer = setInterval(() => !sending && refresh().catch(() => {}), REFRESH_MS);
  return () => clearInterval(timer);
}
