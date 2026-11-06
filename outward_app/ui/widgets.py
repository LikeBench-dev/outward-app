from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QAbstractButton, QAbstractItemView, QAbstractSpinBox, QComboBox, QLabel, QMenu, QScrollBar, QSizePolicy, QStackedLayout, QWidget


class PointerCursors(QObject):
    """Apply the app's pointer convention to controls, including popup menus."""

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.Polish, QEvent.Type.EnabledChange, QEvent.Type.Show):
            if isinstance(watched, (QAbstractButton, QAbstractSpinBox, QComboBox, QScrollBar)):
                watched.setCursor(Qt.CursorShape.PointingHandCursor if watched.isEnabled() else Qt.CursorShape.ArrowCursor)
            elif isinstance(watched, QAbstractItemView):
                watched.viewport().setCursor(Qt.CursorShape.PointingHandCursor if watched.isEnabled() else Qt.CursorShape.ArrowCursor)
            elif isinstance(watched, QMenu):
                watched.setMouseTracking(True)
        elif event.type() in (QEvent.Type.MouseMove, QEvent.Type.Enter):
            if isinstance(watched, QMenu):
                action = watched.actionAt(event.position().toPoint())
                clickable = action is not None and action.isEnabled() and not action.isSeparator()
                watched.setCursor(Qt.CursorShape.PointingHandCursor if clickable else Qt.CursorShape.ArrowCursor)
        return super().eventFilter(watched, event)


def install_pointer_cursors(app) -> None:
    if not hasattr(app, '_outward_pointer_cursors'):
        app._outward_pointer_cursors = PointerCursors(app)
        app.installEventFilter(app._outward_pointer_cursors)


class StatusCaption(QLabel):
    def setText(self, text: str) -> None:
        super().setText(text)
        self.setVisible(bool(text))


class ElidedLabel(QLabel):
    """Keep the full accessible text without imposing its width on a layout."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(text)

    def setText(self, text: str) -> None:
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.contentsRect().width())
        self.style().drawItemText(painter, self.contentsRect(), self.alignment(), self.palette(),
                                  self.isEnabled(), text, QPalette.ColorRole.WindowText)


class CurrentPageLayout(QStackedLayout):
    """Qt queries layout height-for-width directly, so exclude hidden pages here."""

    def sizeHint(self) -> QSize:
        page = self.currentWidget()
        return page.sizeHint() if page is not None else QSize(0, 0)

    def minimumSize(self) -> QSize:
        page = self.currentWidget()
        return page.minimumSizeHint().expandedTo(page.minimumSize()) if page is not None else QSize(0, 0)

    def hasHeightForWidth(self) -> bool:
        page = self.currentWidget()
        return page.hasHeightForWidth() if page is not None else False

    def heightForWidth(self, width: int) -> int:
        page = self.currentWidget()
        return page.heightForWidth(width) if page is not None else -1


class CurrentPageStack(QWidget):
    """A tall inactive settings page must not force other pages to scroll."""

    currentChanged = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pages = CurrentPageLayout(self)
        self._pages.currentChanged.connect(self.currentChanged.emit)
        self.currentChanged.connect(lambda _index: self.updateGeometry())

    def addWidget(self, widget: QWidget) -> int:
        return self._pages.addWidget(widget)

    def setCurrentIndex(self, index: int) -> None:
        self._pages.setCurrentIndex(index)

    def currentIndex(self) -> int:
        return self._pages.currentIndex()

    def currentWidget(self) -> QWidget | None:
        return self._pages.currentWidget()
