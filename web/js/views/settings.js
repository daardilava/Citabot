import { api } from "../api.js";
import { act, capitalize, confirmDialog, field, h, replace, toast } from "../dom.js";

const WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
const SLOT_OPTIONS = [15, 20, 30, 45, 60];

export async function mount(root) {
  const [business, services] = await Promise.all([api.business(), api.services()]);
  // Working copy of the opening hours; saved together with the rest of the form.
  const hours = Object.fromEntries(WEEKDAYS.map((_, day) => [day, (business.opening_hours[day] ?? []).map((r) => [...r])]));

  const name = h("input", { type: "text", required: true, maxLength: 80, value: business.name });
  const welcome = h("textarea", { rows: 3, required: true, maxLength: 500, value: business.welcome_message });
  const slot = h("select", null, SLOT_OPTIONS.map((m) => h("option", { value: m, selected: m === business.slot_minutes }, `${m} minutos`)));
  const hoursBox = h("div", { class: "hours" });

  function renderHours() {
    replace(
      hoursBox,
      WEEKDAYS.map((label, day) =>
        h(
          "div",
          { class: "hours-row" },
          h("span", { class: "hours-day" }, capitalize(label)),
          h(
            "div",
            { class: "hours-ranges" },
            hours[day].length === 0 && h("span", { class: "muted" }, "Cerrado"),
            hours[day].map((range, index) =>
              h(
                "span",
                { class: "range" },
                h("input", { type: "time", required: true, value: range[0], "aria-label": `${label}, abre`, onChange: (e) => (range[0] = e.target.value) }),
                "a",
                h("input", { type: "time", required: true, value: range[1], "aria-label": `${label}, cierra`, onChange: (e) => (range[1] = e.target.value) }),
                h(
                  "button",
                  {
                    class: "icon-btn",
                    type: "button",
                    "aria-label": `Quitar franja de ${label}`,
                    onClick: () => {
                      hours[day].splice(index, 1);
                      renderHours();
                    },
                  },
                  "×",
                ),
              ),
            ),
          ),
          h(
            "button",
            {
              class: "link",
              type: "button",
              onClick: () => {
                hours[day].push(hours[day].length ? ["14:00", "18:00"] : ["08:00", "12:00"]);
                renderHours();
              },
            },
            "+ franja",
          ),
        ),
      ),
    );
  }
  renderHours();

  const businessForm = h(
    "form",
    {
      class: "form",
      onSubmit: async (event) => {
        event.preventDefault();
        await act(businessForm.querySelector("[type=submit]"), async () => {
          await api.updateBusiness({ name: name.value, welcome_message: welcome.value, slot_minutes: Number(slot.value), opening_hours: hours });
          toast("Configuración guardada");
          document.dispatchEvent(new Event("citabot:changed"));
        });
      },
    },
    field("Nombre del negocio", name),
    field("Mensaje de bienvenida", welcome, "Lo que responde el agente cuando alguien saluda."),
    field("Las citas empiezan cada", slot),
    h("div", { class: "field" }, h("span", { class: "field-label" }, "Horario de atención"), hoursBox),
    h("div", { class: "actions" }, h("button", { class: "btn btn-primary", type: "submit" }, "Guardar cambios")),
  );

  const serviceList = h("div", { class: "services" });

  function serviceRow(service) {
    const isNew = !service.id;
    const nameInput = h("input", { type: "text", required: true, maxLength: 24, value: service.name, placeholder: "Nombre", "aria-label": "Nombre del servicio" });
    const duration = h("input", { type: "number", required: true, min: 5, max: 480, step: 5, value: service.duration_minutes, "aria-label": "Duración en minutos" });
    const price = h("input", { type: "text", maxLength: 30, value: service.price ?? "", placeholder: "Precio", "aria-label": "Precio" });
    const form = h(
      "form",
      {
        class: "service-row",
        onSubmit: async (event) => {
          event.preventDefault();
          await act(form.querySelector("[type=submit]"), async () => {
            const payload = { name: nameInput.value, duration_minutes: Number(duration.value), price: price.value };
            if (isNew) await api.addService(payload);
            else await api.updateService(service.id, payload);
            toast(isNew ? "Servicio agregado" : "Servicio actualizado");
            await loadServices();
          });
        },
      },
      nameInput,
      h("span", { class: "with-unit" }, duration, "min"),
      price,
      h("button", { class: "btn btn-small", type: "submit" }, isNew ? "Agregar" : "Guardar"),
      !isNew &&
        h(
          "button",
          {
            class: "link link-danger",
            type: "button",
            onClick: async (event) => {
              if (!(await confirmDialog("Quitar servicio", `«${service.name}» dejará de ofrecerse. Las citas ya agendadas se conservan.`, "Quitar"))) return;
              await act(event.target, async () => {
                await api.deleteService(service.id);
                await loadServices();
              });
            },
          },
          "Quitar",
        ),
    );
    return form;
  }

  async function loadServices(initial) {
    const items = initial ?? (await api.services());
    replace(serviceList, items.map(serviceRow), h("p", { class: "section-title" }, "Nuevo servicio"), serviceRow({ name: "", duration_minutes: 30, price: "" }));
  }
  await loadServices(services);

  replace(
    root,
    h("header", { class: "page-head" }, h("div", null, h("h1", null, "Configuración"), h("p", { class: "muted" }, "El agente usa estos datos para ofrecer horarios y responder."))),
    h(
      "div",
      { class: "grid-2 grid-top" },
      h("div", { class: "card" }, h("h2", null, "Negocio y horario"), businessForm),
      h("div", { class: "card" }, h("h2", null, "Servicios"), h("p", { class: "muted" }, "El nombre admite 24 caracteres, el límite de una fila de lista en WhatsApp."), serviceList),
    ),
  );
}
