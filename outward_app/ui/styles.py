from string import Template

from outward_app.ui.themes import theme_colors


_APP_TEMPLATE = """
* {
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 13px;
    letter-spacing: 0px;
}
QWidget {
    background: $canvas;
    color: $text;
}
QMainWindow, QWidget#appRoot {
    background: $canvas;
}
QDialog {
    background: transparent;
}
QLabel {
    background: transparent;
    color: $text;
}
QFrame#sidebar {
    background: $sidebar;
    border-right: 1px solid $border;
}
QWidget#content, QScrollArea#contentScroll, QScrollArea#contentScroll > QWidget {
    background: $canvas;
    border: none;
}
QLabel#sidebarLogo {
    border: none;
    border-radius: 6px;
    background: transparent;
    padding: 0;
}
QLabel#heroLogo {
    border: none;
    border-radius: 24px;
    background: transparent;
    padding: 0;
}
QLabel#brandTitle {
    font-size: 16px;
    font-weight: 700;
    color: $text;
}
QLabel#brandSubtitle {
    font-size: 10px;
    font-weight: 700;
    color: $accent;
}
QLabel#sectionTitle, QLabel#metricTitle {
    color: $muted;
    font-size: 11px;
    font-weight: 600;
}
QLabel#statusTitle {
    font-size: 16px;
    font-weight: 700;
    color: $text;
}
QLabel#statusDot {
    color: $warning;
    font-size: 15px;
    font-weight: 900;
}
QLabel#statusDot[connected="true"] {
    color: $success;
}
QLabel#statusDot[connected="pending"] {
    color: $accent;
}
QLabel#statusDot[connected="error"] {
    color: $error;
}
QLabel#mutedLabel, QLabel#footerLabel, QLabel#profileSummary {
    color: $muted;
}
QLabel#footerLabel {
    color: $muted;
    padding: 0;
}
QLabel#statusMetricValue {
    color: $accent;
    font-size: 13px;
    font-weight: 700;
}
QLabel#metricValue {
    color: $accent;
    font-size: 16px;
    font-weight: 700;
}
QFrame#statusPanel, QFrame#metricCard, QFrame#settingsCard, QFrame#updatePanel, QFrame#profileDialogPanel {
    background: $panel;
    border: 1px solid $border;
    border-radius: 8px;
}
QFrame#statusPanel {
    min-height: 78px;
}
QFrame#metricCard {
    min-height: 56px;
}
QFrame#settingsCard {
    min-height: 250px;
}
QFrame#updatePanel {
    min-height: 62px;
}
QFrame#profileDialogPanel {
    background: $panel;
    border-color: $control_border;
}
QFrame#inlineSwitch, QFrame#connectionTools, QFrame#statusActions, QFrame#emptyProfiles {
    background: transparent;
    border: none;
}
QFrame#launchTarget {
    background: $panel;
    border: 1px solid $border;
    border-radius: 4px;
    min-height: 34px;
    max-height: 34px;
}
QLabel#tinyLabel {
    color: $muted;
    font-size: 11px;
}
QLabel#settingsHeading, QLabel#settingsHeadingAccent {
    color: $accent;
    font-size: 15px;
    font-weight: 700;
}
QLabel#settingLabel, QLabel#fieldLabel {
    color: $text;
    font-weight: 600;
}
QListWidget {
    background: transparent;
    border: none;
    outline: none;
}
QListWidget::item {
    min-height: 48px;
    padding: 0;
    border: none;
    background: transparent;
}
QListWidget::item:selected {
    border: none;
    background: transparent;
}
QListWidget::item:hover {
    background: transparent;
}
QListWidget#launchSiteList {
    background: $input;
    border: 1px solid $control_border;
    border-radius: 4px;
    padding: 6px;
}
QListWidget#launchSiteList::item {
    min-height: 36px;
    padding: 7px 10px;
    border-radius: 4px;
    background: transparent;
    color: $text;
}
QListWidget#launchSiteList::item:selected {
    background: $selection;
    color: $text;
}
QListWidget#launchSiteList::item:hover {
    background: $hover;
}
QWidget#autoConnectSettings {
    background: transparent;
}
QListWidget#autoConnectList {
    background: $input;
    border: 1px solid $border;
    border-radius: 4px;
    padding: 3px;
}
QListWidget#autoConnectList:focus {
    border-color: $accent;
}
QListWidget#autoConnectList::item {
    min-height: 28px;
    color: $text;
}
QListWidget#autoConnectList::item:hover, QListWidget#autoConnectList::item:focus {
    background: $selection;
}
QListWidget#autoConnectList::item:disabled {
    color: $muted;
}
QFrame#profileRow {
    background: transparent;
    border: none;
    border-radius: 4px;
}
QFrame#profileRow[selected="true"] {
    background: $selection;
}
QFrame#profileAccent {
    background: transparent;
    border-radius: 2px;
}
QFrame#profileRow[selected="true"] QFrame#profileAccent {
    background: $accent;
}
QLabel#profileCountryBadge {
    background: $raised;
    border: 1px solid $border;
    border-radius: 4px;
    color: $text;
    font-size: 10px;
    font-weight: 700;
}
QLabel#profileName {
    color: $muted;
    font-weight: 500;
}
QFrame#profileRow[selected="true"] QLabel#profileName {
    color: $text;
    font-weight: 700;
}
QLabel#profileProtocol {
    color: $muted;
    font-size: 10px;
    font-weight: 700;
}
QFrame#profileRow[selected="true"] QLabel#profileProtocol {
    color: $accent;
}
QPlainTextEdit, QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background: $input;
    border: 1px solid $control_border;
    border-radius: 4px;
    padding: 8px 10px;
    color: $text;
    selection-background-color: $selection_text_bg;
    selection-color: $selection_text;
    placeholder-text-color: $muted;
}
QPlainTextEdit {
    font-family: Cascadia Mono, Consolas, monospace;
    color: $muted;
    line-height: 1.25;
}
QPlainTextEdit#logConsole {
    background: $input;
    border-color: $border;
    border-radius: 8px;
    padding: 14px;
}
QLineEdit#flatLineEdit {
    background: transparent;
    border: none;
    padding: 8px 10px;
}
QFrame#inputShell {
    background: $input;
    border: 1px solid $control_border;
    border-radius: 4px;
    min-height: 34px;
}
QFrame#inputShell[invalid="true"] {
    border-color: $error;
}
QPushButton#protocolPill {
    background: $raised;
    border: 1px solid $control_border;
    color: $muted;
    border-radius: 14px;
    padding: 6px 8px;
    font-size: 11px;
}
QPushButton#protocolPill:checked {
    background: $primary;
    color: $on_primary;
    border-color: $primary;
}
QPushButton#protocolPill:disabled {
    color: $disabled_text;
    border-color: $border;
}
QLabel#detectedProtocol {
    background: $selection;
    color: $accent;
    border: 1px solid $control_border;
    border-radius: 4px;
    padding: 6px 10px;
    font-size: 11px;
    font-weight: 700;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {
    width: 26px;
    border: none;
    background: transparent;
}
QComboBox QAbstractItemView {
    background: $raised;
    border: 1px solid $border;
    border-radius: 4px;
    color: $text;
    selection-background-color: $selection;
    outline: none;
}
QPushButton {
    background: $raised;
    border: 1px solid $control_border;
    border-radius: 4px;
    padding: 8px 14px;
    color: $text;
    font-weight: 700;
}
QPushButton:hover {
    background: $hover;
    border-color: $focus;
}
QPushButton:pressed {
    background: $pressed;
}
QPushButton:focus, QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: $accent;
}
QPushButton:disabled {
    color: $disabled_text;
    background: $disabled_bg;
    border-color: $border;
}
QPushButton#primaryButton, QPushButton#primaryButtonWide, QPushButton#addProfileButton {
    background: $primary;
    border-color: $primary;
    color: $on_primary;
}
QPushButton#primaryButton:hover, QPushButton#primaryButtonWide:hover, QPushButton#addProfileButton:hover {
    background: $primary_hover;
    border-color: $primary_hover;
}
QPushButton#primaryButtonWide {
    min-height: 36px;
}
QPushButton#primaryButton:disabled, QPushButton#primaryButtonWide:disabled {
    color: $disabled_text;
    background: $disabled_bg;
    border-color: $border;
}
QPushButton#ghostButton {
    background: transparent;
    border-color: transparent;
    color: $muted;
}
QPushButton#outlineButton {
    background: transparent;
    border-color: $accent;
    color: $accent;
}
QPushButton#successButton {
    background: $primary;
    border-color: $primary;
    color: $on_primary;
}
QPushButton#successButton:hover {
    background: $primary_hover;
    border-color: $primary_hover;
}
QPushButton#successButton:pressed {
    background: $primary_pressed;
    border-color: $primary_pressed;
}
QPushButton#dangerButton {
    background: $danger_bg;
    border-color: $danger_bg;
    color: $on_danger;
}
QPushButton#dangerButton:hover {
    background: $danger_hover;
    border-color: $danger_hover;
}
QPushButton#dangerButton:pressed {
    background: $danger_pressed;
    border-color: $danger_pressed;
}
QPushButton#iconButton {
    background: transparent;
    border-color: transparent;
    color: $muted;
    padding: 0;
    font-size: 16px;
}
QPushButton#profileMenuButton {
    background: transparent;
    border: 1px solid transparent;
    color: $muted;
    padding: 0;
    font-size: 18px;
}
QPushButton#profileMenuButton:hover, QPushButton#profileMenuButton:focus {
    background: $hover;
    border-color: $accent;
    color: $text;
}
QPushButton#pasteButton {
    background: $selection;
    border-color: $control_border;
    color: $accent;
    padding: 0;
    font-size: 15px;
}
QPushButton#launchManageButton {
    background: $panel;
    border: 1px solid $border;
    border-radius: 4px;
    color: $text;
    padding: 0;
    font-size: 18px;
    font-weight: 700;
}
QPushButton#launchManageButton:hover {
    background: $hover;
    border-color: $focus;
}
QLabel#dialogBadge {
    min-width: 28px;
    min-height: 28px;
    border-radius: 4px;
    background: $selection;
    color: $accent;
    font-size: 22px;
    font-weight: 600;
}
QLabel#dialogTitle {
    color: $text;
    font-size: 20px;
    font-weight: 700;
}
QFrame#pivotTabs {
    background: transparent;
    border: none;
}
QPushButton#pivotTab {
    background: transparent;
    border: none;
    border-radius: 0;
    color: $muted;
    padding: 8px 0 7px 0;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#pivotTab:hover {
    color: $text;
    background: transparent;
}
QPushButton#pivotTab[selected="true"] {
    color: $text;
    border-bottom: 2px solid $accent;
}
QWidget#contentStack {
    background: transparent;
    border: none;
}
QWidget#settingsTabPage, QWidget#logsTabPage, QWidget#updateTabPage {
    background: $canvas;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
    border: none;
}
QScrollBar::handle:vertical {
    background: $scrollbar;
    border-radius: 4px;
    min-height: 48px;
}
QScrollBar::handle:vertical:hover {
    background: $scrollbar_hover;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    width: 0;
    height: 0;
    border: none;
    background: transparent;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
    border: none;
}
QScrollBar:horizontal {
    height: 0;
    background: transparent;
}
QScrollBar::handle:horizontal, QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
    border: none;
}

QFrame#dialogOverlay {
    background: $overlay;
    border: none;
}
QComboBox#launchCombo {
    background: $panel;
    border: none;
    padding: 5px 8px;
    color: $text;
    font-weight: 700;
}
QComboBox#launchCombo QLineEdit {
    background: transparent;
    border: none;
    padding: 0;
    color: $text;
    font-weight: 700;
}
QLabel#launchHint {
    color: $muted;
    font-size: 10px;
}
QLabel#launchChevron {
    color: $muted;
    font-size: 10px;
    font-weight: 700;
}
QTextEdit#logConsole {
    background: $input;
    border: 1px solid $border;
    border-radius: 6px;
    padding: 14px;
}
"""




_CONNECTIONS_TEMPLATE = """
QWidget#settingsRoute { background: $canvas; }
QPushButton#sideAddButton, QPushButton#sideSettingsButton {
    background: $raised;
    color: $muted;
    border: 1px solid transparent;
    text-align: left;
    padding: 8px 12px;
}
QPushButton#sideAddButton:hover, QPushButton#sideSettingsButton:hover { background: $border; color: $text; }
QPushButton#sideSettingsButton[selected="true"] {
    background: $selection;
    border-color: $border;
    color: $accent;
}
QFrame#connectionCard {
    background: $panel;
    border: 1px solid $border;
    border-radius: 8px;
}
QWidget#connectionsDashboard, QWidget#windowsList,
QScrollArea#windowsScroll, QScrollArea#windowsScroll > QWidget,
QScrollArea#legacyToolsScroll, QScrollArea#legacyToolsScroll > QWidget {
    background: $canvas;
    border: none;
}
QPushButton#connectionProfile {
    color: $accent;
    background: transparent;
    border: none;
    text-align: left;
    padding: 0;
    font-size: 11px;
}
QPushButton#connectionProfile:hover { color: $text; }
QPushButton#connectionProfile:focus { border: 1px dotted $accent; }
QLabel#connectionMetadata { color: $muted; font-size: 11px; }
QLabel#connectionPorts { color: $text; font-size: 13px; }
QLabel#connectionState { color: $muted; font-size: 13px; }
QLabel#connectionState[active="true"] { color: $success; }
QWidget#connectionAutoGroup { background: transparent; }
QFrame#connectionCard QComboBox#launchCombo {
    background: $raised;
    border: 1px solid $border;
    border-radius: 4px;
    padding: 6px 28px 6px 10px;
    min-height: 20px;
}
QLabel#connectionMessage { color: $warning; font-size: 12px; }
QLabel#connectionMessage[error="true"] { color: $error; }
QFrame#connectionDivider { background: $border; border: none; }
QFrame#connectionCard QLabel#connectionPorts { font-size: 12px; }
QFrame#connectionCard QLabel#connectionMetadata { font-size: 12px; }
QFrame#connectionCard QPushButton#connectionProfile { font-size: 12px; }
QFrame#connectionCard QLabel#launchHint { font-size: 12px; color: $muted; }
QPushButton#connectionPower {
    background: transparent;
    border: 1px solid $border;
    outline: none;
    border-radius: 6px;
    padding: 0;
}
QPushButton#connectionPower:hover { background: $raised; border-color: $control_border; }
QPushButton#connectionPower:pressed { background: $pressed; }
QPushButton#connectionPower:focus[keyboardFocus="true"] { border: 1px solid $accent; }
QFrame#statusPanel QLabel#systemMetricValue {
    color: $text;
    font-size: 14px;
    font-weight: 600;
}
QFrame#statusPanel QPushButton#connectionProfile,
QFrame#statusPanel QPushButton#connectionProfile:disabled {
    color: $text;
    font-size: 14px;
    font-weight: 600;
}
QLabel#systemProtocol { color: $muted; font-size: 12px; }
QPushButton#systemModeOption {
    background: $input;
    color: $muted;
    border: 1px solid $control_border;
    border-radius: 0;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#systemModeOption[edge="left"] { border-top-left-radius: 4px; border-bottom-left-radius: 4px; }
QPushButton#systemModeOption[edge="right"] { border-top-right-radius: 4px; border-bottom-right-radius: 4px; }
QPushButton#systemModeOption:hover { background: $hover; color: $text; }
QPushButton#systemModeOption:checked { background: $raised; color: $text; border-color: $accent; }
QPushButton#systemModeOption:pressed { background: $pressed; }
QPushButton#systemModeOption:disabled { color: $disabled_text; border-color: $border; }
QPushButton#systemModeOption:checked:disabled { color: $muted; }
QPushButton#systemModeOption:focus { border: 1px solid $focus; }
QFrame#statusPanel QPushButton#connectionPower[connected="true"] {
    background: $success_surface;
    border-color: $success;
}
QFrame#statusPanel QPushButton#connectionPower[connected="true"]:hover { background: $hover; }
QFrame#statusPanel QPushButton#connectionPower[connected="true"]:pressed { background: $pressed; }
QFrame#statusPanel QPushButton#connectionPower[connected="true"]:focus[keyboardFocus="true"] {
    border-color: $accent;
}
QSplitter::handle:vertical { background: $border; height: 4px; }
"""


_EXTRA_TEMPLATE = """
QListView#singleSelectPopup {
    background: $raised;
    color: $text;
    border: 1px solid $control_border;
    padding: 4px;
    outline: none;
}
QListView#singleSelectPopup::item {
    min-height: 28px;
    padding: 0 8px;
    border-radius: 4px;
}
QListView#singleSelectPopup::item:selected {
    background: $selection;
    color: $text;
}
QListView#singleSelectPopup::item:hover { background: $hover; }
QPushButton#primaryButton:pressed, QPushButton#primaryButtonWide:pressed,
QPushButton#addProfileButton:pressed {
    background: $primary_pressed;
    border-color: $primary_pressed;
}
QPushButton#successButton:disabled, QPushButton#dangerButton:disabled,
QPushButton#addProfileButton:disabled {
    background: $disabled_bg;
    border-color: $border;
    color: $disabled_text;
}
QPushButton#outlineButton:hover, QPushButton#ghostButton:hover,
QPushButton#iconButton:hover, QPushButton#pasteButton:hover {
    background: $hover;
    color: $text;
    border-color: $control_border;
}
QPushButton#outlineButton:pressed, QPushButton#ghostButton:pressed {
    background: $pressed;
}
QPushButton#outlineButton:disabled, QPushButton#connectionProfile:disabled {
    color: $disabled_text;
    border-color: transparent;
}
QPushButton#connectionProfile:disabled {
    background: transparent;
}
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled, QTextEdit:disabled {
    color: $disabled_text;
    background: $disabled_bg;
    border-color: $border;
}
QMenu, QToolTip {
    background: $raised;
    color: $text;
    border: 1px solid $control_border;
    padding: 4px;
}
QMenu::item {
    background: transparent;
    padding: 6px 24px;
}
QMenu::item:selected { background: $selection; color: $text; }
QMenu::item:disabled { color: $disabled_text; }
QMenu::separator { height: 1px; background: $border; margin: 4px 6px; }
QListWidget#autoConnectList::indicator { width: 14px; height: 14px; }
QWidget#themeSelector { background: transparent; }
QPushButton#themeOption {
    background: $input;
    color: $muted;
    border: 1px solid $control_border;
    padding: 5px 8px;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#themeOption:hover { background: $hover; color: $text; }
QPushButton#themeOption:checked {
    background: $primary;
    color: $on_primary;
    border-color: $primary;
}
QPushButton#themeOption:focus { border: 1px dotted $focus; }
QPushButton#themeOption:checked:focus, QPushButton#protocolPill:checked:focus,
QPushButton#primaryButton:focus, QPushButton#primaryButtonWide:focus,
QPushButton#successButton:focus, QPushButton#addProfileButton:focus {
    border: 1px dotted $on_primary;
}
"""


def build_styles(name: str = "dark") -> str:
    return Template(_APP_TEMPLATE + _CONNECTIONS_TEMPLATE + _EXTRA_TEMPLATE).substitute(theme_colors(name))


# Compatibility for consumers that need a static default stylesheet.
APP_STYLE = build_styles("dark")
