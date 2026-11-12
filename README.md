# Citabot

Agente de citas y preguntas frecuentes por WhatsApp para pymes. MVP navegable que corre en tu equipo, con una clínica dental como negocio de demostración.

El cliente escribe por WhatsApp, el agente agenda, responde con la base de conocimiento del negocio y pasa el chat a una persona cuando no sabe. El equipo ve todo en un panel web.

## Ejecutar

Requiere **Python 3.10 o superior**. No hay nada que instalar: el proyecto usa solo la biblioteca estándar.

```bash
python run.py
```

En Windows también puedes hacer doble clic en `start.bat`. Luego abre <http://localhost:8000>.

La primera vez se crea `data/citabot.db` con datos de ejemplo. Para volver a ese estado, usa **Reiniciar datos de demo** en la pantalla Resumen.

## Recorrido de 2 minutos

1. **Simulador de WhatsApp** (abajo a la izquierda). Envía «Hola» y agenda una cita con los botones, o escribe todo de una vez: «Quiero agendar una limpieza mañana a las 9».
2. **Agenda**. La cita aparece con la etiqueta WhatsApp. Pulsa **Enviar recordatorios de mañana** y vuelve al simulador para verlo llegar.
3. En el simulador pregunta «¿Tienen parqueadero?» (responde con la base de conocimiento) y «¿Hacen carillas de porcelana?» (no lo sabe y ofrece pasar a una persona).
4. **Conversaciones**. El chat queda marcado *Por atender*. Responde como equipo: el bot se pausa. Devuélvele el chat con **Devolver al bot**.
5. **Conocimiento**. Agrega un documento sobre carillas y repite la pregunta: ahora el agente responde.
6. **Configuración**. Cambia horarios o servicios; el agente los usa en el siguiente mensaje.

## Arquitectura

Arquitectura hexagonal (puertos y adaptadores). Las dependencias apuntan siempre hacia adentro.

```
            Navegador (panel + simulador)        Meta (WhatsApp Cloud API)
                        │  JSON                          │  webhook
                        ▼                                ▼
 interfaces/http   ── rutas delgadas: validar, llamar un caso de uso, serializar
                        │
                        ▼
 application       ── casos de uso: AgentService, BookingService, KnowledgeService,
                      InboxService, ReminderService, BusinessService
                      + ports.py (interfaces que la aplicación necesita)
                        │
                        ▼
 domain            ── entidades, reglas puras de agenda, errores

 infrastructure    ── adaptadores que implementan los puertos:
                      sqlite/ · nlu/rules · retrieval/bm25 · messaging/ · clock
 container.py      ── raíz de composición: el único lugar que elige adaptadores
```

```
src/citabot/
  domain/            models.py · scheduling.py · errors.py
  application/       agent.py · booking.py · knowledge.py · inbox.py · reminders.py
                     business.py · messenger.py · ports.py · text.py
  infrastructure/    sqlite/ · nlu/ · retrieval/ · messaging/ · clock.py · seed.py
  interfaces/http/   framework.py · server.py · api.py · schemas.py
  config.py · container.py · __main__.py
web/                 index.html · css/ · js/ (módulos ES, sin build)
tests/               unittest: dominio, intérprete, agente y API de punta a punta
```

### Decisiones de diseño

| Decisión | Por qué |
| --- | --- |
| **Las reglas de agenda son deterministas** | Un modelo de lenguaje nunca decide si un horario está libre. El agente entiende el mensaje y delega la reserva a `BookingService`, que valida y escribe en una sola transacción. |
| **El agente responde solo con lo recuperado** | `KnowledgeService` contesta si la recuperación supera un umbral de confianza. Si no, marca el chat *Por atender* y ofrece una persona. No inventa. |
| **Puertos para todo lo reemplazable** | `MessageInterpreter`, `PassageRetriever`, `AnswerGenerator`, `MessagingGateway` y los repositorios son `Protocol`. Cambiar reglas por un LLM, BM25 por embeddings o SQLite por Postgres es escribir un adaptador. |
| **El simulador y el webhook usan el mismo caso de uso** | Ambos llaman a `AgentService.handle_inbound`. Lo que pruebas en el simulador es lo que correrá con WhatsApp real. |
| **Multi-tenant desde el modelo** | Todo registro cuelga de `business_id` y todo caso de uso lo recibe. Hoy `tenant()` en `api.py` devuelve siempre el negocio 1. |
| **Sin dependencias externas** | Arranca con `python run.py` en cualquier equipo. El costo: un mini-router propio en `framework.py` en vez de FastAPI. Las rutas no contienen lógica, así que migrar es mecánico. |
| **Frontend sin build** | Módulos ES nativos y un helper `h()` que solo escribe con `textContent`, de modo que un mensaje de cliente no puede inyectar HTML. |

### Seguridad incluida

- El servidor escucha solo en `127.0.0.1`.
- Verificación de firma `X-Hub-Signature-256` en el webhook y comparación en tiempo constante del token.
- Consultas SQL parametrizadas, límite de 1 MB por petición, protección contra *path traversal* en archivos estáticos.
- Cabeceras `Content-Security-Policy`, `X-Frame-Options` y `X-Content-Type-Options`.

## Pruebas

```bash
python -m unittest discover -s tests -t .
```

51 pruebas: reglas de agenda, intérprete de español, adaptadores del LLM (con un cliente falso), flujos completos del agente y la API HTTP con un servidor real en un puerto libre. Opcional, si los tienes instalados: `ruff check .` y `mypy`.

## Entender los mensajes con un LLM

Por defecto el agente entiende los mensajes con reglas. Para usar Claude en el puerto `MessageInterpreter`:

1. `pip install anthropic`
2. En `.env`: `NLU_PROVIDER=llm` y `ANTHROPIC_API_KEY=...`
3. Reinicia con `python run.py`.

El modelo solo lee el mensaje (intención, día, hora, sí/no); la agenda sigue siendo determinista. Si la llamada falla, el agente usa las reglas y deja un aviso en la consola. El modelo se cambia con `CITABOT_LLM_MODEL`.

Con `ANSWER_PROVIDER=llm`, Claude también redacta las respuestas de la base de conocimiento (puerto `AnswerGenerator`) usando solo los fragmentos recuperados. Si los fragmentos no contestan la pregunta, el chat pasa a una persona; si la llamada falla, se cita el fragmento como antes. Los dos interruptores son independientes.

Mientras la base de conocimiento sea pequeña (hasta `CITABOT_WHOLE_BASE_MAX_CHARS`, 12.000 caracteres por defecto), Claude la recibe completa en cada pregunta, así que responde aunque el cliente use otras palabras («¿dónde dejo el carro?» encuentra el documento del parqueadero). Por encima de ese tamaño vuelve la búsqueda BM25 con su umbral de confianza.

## Conectar WhatsApp real

El adaptador `infrastructure/messaging/whatsapp_cloud.py` está escrito pero **no se ha probado contra los servidores de Meta**. Revisa los *payloads* contra la referencia actual de la Cloud API antes de usarlo.

1. Crea una app en Meta for Developers con el producto WhatsApp y un número de prueba.
2. Copia `.env.example` a `.env` y completa `MESSAGING_PROVIDER=whatsapp_cloud`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` y `WHATSAPP_APP_SECRET`.
3. Expón el puerto con un túnel HTTPS (por ejemplo `cloudflared tunnel --url http://localhost:8000`).
4. En Meta, configura el webhook en `https://TU-TUNEL/webhooks/whatsapp` con el mismo *verify token* y suscríbete al campo `messages`.

Los recordatorios se envían fuera de la ventana de 24 horas, así que en producción deben ser **plantillas de utilidad aprobadas**; hoy salen como texto libre.

## Qué falta para producción

Ordenado por lo que bloquea antes a un primer cliente de pago.

1. **Autenticación y tenants reales**: login del equipo, `tenant()` leído de la sesión, alta de negocios, Embedded Signup para conectar el número de cada cliente.
2. **Webhook robusto**: responder 200 de inmediato y procesar en una cola, deduplicar por id de mensaje, manejar estados de entrega.
3. **Postgres** en lugar de SQLite, con una restricción de exclusión para los solapes de citas.
4. **LLM en dos puertos**: `MessageInterpreter` (salida estructurada) y `AnswerGenerator` (respuesta redactada con los pasajes como contexto). Recuperación híbrida con embeddings cuando crezca el corpus.
5. **Zonas horarias**: hoy las horas son locales del servidor. Guardar UTC y convertir con la zona del negocio.
6. **Varios profesionales o sillas** por negocio; hoy hay una sola agenda.
7. **Planificador** para recordatorios, facturación por suscripción y métricas por negocio.
