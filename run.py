"""Start Citabot from a checkout: `python run.py` (after `pip install -e .`)."""

import sys
from pathlib import Path

if sys.version_info < (3, 10):  # noqa: UP036 - friendly message on old interpreters
    sys.exit("Citabot necesita Python 3.10 o superior.")

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

try:
    from citabot.__main__ import main
except ModuleNotFoundError as missing:  # fastapi / uvicorn not installed yet
    sys.exit(f"Falta la dependencia «{missing.name}». Instálalas con:  pip install -e .")

if __name__ == "__main__":
    main()
