import { api } from "../api.js";
import { act, displayName, fmtTime, h, initials, relativeTime, replace } from "../dom.js";

const REFRESH_MS = 3000;

export async function mount(root, param) {
  let selectedId = param ? Number(param) : null;
  let lastListJson = "";
  let lastThreadJson = "";

  const list = h("ul", { class: "inbox-list", "aria-label": "Conversaciones" });
  const thread = h("section", { class: "thread" });
  replace(
    root,
    h("header", { class: "page-head" }, h("div", null, h("h1", null, "Conversaciones"), h("p", { class: "muted" }, "Lo que el agente responde y los chats que esperan a una persona."))),
    h("div", { class: "inbox" }, h("div", { class: "inbox-side" }, list), thread),
  );

  async function refreshList() {
    const conversations = await api.conversations();
    const json = JSON.stringify(conversations);
    if (json === lastListJson) return;
    lastListJson = json;
    if (selectedId == null && conversations.length) selectedId = conversations[0].id;
    replace(
      list,
      conversations.length
        ? conversations.map((c) => listItem(c, c.id === selectedId, select))
        : h("li", { class: "muted pad" }, "Aún no hay conversaciones. Escribe desde el simulador."),
    );
  }

  async function refreshThread(force = false) {
    if (selectedId == null) {
      replace(thread, h("div", { class: "empty" }, h("p", { class: "muted" }, "Elige una conversación.")));
      return;
    }
    const conversation = await api.conversation(selectedId);
    const json = JSON.stringify(conversation);
    if (json === lastThreadJson && !force) return;
    lastThreadJson = json;
    renderThread(conversation);
  }

  function select(id) {
    selectedId = id;
    lastListJson = "";
    history.replaceState(null, "", `#/conversaciones/${id}`);
    refresh(true);
  }

  async function refresh(force = false) {
    await Promise.all([refreshList(), refreshThread(force)]);
  }

  async function change(control, changes) {
    await act(control, async () => {
      await api.updateConversation(selectedId, changes);
      document.dispatchEvent(new Event("citabot:changed"));
      await refresh(true);
    });
  }

  function renderThread(conversation) {
    const isBot = conversation.mode === "bot";
    const draft = thread.querySelector("textarea")?.value ?? "";
    const input = h("textarea", {
      rows: 2,
      maxLength: 2000,
      placeholder: isBot ? "Escribe para tomar el chat: el bot se pausa al enviar" : "Escribe tu respuesta",
      "aria-label": "Respuesta",
      value: draft,
      onKeydown: (event) => {
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          form.requestSubmit();
        }
      },
    });
    const form = h(
      "form",
      {
        class: "composer",
        onSubmit: async (event) => {
          event.preventDefault();
          const text = input.value.trim();
          if (!text) return;
          await act(form.querySelector("button"), async () => {
            await api.reply(selectedId, text);
            input.value = "";
            document.dispatchEvent(new Event("citabot:changed"));
            await refresh(true);
          });
          thread.querySelector("textarea")?.focus();
        },
      },
      input,
      h("button", { class: "btn btn-primary", type: "submit" }, "Enviar"),
    );

    const messages = h("div", { class: "messages" }, conversation.messages.map(bubble));
    replace(
      thread,
      h(
        "header",
        { class: "thread-head" },
        h("span", { class: "avatar" }, initials(conversation.contact.name)),
        h("div", { class: "thread-who" }, h("strong", null, displayName(conversation.contact)), h("small", { class: "muted" }, conversation.contact.phone)),
        conversation.needs_attention &&
          h("button", { class: "btn btn-small", type: "button", onClick: (e) => change(e.target, { needs_attention: false }) }, "Marcar como atendida"),
        h(
          "button",
          {
            class: isBot ? "btn btn-small" : "btn btn-small btn-primary",
            type: "button",
            onClick: (e) => change(e.target, { mode: isBot ? "human" : "bot" }),
          },
          isBot ? "Pausar bot y atender" : "Devolver al bot",
        ),
      ),
      h(
        "p",
        { class: isBot ? "mode-banner" : "mode-banner mode-human" },
        isBot ? "El bot responde este chat automáticamente." : "Bot en pausa: una persona del equipo atiende este chat.",
      ),
      messages,
      form,
    );
    messages.scrollTop = messages.scrollHeight;
  }

  await refresh(true);
  const timer = setInterval(() => refresh().catch(() => {}), REFRESH_MS);
  return () => clearInterval(timer);
}

function listItem(conversation, selected, onSelect) {
  const last = conversation.last_message;
  return h(
    "li",
    null,
    h(
      "button",
      {
        class: selected ? "inbox-item selected" : "inbox-item",
        type: "button",
        "aria-current": selected ? "true" : null,
        onClick: () => onSelect(conversation.id),
      },
      h("span", { class: "avatar" }, initials(conversation.contact.name)),
      h(
        "span",
        { class: "inbox-text" },
        h("span", { class: "inbox-top" }, h("strong", null, displayName(conversation.contact)), h("small", { class: "muted" }, last ? relativeTime(last.created_at) : "")),
        h("span", { class: "inbox-snippet" }, last ? `${last.direction === "out" ? "↩ " : ""}${last.text}` : "Sin mensajes"),
        h(
          "span",
          { class: "inbox-tags" },
          conversation.needs_attention && h("span", { class: "tag tag-alert" }, "Por atender"),
          conversation.mode === "human" && h("span", { class: "tag tag-human" }, "Humano"),
        ),
      ),
    ),
  );
}

const SENDER_LABEL = { bot: "Bot", agent: "Equipo", customer: "" };

export function bubble(message) {
  return h(
    "div",
    { class: `bubble bubble-${message.sender}` },
    h("p", null, message.text),
    message.options.length > 0 && h("div", { class: "bubble-options" }, message.options.map((option) => h("span", null, option))),
    h("small", null, [SENDER_LABEL[message.sender], fmtTime(message.created_at)].filter(Boolean).join(" · ")),
  );
}
