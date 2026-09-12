"""reme-helper sources.

Layout note (why this package has no imports of its own):

* ``main.py`` is the entry point and is run as a **script** (``python src/main.py``,
  and as PyInstaller's entry with ``--paths src``), never as ``python -m src.main``:
  on Windows ``python -m`` would attach a console window, and this is a tray app.
* Running it as a script puts this directory on ``sys.path``, so ``main.py`` imports
  ``i18n`` and ``guide`` as plain absolute modules. Keeping that true is what makes
  the frozen build and a source run behave the same, so nothing here re-exports them.
* ``tests/conftest.py`` puts this directory on ``sys.path`` for the test suites, so
  they import ``main`` the same way the app runs it.
"""
