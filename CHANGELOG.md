# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added

- Dark mode on every page. It follows the system preference until you pick one with the
  sun/moon button, and the choice is remembered in that browser.

- Public site: landing page, pricing, sign-up, sign-in and 404 page, with clean
  URLs (`/precios`, `/login`, `/registro`). The dashboard moves to `/app`.
- Accounts: each sign-up creates its own empty business. The dashboard requires a session and each
  business only sees its own data.
- Sessions in an `HttpOnly` cookie, scrypt password hashing, temporary lockout after failed attempts and
  rejection of cross-site writes.
- "See the demo" opens the sample clinic without a password; turn it off with `CITABOT_DEMO_LOGIN=0`.

- The WhatsApp webhook stores the message, acknowledges Meta immediately and replies in the
  background, in order within each conversation.
- Messages redelivered by Meta are recognized by their id and never answered twice.

### Changed

- Language model calls no longer happen inside the database transaction:
  one customer never waits on another's reply and the dashboard no longer freezes.
- Existing databases migrate themselves when opened (`messages.external_id` column and
  `users` and `sessions` tables).
- "Reset demo data" only affects the demo business and keeps all accounts.

### Fixed

- The connection to the Anthropic API uses IPv4 only, avoiding ~20 s waits on networks
  with misrouted IPv6.

## [0.1.0] - 2026-11-12

First release: a runnable MVP that runs on a single machine.

### Added

- Conversational agent that books, cancels and lists appointments over WhatsApp, with deterministic
  scheduling rules.
- Per-business knowledge base with BM25 search and handover to a human when there is no answer.
- Web dashboard: overview, schedule, conversations, knowledge, settings and WhatsApp simulator.
- Reminders for next-day appointments.
- WhatsApp Cloud API adapter with webhook signature verification (not tested against Meta).
- Message understanding with Claude (`NLU_PROVIDER=llm`), falling back to the rules.
- Knowledge-base answers drafted by Claude (`ANSWER_PROVIDER=llm`), which reads the whole
  base when it is small and abstains when it doesn't contain the answer.
- Continuous integration (lint, types and tests on Linux and Windows), PR and issue templates and a
  contributing guide.

[Unreleased]: https://github.com/daardilava/Citabot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/daardilava/Citabot/releases/tag/v0.1.0
