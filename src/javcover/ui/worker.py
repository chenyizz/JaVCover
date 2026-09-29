"""Background worker thread used for OCR / PSD / export / CMYK jobs."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from javcover.tasks import TaskCancelled


class _BackgroundWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(object)
    cancelled = Signal()

    def __init__(self, work: Callable[[threading.Event], object], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._work = work
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event

    def run(self) -> None:
        try:
            result = self._work(self._cancel_event)
        except TaskCancelled:
            self.cancelled.emit()
        except Exception as error:  # noqa: BLE001 - re-raised on the UI thread
            self.failed.emit(error)
        else:
            self.succeeded.emit(result)
