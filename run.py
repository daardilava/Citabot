"""Start Citabot without installing anything: `python run.py`."""

import sys
from pathlib import Path

if sys.version_info < (3, 10):  # noqa: UP036 - friendly message on old interpreters
    sys.exit("Citabot necesita Python 3.10 o superior.")

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from citabot.__main__ import main

if __name__ == "__main__":
    main()
