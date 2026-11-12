import { api } from "../api.js";
import { act, confirmDialog, field, h, replace, toast } from "../dom.js";

const ANSWER_THRESHOLD = 0.5; // keep in sync with KnowledgeService.min_confidence

export async function mount(root) {
  const list = h("div", { class: "docs" });
  const results = h("div", { class: "results" });

  const title = h("input", { type: "text", required: true, maxLength: 120, placeholder: "Ej. Política de garantías" });
  const content = h("textarea", { rows: 5, required: true, maxLength: 20000, placeholder: "Escribe la información tal como se la dirías a un cliente. Separa los temas con una línea en blanco." });
  const addForm = h(
    "form",
    {
      class: "form",
      onSubmit: async (event) => {
        event.preventDefault();
        await act(addForm.querySelector("button"), async () => {
          await api.addDoc({ title: title.value, content: content.value });
          addForm.reset();
          toast("Documento agregado: el agente ya puede usarlo");
          await load();
        });
      },
    },
    field("Título", title),
    field("Contenido", content),
    h("div", { class: "actions" }, h("button", { class: "btn btn-primary", type: "submit" }, "Agregar documento")),
  );

  const question = h("input", { type: "search", required: true, maxLength: 500, placeholder: "Ej. ¿Aceptan tarjeta?", "aria-label": "Pregunta de prueba" });
  const searchForm = h(
    "form",
    {
      class: "search",
      onSubmit: async (event) => {
        event.preventDefault();
        await act(searchForm.querySelector("button"), async () => renderResults(await api.searchDocs(question.value)));
      },
    },
    question,
    h("button", { class: "btn", type: "submit" }, "Probar"),
  );

  replace(
    root,
    h("header", { class: "page-head" }, h("div", null, h("h1", null, "Conocimiento"), h("p", { class: "muted" }, "Lo que el agente sabe del negocio. Responde solo con esta información; si no la encuentra, pasa el chat a una persona."))),
    h(
      "div",
      { class: "grid-2 grid-top" },
      h("div", null, h("div", { class: "card" }, h("h2", null, "Agregar documento"), addForm), list),
      h(
        "div",
        { class: "card sticky" },
        h("h2", null, "Probar una pregunta"),
        h("p", { class: "muted" }, `Mira qué fragmento recupera el buscador. El agente responde cuando la confianza es de ${ANSWER_THRESHOLD * 100}% o más.`),
        searchForm,
        results,
      ),
    ),
  );

  function renderResults(passages) {
    if (!passages.length) {
      replace(results, h("p", { class: "muted" }, "Sin coincidencias: el agente ofrecería pasar el chat a una persona."));
      return;
    }
    replace(
      results,
      passages.map((p, index) => {
        const answers = index === 0 && p.confidence >= ANSWER_THRESHOLD;
        const meter = h("span", { class: "meter-fill" });
        meter.style.width = `${Math.round(p.confidence * 100)}%`;
        return h(
          "article",
          { class: answers ? "result result-win" : "result" },
          h("header", null, h("strong", null, p.title), answers && h("span", { class: "tag tag-whatsapp" }, "El agente respondería esto")),
          h("p", null, p.text),
          h("div", { class: "meter", "aria-hidden": "true" }, meter),
          h("small", { class: "muted" }, `Confianza ${Math.round(p.confidence * 100)}% · puntaje BM25 ${p.score}`),
        );
      }),
    );
  }

  async function load() {
    const docs = await api.docs();
    replace(
      list,
      h("h2", { class: "section-title" }, `Documentos (${docs.length})`),
      docs.map((doc) =>
        h(
          "article",
          { class: "card doc" },
          h(
            "header",
            null,
            h("h3", null, doc.title),
            h(
              "button",
              {
                class: "link link-danger",
                type: "button",
                onClick: async (event) => {
                  if (!(await confirmDialog("Eliminar documento", `El agente dejará de usar «${doc.title}».`, "Eliminar"))) return;
                  await act(event.target, async () => {
                    await api.deleteDoc(doc.id);
                    await load();
                  });
                },
              },
              "Eliminar",
            ),
          ),
          h("p", { class: "doc-content" }, doc.content),
        ),
      ),
    );
  }

  await load();
}
