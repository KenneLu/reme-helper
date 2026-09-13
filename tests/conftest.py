"""Shared test bootstrap.

The suites import ``main`` the same way the app runs it: with ``src/`` on
``sys.path``. Doing that here (instead of in every file) is what let the tests
move out of the repository root without touching how they import the tool.

Run the suites from the repository root, e.g. ``python tests/test_helper.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # repository root
SRC = ROOT / "src"                                 # where main.py / i18n.py / guide.py live

for path in (str(SRC), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

# The suites print Chinese check names. When stdout is not a console - a CI pipe
# or a redirect - Windows Python falls back to the locale encoding, which on a
# hosted runner is cp1252, and every such print raises UnicodeEncodeError before
# the suite can report anything. Declare UTF-8 here so the suites behave the same
# wherever they run, and degrade instead of crashing while reporting.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):  # not a TextIOWrapper, or already detached
        pass

#: Repository root - tests write their per-run logs here, next to the build.
TOOL = ROOT
#: Where the application sources live (main.py / i18n.py / guide.py).
SRC_DIR = SRC
