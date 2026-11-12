import { api } from "../api.js";
import { act, addDays, confirmDialog, displayName, field, fmtShortDay, fmtTime, h, isoDate, openModal, replace, toast } from "../dom.js";

const STATUS_LABEL = { confirmed: "Confirmada", cancelled: "Cancelada", completed: "Atendida" };

function mondayOf(date) {
  const copy = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return addDays(copy, -((copy.getDay() + 6) % 7));
}

export async function mount(root) {
  let weekStart = mondayOf(new Date());
  const title = h("h2", { class: "week-title" });
  const grid = h("div", { class: "week" });

  replace(
    root,
    h(
      "header",
      { class: "page-head" },
      h("div", null, h("h1", null, "Agenda"), h("p", { class: "muted" }, "Citas agendadas por el agente y por el equipo.")),
      h(
        "div",
        { class: "actions" },
        h("button", { class: "btn", type: "button", onClick: sendReminders }, "Enviar recordatorios de mañana"),
        h("button", { class: "btn btn-primary", type: "button", onClick: () => newAppointment(load) }, "Nueva cita"),
      ),
    ),
    h(
      "div",
      { class: "week-nav" },
      h("button", { class: "btn btn-small", type: "button", "aria-label": "Semana anterior", onClick: () => move(-7) }, "←"),
      h("button", { class: "btn btn-small", type: "button", onClick: () => move(0) }, "Hoy"),
      h("button", { class: "btn btn-small", type: "button", "aria-label": "Semana siguiente", onClick: () => move(7) }, "→"),
      title,
    ),
    grid,
  );

  function move(days) {
    weekStart = days === 0 ? mondayOf(new Date()) : addDays(weekStart, days);
    load().catch((error) => toast(error.message, "error"));
  }

  async function load() {
    const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i));
    const appointments = await api.appointments(isoDate(days[0]), isoDate(days[6]));
    title.textContent = `${fmtShortDay(days[0])} – ${fmtShortDay(days[6])}`;
    const today = isoDate(new Date());
    replace(
      grid,
      days.map((day) => {
        const key = isoDate(day);
        const items = appointments.filter((a) => a.starts_at.startsWith(key));
        return h(
          "section",
          { class: key === today ? "day day-today" : "day" },
          h("h3", null, fmtShortDay(day), key === today && h("span", { class: "tag tag-whatsapp" }, "Hoy")),
          items.length ? items.map((a) => card(a, load)) : h("p", { class: "day-empty" }, "Sin citas"),
        );
      }),
    );
  }

  async function sendReminders(event) {
    await act(event.target, async () => {
      const { sent } = await api.runReminders();
      toast(sent ? `${sent} recordatorio(s) enviados. Míralos en Conversaciones.` : "No hay recordatorios pendientes para mañana.");
      await load();
    });
  }

  await load();
}

function card(appointment, reload) {
  async function setStatus(event, status, question, label) {
    if (question && !(await confirmDialog(label, question, label))) return;
    await act(event.target, async () => {
      await api.setAppointmentStatus(appointment.id, status);
      document.dispatchEvent(new Event("citabot:changed"));
      await reload();
    });
  }
  const confirmed = appointment.status === "confirmed";
  return h(
    "article",
    { class: `appt appt-${appointment.status}` },
    h("div", { class: "appt-time" }, `${fmtTime(appointment.starts_at)} – ${fmtTime(appointment.ends_at)}`),
    h("strong", null, displayName(appointment.contact)),
    h("small", { class: "muted" }, appointment.service.name),
    h(
      "div",
      { class: "appt-tags" },
      h("span", { class: `tag tag-${appointment.status}` }, STATUS_LABEL[appointment.status]),
      h("span", { class: `tag tag-${appointment.source}` }, appointment.source === "whatsapp" ? "WhatsApp" : "Panel"),
      appointment.reminder_sent && h("span", { class: "tag" }, "Recordada"),
    ),
    confirmed &&
      h(
        "div",
        { class: "appt-actions" },
        h("button", { class: "link", type: "button", onClick: (e) => setStatus(e, "completed") }, "Atendida"),
        h(
          "button",
          { class: "link link-danger", type: "button", onClick: (e) => setStatus(e, "cancelled", `Se cancelará la cita de ${displayName(appointment.contact)}.`, "Cancelar cita") },
          "Cancelar",
        ),
      ),
  );
}

async function newAppointment(reload) {
  const services = await api.services();
  const name = h("input", { type: "text", required: true, maxLength: 80, autocomplete: "off" });
  const phone = h("input", { type: "tel", required: true, maxLength: 30, placeholder: "+57 300 000 0000", autocomplete: "off" });
  const service = h("select", { required: true }, services.map((s) => h("option", { value: s.id }, `${s.name} · ${s.duration_minutes} min`)));
  const date = h("input", { type: "date", required: true, value: isoDate(addDays(new Date(), 1)), min: isoDate(new Date()) });
  const slot = h("select", { required: true });
  const hint = h("small", { class: "muted" });

  async function loadSlots() {
    replace(slot);
    hint.textContent = "";
    if (!date.value || !service.value) return;
    try {
      const { slots } = await api.availability(service.value, date.value);
      replace(slot, slots.map((s) => h("option", { value: s }, fmtTime(s))));
      if (!slots.length) hint.textContent = "No hay horarios disponibles ese día.";
    } catch (error) {
      hint.textContent = error.message;
    }
  }
  service.addEventListener("change", loadSlots);
  date.addEventListener("change", loadSlots);

  const form = h(
    "form",
    {
      class: "form",
      onSubmit: async (event) => {
        event.preventDefault();
        await act(form.querySelector("[type=submit]"), async () => {
          await api.createAppointment({ name: name.value, phone: phone.value, service_id: Number(service.value), starts_at: slot.value });
          dialog.close();
          toast("Cita creada");
          document.dispatchEvent(new Event("citabot:changed"));
          await reload();
        });
      },
    },
    field("Nombre del cliente", name),
    field("Teléfono (WhatsApp)", phone),
    field("Servicio", service),
    h("div", { class: "form-row" }, field("Fecha", date), field("Hora", slot)),
    hint,
    h("div", { class: "actions" }, h("button", { class: "btn btn-primary", type: "submit" }, "Crear cita")),
  );
  const dialog = openModal("Nueva cita", form);
  await loadSlots();
  name.focus();
}
