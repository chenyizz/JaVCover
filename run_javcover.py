"""Frozen-app launcher.

Running ``javcover.app`` as the PyInstaller entry script places ``app.py`` at the
bundle root, where ``Path(__file__).parent / "icons"`` does not match the
``--add-data`` target. Launching through this module keeps ``javcover.app``
inside the ``javcover`` package so icon/package resources resolve correctly.
"""

from javcover.app import main

if __name__ == "__main__":
    raise SystemExit(main())
