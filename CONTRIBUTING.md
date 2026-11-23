# Contributing

## Set up the environment

The application has no dependencies; the development tools do.

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows (on macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev,llm]"
pre-commit install       # optional: checks every commit before it is created
```

## Workflow

`main` is always deployable and only receives changes through pull requests.

1. Create a branch from `main` named after the type of change plus a short name:
   `feat/conversation-context`, `fix/truncated-button`, `chore/update-ci`.
2. Make small commits using [Conventional Commits](https://www.conventionalcommits.org/en/):

   ```
   feat(agent): understand "the second one" using the chat context
   fix(whatsapp): don't truncate button titles longer than 20 characters
   ```

   Types in use: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`.
   Common scopes: `agent`, `booking`, `knowledge`, `llm`, `whatsapp`, `http`, `web`.
3. Open the pull request against `main`. CI must be green.
4. It is merged with *squash*, so each PR becomes one commit on `main`.

## Before opening the PR

```bash
ruff check .
ruff format --check .
mypy
python -m unittest discover -s tests -t .
```

These are the same steps CI runs on Linux and Windows, with Python 3.10 and 3.13.

## Code rules

- **Dependencies point inward**: `domain` imports nothing from the project, `application`
  only imports `domain`, and `infrastructure` and `interfaces` implement or use the ports in
  `application/ports.py`. Only `container.py` picks adapters.
- **Scheduling is deterministic**: a language model may understand a message or draft a reply,
  but it never decides whether a slot is free.
- **The app starts without installing anything**: any new dependency is optional and is imported
  only when its adapter is enabled.
- **Every behavior change comes with its test.** Tests never call external services;
  network adapters are tested with fake clients.
- Code, comments and documentation in English; customer-facing texts in Spanish.

## Versioning

The project follows [SemVer](https://semver.org/). Every visible change is noted in
`CHANGELOG.md` under "Unreleased", and each release is tagged as `vX.Y.Z`.

## Secrets

`.env` and `data/*.db` are in `.gitignore` and are never committed. If a token ends up in a commit,
revoke it with the provider: deleting it from the history is not enough.
