import { api } from "../api.js";
import { act, confirmDialog, displayName, fmtDay, fmtTime, h, replace, toast } from "../dom.js";

const WEEKDAY = new Intl.DateTimeFormat("es", { weekday: "short" });

export async function mount(root) {
  async function load() {
    const { business, metrics, upcoming } = await api.dashboard();
    const automation = metrics.automation_rate == null ? "—" : `${Math.round(metrics.automation_rate * 100)}%`;

    replace(
      root,
      h(
        "header",
        { class: "page-head" },
        h("div", null, h("h1", null, "Resumen"), h("p", { class: "muted" }, `Así va ${business.name} en WhatsApp.`)),
        // Only the demo business can be put back to its sample data.
        document.documentElement.dataset.demo === "true" &&
          h("button", { class: "btn", type: "button", onClick: reset }, "Reiniciar datos de demo"),
      ),
      h(
        "section",
        { class: "stats" },
        stat("Citas hoy", metrics.appointments_today, "#/agenda"),
        stat("Citas en 7 días", metrics.appointments_next_7_days, "#/agenda"),
        stat("Por atender", metrics.needs_attention, "#/conversaciones", metrics.needs_attention > 0),
        stat("Respuestas automáticas", automation, "#/conversaciones", false, "últimos 7 días"),
      ),
      h(
        "section",
        { class: "grid-2" },
        h("div", { class: "card" }, h("h2", null, "Citas de los próximos 7 días"), chart(metrics.appointments_by_day)),
        h(
          "div",
          { class: "card" },
          h("h2", null, "Próximas citas"),
          upcoming.length
            ? h("ul", { class: "list" }, upcoming.map(appointmentRow))
            : h("p", { class: "muted" }, "No hay citas confirmadas."),
        ),
      ),
      h(
        "section",
        { class: "card cta" },
        h(
          "div",
          null,
          h("h2", null, "Prueba el agente como lo vería un cliente"),
          h(
            "p",
            { class: "muted" },
            `El agente ha agendado ${metrics.booked_by_bot} citas por WhatsApp. Abre el simulador, pide una cita y mírala aparecer en la agenda.`,
          ),
        ),
        h("a", { class: "btn btn-primary", href: "#/simulador" }, "Abrir simulador"),
      ),
    );
  }

  async function reset(event) {
    const ok = await confirmDialog(
      "Reiniciar datos de demo",
      "Se borran las conversaciones, citas y cambios de configuración, y se cargan de nuevo los datos de ejemplo.",
      "Reiniciar",
    );
    if (!ok) return;
    await act(event.target, async () => {
      await api.resetDemo();
      toast("Datos de demo reiniciados");
      document.dispatchEvent(new Event("citabot:changed"));
      await load();
    });
  }

  await load();
}

function stat(label, value, href, alert = false, note = "") {
  return h(
    "a",
    { class: alert ? "stat stat-alert" : "stat", href },
    h("span", { class: "stat-label" }, label),
    h("strong", { class: "stat-value" }, String(value)),
    note && h("span", { class: "stat-note" }, note),
  );
}

function chart(days) {
  const max = Math.max(1, ...days.map((d) => d.count));
  return h(
    "div",
    { class: "chart", role: "img", "aria-label": days.map((d) => `${d.date}: ${d.count}`).join(", ") },
    days.map((day) => {
      const bar = h("div", { class: day.count ? "bar" : "bar bar-empty" });
      bar.style.height = `${Math.max(4, (day.count / max) * 100)}%`;
      return h(
        "div",
        { class: "chart-col" },
        h("span", { class: "chart-value" }, String(day.count)),
        h("div", { class: "chart-track" }, bar),
        h("span", { class: "chart-label" }, WEEKDAY.format(new Date(`${day.date}T12:00`)).replace(".", "")),
      );
    }),
  );
}

function appointmentRow(appointment) {
  return h(
    "li",
    { class: "row" },
    h("div", { class: "row-time" }, h("strong", null, fmtTime(appointment.starts_at)), h("small", null, fmtDay(appointment.starts_at).split(",")[0])),
    h("div", { class: "row-main" }, h("strong", null, displayName(appointment.contact)), h("small", { class: "muted" }, appointment.service.name)),
    h("span", { class: `tag tag-${appointment.source}` }, appointment.source === "whatsapp" ? "WhatsApp" : "Panel"),
  );
}
