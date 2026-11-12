# Changelog

Todos los cambios visibles de este proyecto se anotan aquí. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones siguen
[SemVer](https://semver.org/lang/es/).

## [Sin publicar]

### Añadido

- Sitio público: página de inicio, precios, registro, inicio de sesión y página 404, con URLs
  limpias (`/precios`, `/login`, `/registro`). El panel pasa a `/app`.
- Cuentas: cada registro crea un negocio propio y vacío. El panel exige sesión y cada negocio solo
  ve sus datos.
- Sesiones en cookie `HttpOnly`, contraseñas con scrypt, bloqueo temporal tras intentos fallidos y
  rechazo de escrituras desde otros sitios.
- «Ver la demo» entra a la clínica de ejemplo sin contraseña; se apaga con `CITABOT_DEMO_LOGIN=0`.

- El webhook de WhatsApp guarda el mensaje, confirma a Meta de inmediato y responde en segundo
  plano, en orden dentro de cada conversación.
- Los mensajes que Meta reenvía se reconocen por su id y no se responden dos veces.

### Cambiado

- Las llamadas al modelo de lenguaje ya no ocurren dentro de la transacción de la base de datos:
  un cliente no espera por la respuesta de otro y el panel no se congela.
- Las bases de datos existentes se migran solas al abrirlas (columna `messages.external_id` y
  tablas `users` y `sessions`).
- «Reiniciar datos de demo» solo afecta al negocio de demostración y conserva todas las cuentas.

### Corregido

- La conexión con la API de Anthropic usa solo IPv4, lo que evita esperas de unos 20 s en redes
  con IPv6 mal enrutado.

## [0.1.0] - 2026-11-12

Primera versión: MVP navegable que corre en un solo equipo.

### Añadido

- Agente conversacional que agenda, cancela y lista citas por WhatsApp, con reglas de agenda
  deterministas.
- Base de conocimiento por negocio con búsqueda BM25 y paso a una persona cuando no hay respuesta.
- Panel web: resumen, agenda, conversaciones, conocimiento, configuración y simulador de WhatsApp.
- Recordatorios de citas del día siguiente.
- Adaptador de WhatsApp Cloud API con verificación de firma del webhook (sin probar contra Meta).
- Comprensión de mensajes con Claude (`NLU_PROVIDER=llm`), con respaldo en las reglas.
- Respuestas de la base de conocimiento redactadas por Claude (`ANSWER_PROVIDER=llm`), que lee la
  base completa cuando es pequeña y se abstiene cuando no contiene la respuesta.
- Integración continua (lint, tipos y pruebas en Linux y Windows), plantillas de PR e issues y
  guía de contribución.

[Sin publicar]: https://github.com/daardilava/Citabot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/daardilava/Citabot/releases/tag/v0.1.0
