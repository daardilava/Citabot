# Citabot

[![CI](https://github.com/daardilava/Citabot/actions/workflows/ci.yml/badge.svg)](https://github.com/daardilava/Citabot/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Sin dependencias](https://img.shields.io/badge/dependencias-ninguna-brightgreen)

Agente de citas y preguntas frecuentes por WhatsApp para pymes. MVP navegable que corre en tu equipo, con una clínica dental como negocio de demostración.

El cliente escribe por WhatsApp, el agente agenda, responde con la base de conocimiento del negocio y pasa el chat a una persona cuando no sabe. El equipo ve todo en un panel web.

## Ejecutar

Requiere **Python 3.10 o superior**. No hay nada que instalar: el proyecto usa solo la biblioteca estándar.

```bash
python run.py
```

En Windows también puedes hacer doble clic en `start.bat`. Luego abre <http://localhost:8000>.

La primera vez se crea `data/citabot.db` con datos de ejemplo. Para volver a ese estado, usa **Reiniciar datos de demo** en la pantalla Resumen.

### Páginas

| Ruta | Qué es |
| --- | --- |
| `/` | Página de inicio pública: funciones, cómo funciona, planes y preguntas frecuentes. |
| `/precios` | Planes, comparación detallada y preguntas sobre facturación. |
| `/registro` | Crea un negocio nuevo, vacío, con su primer usuario. |
| `/login` | Inicio de sesión. **Ver la demo** entra a la clínica de ejemplo sin contraseña. |
| `/app` | El panel. Sin sesión, redirige a `/login`. |

Los precios y planes son de muestra: la facturación todavía no está implementada.

## Recorrido de 2 minutos

Abre <http://localhost:8000> y pulsa **Ver la demo**.

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
| **El simulador y el webhook usan el mismo caso de uso** | Ambos pasan por `AgentService`. Lo que pruebas en el simulador es lo que correrá con WhatsApp real. |
| **Recibir y responder son dos pasos** | `receive` guarda el mensaje en una transacción corta y el webhook confirma a Meta de inmediato; `respond` corre en segundo plano. Un mensaje reenviado se reconoce por su id y no se responde dos veces. |
| **El modelo nunca corre dentro de una transacción** | Entender el mensaje y redactar la respuesta ocurren sin el bloqueo de la base de datos, así que un cliente no espera por la llamada al modelo de otro. El diálogo, que es determinista, sí corre en una transacción; si necesita una respuesta de conocimiento, se deshace, se consulta y se repite. |
| **Multi-tenant desde el modelo** | Todo registro cuelga de `business_id` y todo caso de uso lo recibe. `tenant()` en `api.py` lo toma de la sesión, así que ninguna ruta del panel responde sin sesión ni alcanza datos de otro negocio. |
| **Sin dependencias externas** | Arranca con `python run.py` en cualquier equipo. El costo: un mini-router propio en `framework.py` en vez de FastAPI. Las rutas no contienen lógica, así que migrar es mecánico. |
| **Frontend sin build** | Módulos ES nativos y un helper `h()` que solo escribe con `textContent`, de modo que un mensaje de cliente no puede inyectar HTML. |

### Seguridad incluida

- El servidor escucha solo en `127.0.0.1`.
- Contraseñas con scrypt y sal por usuario. Sesiones en cookie `HttpOnly` y `SameSite=Lax`, guardadas en la base solo como hash; expiran a los 14 días.
- Inicio de sesión con la misma respuesta para correo inexistente y contraseña errónea, y bloqueo temporal tras 5 intentos fallidos por correo.
- Las escrituras a `/api/` desde otro origen se rechazan (protección CSRF).
- **Ver la demo** entra sin contraseña al negocio de ejemplo. Apágalo con `CITABOT_DEMO_LOGIN=0` antes de exponer el servidor, y activa `CITABOT_COOKIE_SECURE=1` detrás de HTTPS.
- Verificación de firma `X-Hub-Signature-256` en el webhook y comparación en tiempo constante del token.
- Consultas SQL parametrizadas, límite de 1 MB por petición, protección contra *path traversal* en archivos estáticos.
- Cabeceras `Content-Security-Policy`, `X-Frame-Options` y `X-Content-Type-Options`.

## Pruebas

```bash
python -m unittest discover -s tests -t .
```

63 pruebas: reglas de agenda, intérprete de español, adaptadores del LLM (con un cliente falso), entrada de mensajes (duplicados, concurrencia, migración), flujos completos del agente y la API HTTP con un servidor real en un puerto libre. 

La integración continua ejecuta estas pruebas en Linux y Windows con Python 3.10 y 3.13, además de `ruff` y `mypy --strict`. El flujo de ramas, el formato de commits y cómo preparar el entorno están en [CONTRIBUTING.md](CONTRIBUTING.md); el historial de versiones, en [CHANGELOG.md](CHANGELOG.md).

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

1. **Un número de WhatsApp por negocio**: las cuentas y el panel ya separan negocios, pero el webhook entrega todos los mensajes al negocio de demostración. Falta Embedded Signup para que cada negocio conecte su número y enrutar por `phone_number_id`. También faltan invitar compañeros, recuperar contraseña y verificar el correo.
2. **Cola duradera**: el webhook ya confirma de inmediato y descarta reenvíos, pero las respuestas pendientes viven en memoria. Si el proceso se detiene entre guardar un mensaje y responderlo, ese mensaje queda sin respuesta. Falta también manejar los estados de entrega.
3. **Postgres** en lugar de SQLite, con una restricción de exclusión para los solapes de citas.
4. **LLM en dos puertos**: `MessageInterpreter` (salida estructurada) y `AnswerGenerator` (respuesta redactada con los pasajes como contexto). Recuperación híbrida con embeddings cuando crezca el corpus.
5. **Zonas horarias**: hoy las horas son locales del servidor. Guardar UTC y convertir con la zona del negocio.
6. **Varios profesionales o sillas** por negocio; hoy hay una sola agenda.
7. **Planificador** para recordatorios, facturación por suscripción y métricas por negocio.
