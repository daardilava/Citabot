# Citabot

[![CI](https://github.com/daardilava/Citabot/actions/workflows/ci.yml/badge.svg)](https://github.com/daardilava/Citabot/actions/workflows/ci.yml)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![No dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

WhatsApp booking and FAQ agent for small businesses. A runnable MVP that works on your own machine, with a dental clinic as the demo business. The agent talks to customers in Spanish (Latin American market).

The customer writes on WhatsApp, the agent books appointments, answers from the business's knowledge base and hands the chat over to a human when it doesn't know. The team sees everything in a web dashboard.

## Run it

Requires **Python 3.10 or later**. Nothing to install: the project uses only the standard library.

```bash
python run.py
```

On Windows you can also double-click `start.bat`. Then open <http://localhost:8000>.

On first run, `data/citabot.db` is created with sample data. To return to that state, use **Reset demo data** on the Overview screen.

### Pages

| Route | What it is |
| --- | --- |
| `/` | Public landing page: features, how it works, plans and FAQ. |
| `/precios` | Pricing: plans, detailed comparison and billing questions. |
| `/registro` | Sign-up: creates a new, empty business with its first user. |
| `/login` | Sign-in. **See the demo** opens the sample clinic without a password. |
| `/app` | The dashboard. Without a session, it redirects to `/login`. |

Prices and plans are placeholders: billing is not implemented yet.

## 2-minute tour

Open <http://localhost:8000> and click **See the demo**.

1. **WhatsApp simulator** (bottom left). Send "Hola" and book an appointment with the buttons, or type it all at once: "Quiero agendar una limpieza mañana a las 9" (*I'd like to book a cleaning tomorrow at 9*).
2. **Schedule**. The appointment shows up with the WhatsApp tag. Click **Send tomorrow's reminders** and go back to the simulator to see it arrive.
3. In the simulator ask "¿Tienen parqueadero?" (*Do you have parking?*) — it answers from the knowledge base — and "¿Hacen carillas de porcelana?" (*Do you do porcelain veneers?*) — it doesn't know and offers a human.
4. **Conversations**. The chat is flagged *Needs attention*. Reply as the team: the bot pauses. Hand the chat back with **Return to bot**.
5. **Knowledge**. Add a document about veneers and ask again: now the agent answers.
6. **Settings**. Change opening hours or services; the agent uses them on the next message.

## Architecture

Hexagonal architecture (ports and adapters). Dependencies always point inward.

```
           Browser (dashboard + simulator)      Meta (WhatsApp Cloud API)
                        │  JSON                          │  webhook
                        ▼                                ▼
 interfaces/http   ── thin routes: validate, call a use case, serialize
                        │
                        ▼
 application       ── use cases: AgentService, BookingService, KnowledgeService,
                      InboxService, ReminderService, BusinessService
                      + ports.py (interfaces the application needs)
                        │
                        ▼
 domain            ── entities, pure scheduling rules, errors

 infrastructure    ── adapters that implement the ports:
                      sqlite/ · nlu/rules · retrieval/bm25 · messaging/ · clock
 container.py      ── composition root: the only place that picks adapters
```

```
src/citabot/
  domain/            models.py · scheduling.py · errors.py
  application/       agent.py · booking.py · knowledge.py · inbox.py · reminders.py
                     business.py · messenger.py · ports.py · text.py
  infrastructure/    sqlite/ · nlu/ · retrieval/ · messaging/ · clock.py · seed.py
  interfaces/http/   framework.py · server.py · api.py · schemas.py
  config.py · container.py · __main__.py
web/                 index.html · css/ · js/ (ES modules, no build step)
tests/               unittest: domain, interpreter, agent and end-to-end API
```

### Design decisions

| Decision | Why |
| --- | --- |
| **Scheduling rules are deterministic** | A language model never decides whether a slot is free. The agent understands the message and delegates the booking to `BookingService`, which validates and writes in a single transaction. |
| **The agent only answers from what it retrieved** | `KnowledgeService` answers only if retrieval clears a confidence threshold. Otherwise it flags the chat *Needs attention* and offers a human. It doesn't make things up. |
| **Ports for everything replaceable** | `MessageInterpreter`, `PassageRetriever`, `AnswerGenerator`, `MessagingGateway` and the repositories are `Protocol`s. Swapping rules for an LLM, BM25 for embeddings or SQLite for Postgres means writing one adapter. |
| **Simulator and webhook share the same use case** | Both go through `AgentService`. What you test in the simulator is what will run on real WhatsApp. |
| **Receiving and replying are two steps** | `receive` stores the message in a short transaction and the webhook acknowledges Meta immediately; `respond` runs in the background. A redelivered message is recognized by its id and never answered twice. |
| **The model never runs inside a transaction** | Understanding the message and drafting the reply happen outside the database lock, so one customer never waits on another customer's model call. The deterministic dialogue does run in a transaction; if it needs a knowledge answer, it rolls back, queries and retries. |
| **Multi-tenant by design** | Every record hangs off `business_id` and every use case receives it. `tenant()` in `api.py` takes it from the session, so no dashboard route answers without a session or reaches another business's data. |
| **No external dependencies** | Starts with `python run.py` on any machine. The trade-off: a small custom router in `framework.py` instead of FastAPI. Routes contain no logic, so migrating is mechanical. |
| **No-build frontend** | Native ES modules and an `h()` helper that only writes via `textContent`, so a customer message can't inject HTML. |
| **Colors as tokens** | Every color is a CSS variable with a light and a dark value. `theme.js` loads in the `<head>` to apply the theme before first paint, and a test requires every light token to have a dark counterpart. |

### Security built in

- The server listens on `127.0.0.1` only.
- Passwords hashed with scrypt and a per-user salt. Sessions in an `HttpOnly`, `SameSite=Lax` cookie, stored in the database only as a hash; they expire after 14 days.
- Sign-in returns the same response for an unknown email and a wrong password, with a temporary lockout after 5 failed attempts per email.
- Cross-origin writes to `/api/` are rejected (CSRF protection).
- **See the demo** opens the sample business without a password. Turn it off with `CITABOT_DEMO_LOGIN=0` before exposing the server, and set `CITABOT_COOKIE_SECURE=1` behind HTTPS.
- `X-Hub-Signature-256` signature verification on the webhook and constant-time token comparison.
- Parameterized SQL queries, a 1 MB request limit, and path-traversal protection for static files.
- `Content-Security-Policy`, `X-Frame-Options` and `X-Content-Type-Options` headers.

## Tests

```bash
python -m unittest discover -s tests -t .
```

63 tests: scheduling rules, the Spanish message interpreter, LLM adapters (with a fake client), message intake (duplicates, concurrency, migration), full agent flows, and the HTTP API against a real server on a free port.

CI runs these tests on Linux and Windows with Python 3.10 and 3.13, plus `ruff` and `mypy --strict`. Branching, commit format and environment setup are in [CONTRIBUTING.md](CONTRIBUTING.md); release history is in [CHANGELOG.md](CHANGELOG.md).

## Understanding messages with an LLM

By default the agent understands messages with rules. To use Claude for the `MessageInterpreter` port:

1. `pip install anthropic`
2. In `.env`: `NLU_PROVIDER=llm` and `ANTHROPIC_API_KEY=...`
3. Restart with `python run.py`.

The model only reads the message (intent, day, time, yes/no); scheduling stays deterministic. If the call fails, the agent falls back to the rules and logs a warning to the console. Change the model with `CITABOT_LLM_MODEL`.

With `ANSWER_PROVIDER=llm`, Claude also drafts knowledge-base answers (`AnswerGenerator` port) using only the retrieved passages. If the passages don't answer the question, the chat goes to a human; if the call fails, the passage is quoted as before. The two switches are independent.

While the knowledge base is small (up to `CITABOT_WHOLE_BASE_MAX_CHARS`, 12,000 characters by default), Claude receives all of it with every question, so it answers even when the customer uses different words ("¿dónde dejo el carro?" — *where do I leave the car?* — finds the parking document). Above that size, BM25 search with its confidence threshold takes over again.

## Connecting real WhatsApp

The `infrastructure/messaging/whatsapp_cloud.py` adapter is written but **has not been tested against Meta's servers**. Check the payloads against the current Cloud API reference before using it.

1. Create an app in Meta for Developers with the WhatsApp product and a test number.
2. Copy `.env.example` to `.env` and fill in `MESSAGING_PROVIDER=whatsapp_cloud`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN` and `WHATSAPP_APP_SECRET`.
3. Expose the port with an HTTPS tunnel (for example `cloudflared tunnel --url http://localhost:8000`).
4. In Meta, set the webhook to `https://YOUR-TUNNEL/webhooks/whatsapp` with the same verify token and subscribe to the `messages` field.

Reminders are sent outside the 24-hour window, so in production they must be **approved utility templates**; today they go out as free text.

## Roadmap to production

Ordered by what would block a first paying customer soonest.

1. **One WhatsApp number per business**: accounts and the dashboard already separate businesses, but the webhook delivers every message to the demo business. Embedded Signup is needed so each business connects its own number, plus routing by `phone_number_id`. Inviting teammates, password reset and email verification are also missing.
2. **Durable queue**: the webhook already acknowledges immediately and drops redeliveries, but pending replies live in memory. If the process stops between storing a message and answering it, that message goes unanswered. Delivery-status handling is also missing.
3. **Postgres** instead of SQLite, with an exclusion constraint for overlapping appointments.
4. **LLM on both ports**: `MessageInterpreter` (structured output) and `AnswerGenerator` (drafted answer with passages as context). Hybrid retrieval with embeddings once the corpus grows.
5. **Time zones**: times are currently server-local. Store UTC and convert with the business's time zone.
6. **Multiple practitioners or chairs** per business; today there is a single schedule.
7. **Scheduler** for reminders, subscription billing and per-business metrics.
