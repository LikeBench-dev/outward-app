from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPalette, QPen
from PySide6.QtWidgets import QAbstractButton, QAbstractItemView, QAbstractSpinBox, QButtonGroup, QComboBox, QHBoxLayout, QLabel, QListView, QMenu, QPushButton, QScrollBar, QSizePolicy, QStackedLayout, QWidget
from outward_app.ui.i18n import tr
from outward_app.ui.themes import theme_color


class SelectCombo(QComboBox):
    """Single selection with a visible chevron and no accidental wheel changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        view = QListView(self)
        view.setObjectName('singleSelectPopup')
        view.setUniformItemSizes(True)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setView(view)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(theme_color('muted' if self.isEnabled() else 'disabled_text'))
        x, y = self.width() - 15, self.height() // 2
        painter.drawLine(x - 3, y - 1, x, y + 2)
        painter.drawLine(x, y + 2, x + 3, y - 1)
        painter.end()

    def wheelEvent(self, event):
        event.ignore()


def _paint_plus(widget, color_role) -> None:
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(widget.palette().color(color_role), 1.8,
                        Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    center = QRectF(widget.rect()).center()
    x, y = center.x(), center.y()
    painter.drawLine(QPointF(x - 4, y), QPointF(x + 4, y))
    painter.drawLine(QPointF(x, y - 4), QPointF(x, y + 4))


class PlusButton(QPushButton):
    """Keep the add glyph centered independently of font and DPI metrics."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        _paint_plus(self, QPalette.ColorRole.ButtonText)


class CloseButton(QPushButton):
    """Keep the close glyph centered independently of font and DPI metrics."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.ButtonText), 1.5,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        center = QRectF(self.rect()).center()
        x, y = center.x(), center.y()
        painter.drawLine(QPointF(x - 3, y - 3), QPointF(x + 3, y + 3))
        painter.drawLine(QPointF(x - 3, y + 3), QPointF(x + 3, y - 3))


class PlusBadge(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName('dialogBadge')
        self.setFixedSize(28, 28)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        _paint_plus(self, QPalette.ColorRole.WindowText)


class MenuButton(QPushButton):
    """Paint dots from the current palette instead of caching a colored icon."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.ButtonText))
        center = QRectF(self.rect()).center()
        for offset in (-5, 0, 5):
            painter.drawEllipse(QRectF(center.x() + offset - 1, center.y() - 1, 2, 2))


class ThemeSelector(QWidget):
    theme_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("themeSelector")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for name, label in (("light", tr('Светлая')), ("dark", tr('Тёмная'))):
            button = QPushButton(label)
            button.setObjectName("themeOption")
            button.setCheckable(True)
            button.setAccessibleName(label + tr(' тема'))
            button.setAccessibleDescription(tr('Применяется сразу и сохраняется автоматически'))
            button.clicked.connect(lambda _checked=False, value=name: self.theme_selected.emit(value))
            self.group.addButton(button)
            self.buttons[name] = button
            layout.addWidget(button)
        self.setFixedWidth(168)
        self.set_theme("dark")

    def set_theme(self, name: str) -> None:
        self.buttons[name].setChecked(True)


class PointerCursors(QObject):
    """Apply the app's pointer convention to controls, including popup menus."""

    def eventFilter(self, watched, event) -> bool:
        if event.type() in (QEvent.Type.Polish, QEvent.Type.EnabledChange, QEvent.Type.Show):
            if isinstance(watched, (QAbstractButton, QAbstractSpinBox, QComboBox, QScrollBar)):
                pointer = watched.isEnabled() and not watched.property('nativeCaptionButton')
                watched.setCursor(Qt.CursorShape.PointingHandCursor if pointer else Qt.CursorShape.ArrowCursor)
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
