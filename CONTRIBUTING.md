# Cómo contribuir

## Preparar el entorno

La aplicación no tiene dependencias; las herramientas de desarrollo sí.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (en macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev,llm]"
pre-commit install              # opcional: revisa cada commit antes de crearlo
```

## Flujo de trabajo

`main` siempre está desplegable y solo recibe cambios por *pull request*.

1. Crea una rama desde `main` con el tipo de cambio y un nombre corto:
   `feat/contexto-conversacion`, `fix/boton-truncado`, `chore/actualizar-ci`.
2. Haz commits pequeños con el formato [Conventional Commits](https://www.conventionalcommits.org/es/):

   ```
   feat(agent): entender «la segunda» con el contexto del chat
   fix(whatsapp): no truncar títulos de botones de más de 20 caracteres
   ```

   Tipos en uso: `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`.
   Ámbitos habituales: `agent`, `booking`, `knowledge`, `llm`, `whatsapp`, `http`, `web`.
3. Abre el *pull request* contra `main`. La integración continua debe quedar en verde.
4. Se fusiona con *squash*, de modo que cada PR es un commit en `main`.

## Antes de abrir el PR

```bash
ruff check .
ruff format --check .
mypy
python -m unittest discover -s tests -t .
```

Son los mismos pasos que ejecuta la CI en Linux y Windows, con Python 3.10 y 3.13.

## Reglas del código

- **Las dependencias apuntan hacia adentro**: `domain` no importa nada del proyecto, `application`
  solo importa `domain`, e `infrastructure` e `interfaces` implementan o usan los puertos de
  `application/ports.py`. Solo `container.py` elige adaptadores.
- **La agenda es determinista**: un modelo de lenguaje puede entender un mensaje o redactar una
  respuesta, pero nunca decide si un horario está libre.
- **La aplicación arranca sin instalar nada**: cualquier dependencia nueva es opcional y se importa
  solo cuando su adaptador está activado.
- **Cada cambio de comportamiento lleva su prueba.** Las pruebas no llaman a servicios externos;
  los adaptadores de red se prueban con clientes falsos.
- Código y comentarios en inglés; textos para el cliente y documentación en español.

## Versiones

El proyecto sigue [SemVer](https://semver.org/lang/es/). Cada cambio visible se anota en
`CHANGELOG.md` bajo «Sin publicar», y al publicar una versión se etiqueta como `vX.Y.Z`.

## Secretos

`.env` y `data/*.db` están en `.gitignore` y nunca se suben. Si un token llega a un commit,
revócalo en el proveedor: borrarlo del historial no basta.
