"""JAVCover application entry point (``python -m javcover.app``)."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
from PySide6.QtWidgets import QApplication

from javcover.core.constants import IMAGE_SUFFIXES
from javcover.ui.main_window import MainWindow


def _startup_path(argv: list[str]) -> Path | None:
    for argument in argv[1:]:
        if argument.startswith("-"):
            continue
        candidate = Path(argument)
        if candidate.is_file() and candidate.suffix.lower() in (
            {".javcover"} | IMAGE_SUFFIXES
        ):
            return candidate
    return None


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("JAVCover")
    app.setOrganizationName("JAVCover")
    translator = QTranslator(app)
    translations = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load("qtbase_zh_CN", translations):
        app.installTranslator(translator)
    window = MainWindow()
    window.show()
    startup = _startup_path(sys.argv)
    if startup is not None:
        QTimer.singleShot(0, lambda: window.open_path(startup))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
