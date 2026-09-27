APP_STYLE = """
* {
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 13px;
    letter-spacing: 0px;
}
QWidget {
    background: #11111d;
    color: #f4f1ff;
}
QMainWindow, QWidget#appRoot {
    background: #11111d;
}
QDialog {
    background: transparent;
}
QLabel {
    background: transparent;
    color: #f6f3ff;
}
QFrame#sidebar {
    background: #0c0c16;
    border-right: 1px solid #202033;
}
QWidget#content, QScrollArea#contentScroll, QScrollArea#contentScroll > QWidget {
    background: #1a1a2c;
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
    color: #ffffff;
}
QLabel#brandSubtitle {
    font-size: 10px;
    font-weight: 700;
    color: #9B59FF;
}
QLabel#sectionTitle, QLabel#metricTitle {
    color: #82889d;
    font-size: 11px;
    font-weight: 600;
}
QLabel#statusTitle {
    font-size: 16px;
    font-weight: 700;
    color: #ffffff;
}
QLabel#statusDot {
    color: #ffbf32;
    font-size: 15px;
    font-weight: 900;
}
QLabel#statusDot[connected="true"] {
    color: #26d98a;
}
QLabel#statusDot[connected="pending"] {
    color: #9B59FF;
}
QLabel#mutedLabel, QLabel#footerLabel, QLabel#profileSummary {
    color: #9198ad;
}
QLabel#footerLabel {
    color: #666d82;
    padding: 0;
}
QLabel#statusMetricValue {
    color: #9B59FF;
    font-size: 13px;
    font-weight: 700;
}
QLabel#metricValue {
    color: #9B59FF;
    font-size: 16px;
    font-weight: 700;
}
QFrame#statusPanel, QFrame#metricCard, QFrame#settingsCard, QFrame#updatePanel, QFrame#profileDialogPanel {
    background: #303050;
    border: 1px solid #47456f;
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
    background: #303050;
    border-color: #6e48b7;
}
QFrame#inlineSwitch, QFrame#connectionTools {
    background: transparent;
    border: none;
}
QFrame#launchTarget {
    background: #303050;
    border: 1px solid rgba(255, 255, 255, 15);
    border-radius: 4px;
    min-height: 34px;
    max-height: 34px;
}
QLabel#tinyLabel {
    color: #94A3B8;
    font-size: 11px;
}
QLabel#settingsHeading, QLabel#settingsHeadingAccent {
    color: #9B59FF;
    font-size: 15px;
    font-weight: 700;
}
QLabel#settingLabel, QLabel#fieldLabel {
    color: #ffffff;
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
    background: #252543;
    border: 1px solid #403f66;
    border-radius: 4px;
    padding: 6px;
}
QListWidget#launchSiteList::item {
    min-height: 36px;
    padding: 7px 10px;
    border-radius: 4px;
    background: transparent;
    color: #f4f1ff;
}
QListWidget#launchSiteList::item:selected {
    background: #3a315b;
    color: #ffffff;
}
QListWidget#launchSiteList::item:hover {
    background: #302d4f;
}
QFrame#profileRow {
    background: transparent;
    border: none;
    border-radius: 4px;
}
QFrame#profileRow[selected="true"] {
    background: rgba(155, 89, 255, 16);
}
QFrame#profileAccent {
    background: transparent;
    border-radius: 2px;
}
QFrame#profileRow[selected="true"] QFrame#profileAccent {
    background: #9B59FF;
}
QLabel#profileCountryBadge {
    background: rgba(255, 255, 255, 12);
    border: 1px solid rgba(255, 255, 255, 20);
    border-radius: 4px;
    color: #F8FAFC;
    font-size: 10px;
    font-weight: 700;
}
QLabel#profileName {
    color: #8f96a8;
    font-weight: 500;
}
QFrame#profileRow[selected="true"] QLabel#profileName {
    color: #ffffff;
    font-weight: 700;
}
QLabel#profileProtocol {
    color: #60687b;
    font-size: 10px;
    font-weight: 700;
}
QFrame#profileRow[selected="true"] QLabel#profileProtocol {
    color: #b98cff;
}
QPlainTextEdit, QLineEdit, QTextEdit, QSpinBox, QComboBox {
    background: #111120;
    border: 1px solid #25253a;
    border-radius: 4px;
    padding: 8px 10px;
    color: #f8f4ff;
    selection-background-color: #9B59FF;
}
QPlainTextEdit {
    font-family: Cascadia Mono, Consolas, monospace;
    color: #9da4b8;
    line-height: 1.25;
}
QPlainTextEdit#logConsole {
    background: #10101e;
    border-color: #18182a;
    border-radius: 8px;
    padding: 14px;
}
QLineEdit#flatLineEdit {
    background: transparent;
    border: none;
    padding: 8px 10px;
}
QFrame#inputShell {
    background: #111120;
    border: 1px solid #25253a;
    border-radius: 4px;
    min-height: 34px;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button {
    width: 26px;
    border: none;
    background: transparent;
}
QComboBox QAbstractItemView {
    background: #0A0B14;
    border: 1px solid rgba(255, 255, 255, 15);
    border-radius: 4px;
    color: #F8FAFC;
    selection-background-color: rgba(155, 89, 255, 32);
    outline: none;
}
QPushButton {
    background: #202033;
    border: 1px solid #2b2b42;
    border-radius: 4px;
    padding: 8px 14px;
    color: #f6f2ff;
    font-weight: 700;
}
QPushButton:hover {
    background: #282842;
    border-color: #7f54d9;
}
QPushButton:pressed {
    background: #181828;
}
QPushButton:disabled {
    color: #70778c;
    background: #171725;
    border-color: #222236;
}
QPushButton#primaryButton, QPushButton#primaryButtonWide, QPushButton#addProfileButton, QPushButton#sideAddButton {
    background: #9B59FF;
    border-color: #9B59FF;
    color: #ffffff;
}
QPushButton#primaryButton:hover, QPushButton#primaryButtonWide:hover, QPushButton#addProfileButton:hover, QPushButton#sideAddButton:hover {
    background: #b975ff;
    border-color: #b975ff;
}
QPushButton#primaryButtonWide {
    min-height: 36px;
}
QPushButton#sideAddButton {
    text-align: left;
    background: #151521;
    border-color: #151521;
    color: #9da4b8;
    padding-left: 12px;
}
QPushButton#ghostButton {
    background: transparent;
    border-color: transparent;
    color: #bdc3d2;
}
QPushButton#outlineButton {
    background: transparent;
    border-color: #9B59FF;
    color: #bd86ff;
}
QPushButton#successButton {
    background: #1f9d62;
    border-color: #1f9d62;
    color: #ffffff;
}
QPushButton#successButton:hover {
    background: #27b874;
    border-color: #27b874;
}
QPushButton#successButton:pressed {
    background: #187f4f;
    border-color: #187f4f;
}
QPushButton#dangerButton {
    background: #d14343;
    border-color: #d14343;
    color: #ffffff;
}
QPushButton#dangerButton:hover {
    background: #e05252;
    border-color: #e05252;
}
QPushButton#dangerButton:pressed {
    background: #a93232;
    border-color: #a93232;
}
QPushButton#iconButton {
    background: transparent;
    border-color: transparent;
    color: #aeb4c8;
    padding: 0;
    font-size: 16px;
}
QPushButton#pasteButton {
    background: #241b43;
    border-color: #3f2a75;
    color: #b781ff;
    padding: 0;
    font-size: 15px;
}
QPushButton#launchManageButton {
    background: #303050;
    border: 1px solid rgba(255, 255, 255, 15);
    border-radius: 4px;
    color: #ffffff;
    padding: 0;
    font-size: 18px;
    font-weight: 700;
}
QPushButton#launchManageButton:hover {
    background: #3a3a60;
    border-color: #7f54d9;
}
QPushButton#protocolPill {
    background: #181829;
    border: 1px solid #26263b;
    color: #9ca3b8;
    border-radius: 14px;
    padding: 6px 8px;
    font-size: 11px;
}
QPushButton#protocolPill:checked {
    background: #9B59FF;
    color: #ffffff;
    border-color: #9B59FF;
}
QPushButton#protocolPill:disabled {
    color: #73798b;
    border-color: #202033;
}
QLabel#dialogBadge {
    min-width: 28px;
    min-height: 28px;
    border-radius: 4px;
    background: #47257a;
    color: #c697ff;
    font-size: 22px;
    font-weight: 600;
}
QLabel#dialogTitle {
    color: #ffffff;
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
    color: #6f778c;
    padding: 8px 0 7px 0;
    font-size: 13px;
    font-weight: 600;
}
QPushButton#pivotTab:hover {
    color: #d4d8e6;
    background: transparent;
}
QPushButton#pivotTab[selected="true"] {
    color: #F8FAFC;
    border-bottom: 2px solid #9B59FF;
}
QStackedWidget#contentStack {
    background: transparent;
    border: none;
}
QWidget#settingsTabPage, QWidget#logsTabPage, QWidget#updateTabPage {
    background: #1a1a2c;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
    border: none;
}
QScrollBar::handle:vertical {
    background: #44405f;
    border-radius: 4px;
    min-height: 48px;
}
QScrollBar::handle:vertical:hover {
    background: #585276;
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
    background: rgba(0, 0, 0, 128);
    border: none;
}
QComboBox#launchCombo {
    background: #303050;
    border: none;
    padding: 5px 8px;
    color: #ffffff;
    font-weight: 700;
}
QComboBox#launchCombo QLineEdit {
    background: transparent;
    border: none;
    padding: 0;
    color: #ffffff;
    font-weight: 700;
}
QLabel#launchHint {
    color: #8f96aa;
    font-size: 10px;
}
QLabel#launchChevron {
    color: #94A3B8;
    font-size: 10px;
    font-weight: 700;
}
QTextEdit#logConsole {
    background: #10101e;
    border: 1px solid #18182a;
    border-radius: 6px;
    padding: 14px;
}
"""


