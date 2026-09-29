"""Reusable dock-panel template used by every card in the app.

Design goals (single source of truth):
- One template (``PanelDock``) for the tool panel and all inspector cards, so
  behaviour stays consistent instead of being patched per panel.
- Keep ``windowTitle`` set: QMainWindow's tab bar and the View menu use it, so
  tabbed/stacked panels always show their name.
- Use a compact custom title bar that shows only the name (no float/close
  buttons) to keep panels narrow. Visibility is toggled from the View menu.
- Keep the dock movable and floatable to all areas so it can be docked,
  tabbed and torn off freely; the custom title bar lets mouse events fall
  through to ``QDockWidget`` so drag-docking keeps working.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

TITLE_BAR_HEIGHT = 20


class PanelTitleBar(QWidget):
    """Compact title bar: panel name only, no buttons."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panelTitleBar")
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(4)
        self.label = QLabel(title, self)
        self.label.setObjectName("panelTitleLabel")
        # Let mouse events pass through so the dock can still be dragged.
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.label, 1)


class PanelDock(QDockWidget):
    """Template dock: named, compact title bar, movable/floatable everywhere."""

    def __init__(
        self,
        title: str,
        object_name: str,
        parent: QWidget | None = None,
        *,
        minimum_width: int = 0,
    ) -> None:
        super().__init__(title, parent)
        self.setObjectName(object_name)
        self.setWindowTitle(title)  # kept for tab bar / View menu / restoreState
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        if minimum_width:
            self.setMinimumWidth(minimum_width)
        self.title_bar = PanelTitleBar(title, self)
        self.setTitleBarWidget(self.title_bar)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

    def set_panel_title(self, title: str) -> None:
        self.setWindowTitle(title)
        self.title_bar.label.setText(title)
