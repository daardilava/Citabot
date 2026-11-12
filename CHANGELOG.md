# Changelog

Todos los cambios visibles de este proyecto se anotan aquí. El formato sigue
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y las versiones siguen
[SemVer](https://semver.org/lang/es/).

## [Sin publicar]

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
