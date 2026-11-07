---
name: Outward App
description: Graphite light and dark Windows desktop design system.
colors:
  app-bg: "#101010"
  sidebar-bg: "#141414"
  content-bg: "#101010"
  panel-bg: "#1D1D1D"
  panel-border: "#363636"
  control-border: "#707070"
  input-bg: "#171717"
  primary: "#E6E6E6"
  primary-hover: "#FFFFFF"
  on-primary: "#101010"
  fluent-accent: "#D5D5D5"
  text: "#ECECEC"
  muted: "#A8A8A8"
  connected: "#58D59B"
  disconnected: "#E9B949"
  error: "#FF8F8F"
  danger: "#B42318"
light-colors:
  app-bg: "#F5F5F4"
  sidebar-bg: "#EBEBE9"
  panel-bg: "#FFFFFF"
  panel-border: "#D6D6D2"
  control-border: "#85857F"
  input-bg: "#FAFAFA"
  primary: "#333333"
  on-primary: "#FFFFFF"
  text: "#202020"
  muted: "#62625E"
  connected: "#167749"
  disconnected: "#8A5A00"
  error: "#B42318"
typography:
  body:
    fontFamily: "Segoe UI, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  title:
    fontFamily: "Segoe UI, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 700
  dialog-title:
    fontFamily: "Segoe UI, Arial, sans-serif"
    fontSize: "20px"
    fontWeight: 700
rounded:
  control: "4px"
  panel: "8px"
spacing:
  inline: "8px"
  actions: "12px"
  groups: "14px"
  panel: "16px"
  dialog: "24px"
---

## Overview

Preserve the approved Graphite Windows desktop interface: neutral light/dark surfaces, restrained borders and monochrome actions. Both themes are first-class; dark is the default for new and legacy settings. This document records implementation decisions rather than claiming complete accessibility certification.

Sources: `outward_app/ui/themes.py` (semantic palettes and ThemeManager), `ui/styles.py` (theme-generated QSS and default `APP_STYLE`), `ui/main_window.py` (theme selection, custom controls and rich-text journal), `ui/widgets.py` (palette-aware plus/menu glyphs and ThemeSelector), `ui/connection_card.py` (connection painters), `ui/dialogs.py` (forms), and `ui/window_chrome.py` (native window integration). Paths starting with `ui/` are relative to `outward_app/`.

## Colors

The connection power button shows a thin solid focus border for Tab/Shift+Tab navigation; mouse clicks leave no focus border. Preserve its hover and pressed feedback.

Use semantic roles from `THEME_COLORS`; never add raw interface colors to QSS, painters or rich text. Primary actions are light with dark text in dark mode, charcoal with white text in light mode. Selection, focus and pending progress use neutral contrast. Green is reserved for connection/success state; amber for warnings/offline system status; red for errors/destructive actions. State also has tooltips, accessible text or changed controls. Country flags and the app logo retain their asset colors; the neutral globe works against both themes.

`build_styles(theme)` resolves palette roles into QSS. ThemeManager synchronizes QPalette, optional Fluent controls and QSS before notifying existing widgets. Distinguish quiet separators from stronger control boundaries. Placeholder text uses the muted role; selected primary controls use a contrasting dotted focus border. Validate hover, pressed, selected, loading, error and disabled states in both themes.

The theme selector is the first General setting, with explicit «Светлая / Тёмная» buttons. It applies immediately and writes only the theme field through the atomic store, without committing form drafts or applying ports/startup configuration. An absent/invalid stored theme resolves to dark. General settings saves retain it. A failed theme write restores the previous selector and appearance. Apply the stored palette before building/showing the main content. Existing sessions and widgets remain alive; journal HTML is regenerated with the same text selection and scroll position. New widgets inherit the current palette.

## Typography

Keep Segoe UI and its existing fallbacks. Body text is 13px; section and metric captions use 11px; status and brand titles use 16px/700; dialog titles use 20px/700. Log styles declare Cascadia Mono/Consolas for `QPlainTextEdit`; the current log widget is `QTextEdit`, so verify its effective font instead of assuming that selector applies.

The UI supports Russian (default) and English through `ui/i18n.py`. Translate source templates before inserting profile names, URLs and other user content; preserve protocol names and original engine diagnostics. Allow Cyrillic and long profile names in either language.

General settings place a compact single-select language dropdown directly below appearance. Its two options always read «Русский» and «English». Reuse the shared `SelectCombo` chevron, keyboard behavior and wheel protection in both themes. Language saves independently of unfinished network settings and applies after restart; the row explains this without interrupting the user. A failed write restores the previous choice. Do not restart or recreate sessions when selecting a language.

## Layout

The system card has a compact two-segment TUN / «Системный прокси» control on its own row between header and metrics, aligned left without explanatory text on the right. Selected mode uses neutral theme roles; green remains reserved for the connected power button. The selector is disabled while connected or transitioning; its checked state remains visible. Mode persists without starting a connection. Only TUN offers VPN-service installation. The dashboard's required height includes pinned controls and the windows area's minimum height; the windows area can shrink and scroll at smaller window heights.

The main window retains its profile sidebar and neutral Graphite styling. The home route pins a compact system connection card and an add-window toolbar above a scrollable list of independent connection cards. Each window groups status/profile/session/HTTPS latency, inline HTTP/SOCKS5/protocol and its own browser/resource/auto-open controls. The system card has no ports or browser controls. The separate Settings route contains the existing log/client settings/update tabs, preserving their controls and appearance. Its sidebar action is immediately below New profile, with an 8px gap and a visible selected state; the page offers a back-to-home action. Route changes retain live sessions, unsaved settings and the selected settings tab. The log tab includes a connection selector by stable ID; a card's log action opens that route and selects its own session.

Window cards use 12px padding, 8px row gaps and existing panel borders/radii; the system card retains 16px horizontal padding. Browser controls stack inside each window card without shrinking fonts. Profile names elide with the full name available in tooltip and accessibility text; resource selection ignores wheel scrolling. Only the windows list scrolls within the dashboard; the system card and add action remain visible. Menus provide profile/port edits, per-connection startup, diagnostics and address copying. The stable window number survives deletion of neighboring cards.

The system card uses a two-tier layout: title, menu and power control on top; profile with a small country flag and protocol, latency, session and traffic in four aligned groups below. Captions use muted 11px text and values use 14px/600 text. Remove the repeated app logo, status dot and routine state words. The power icon alone communicates routine state: gray off, rotating/cancellable while busy, green icon and border with a subtle success-colored surface when connected; preserve tooltips, accessible state and keyboard focus. The flag identifies the profile and retains its colors while offline. Ping means TCP handshake to the profile server through the physical interface, excluding DNS/TLS/HTTP. It starts in the background as soon as a session connects and updates about every 5 seconds. Show an ellipsis while the first sample is pending, an explicit no-response value after a failed sample, and a dash while offline. WireGuard uses a separately labelled HTTPS duration instead of pretending that a UDP endpoint has TCP ping. The service setup action names the Windows system-VPN service and explains its role before UAC; it is not another VPN client.

The initial 903 by 650 content area, below the 32px title bar, must show the home page, including one row of connection cards and the footer, without a scrollbar. Keep the outer page free of vertical scrolling; additional connection rows scroll inside the windows list, and overflowing settings scroll inside their own content area. Verify this on the native Windows Qt plugin; offscreen font metrics alone missed this regression. Only the active tab may contribute size hints and height-for-width calculations. Logs scroll inside their own console when needed.

Below 760 logical pixels of usable content width (viewport width minus 50px of body insets), settings cards stack vertically and the connection action moves below the status details. Keep horizontal clipping out of both compact and wide layouts; allow vertical scrolling after an explicit reduction of the window to reach the save action. Long profile names elide visually while retaining the full label text and tooltip. Keep settings dropdowns compact so their columns do not unnecessarily wrap descriptions.

Current source sizes: initial window 903 by 682, minimum 900 by 592, including the 32px title bar; profile dialog width 460; launch-sites dialog width 440. These are existing constraints to verify against, not new mandatory fixed sizes for every component. Common gaps are 8, 12, 14, 16 and 18 logical pixels; panel insets are around 14–16, dialog insets 24. Match the relevant neighboring layout rather than forcing a new spacing scale.

Validate changed areas at minimum and initial window sizes, Windows display scaling (100%, 125%, 150%), and with long Russian labels or profile names. Keep actions reachable when content grows.

## Elevation & Depth

Proxy window cards are 260 logical pixels wide with content-driven height and 12px grid gaps: two fit across the default 903px window, three at 1100px. There is no bottom spacer or forced square height. Long protocol names wrap instead of clipping. The header shows only the stable window number, profile flag, menu and power icon. The flag is grayscale until connected; the power outline is slate when off, green when connected, and a rotating neutral-contrast arc while preparing/connecting/reconnecting/stopping. Connecting remains cancellable with keyboard and mouse. The profile occupies its own line. Data uses two columns: session/Ping, HTTP/SOCKS5, protocol/Трафик. Browser button, resource dropdown with add button and auto-open switch retain their actions. Errors use the title warning tooltip and do not increase card height. Routine status words and the window status dot are hidden. The system card uses the approved two-tier information layout, without the repeated app logo or status dot; it keeps the same top-right power icon and menu order as the windows. Its connected power control also has a green border and subtle success surface. Traffic tooltips explain the calendar month, upload plus download and the start of collection; unavailable service statistics show a dash instead of a fabricated total.

Window connection and browser errors appear in an 18×22 logical-pixel vector triangle beside the window title, with full sanitized details in a native tooltip on hover or keyboard focus. The indicator disappears when the error clears; error text does not occupy the card body or change its height. Non-error recovery/information captions and system-card messages keep their existing inline behavior.

The current hierarchy uses flat dark surfaces and thin borders. Dialogs use the existing translucent background and `dialogOverlay`. Preserve this model for normal feature work.

## Shapes

Controls and profile rows generally have 4px corners; panels have 8px corners. Switches retain their rounded tracks and protocol choices retain their rounded pills. Preserve the 3px selected-profile accent and existing logo treatment. Generic recommendations about large radii or alternative typography do not override this established design.

## Components

Reuse `objectName` styles and existing construction patterns before adding another visual variant:

- Actions: `primaryButton`, `primaryButtonWide`, `outlineButton`, `ghostButton`, `successButton`, `dangerButton`, `iconButton`.
- Surfaces: `statusPanel`, `metricCard`, `settingsCard`, `updatePanel`, `profileDialogPanel`.
- Profiles: `profileRow[selected]`, `profileAccent`, `profileCountryBadge`, `profileName`, `profileProtocol`, and the drawn three-dot `profileMenuButton`. Country badges show local 4:3 SVG flags at 24 by 18 logical pixels inside a 28 by 20 slot, retaining country names in tooltips and accessible text. Unknown countries use a neutral globe. The country picker uses the same icons beside its existing text labels. The empty state offers a single add-profile action.
- Forms: `fieldLabel`, `inputShell[invalid]`, `flatLineEdit`, `protocolPill`; reuse `ProfileDialog` and `LaunchSitesDialog` conventions. Preserve the visible protocol list: VLESS and Shadowsocks are enabled; WireGuard import in this dialog, Trojan and VMess are disabled with explanatory tooltips. Pasting a valid link selects the detected protocol automatically. Show validation beside the input; the resources dialog commits the current edit on selection changes and on Done.
- Navigation and feedback: `pivotTab[selected]`, `contentStack`, `statusDot[connected]`, `LoadingButton` and `SwitchControl` in `main_window.py`.

Object names and dynamic properties participate in QSS matching; preserve their behavior when refactoring. Apply Qt stylesheet syntax rather than browser CSS. Some controls are custom painted or have inline styles, so inspect their Python implementation too.

Resource add buttons use `PlusButton`, and the 28px dialog badges use `PlusBadge`. Both paint symmetric strokes around the floating-point widget center instead of relying on a font's plus glyph and baseline; preserve their existing QSS surfaces and accessible button names.

The status panel shows progress/recovery text when relevant and a red error indicator. Keep routine idle/connected captions empty to preserve the compact resting height. Disconnected metadata describes the selected profile; connected metadata continues to describe the running session even if the user selects another profile. `SwitchControl` derives from Qt's check box for native keyboard/accessibility behavior while preserving its existing painted appearance, with a dotted theme-aware focus outline.

The settings save action is a compact primary button, 36px tall and aligned to the right. Do not stretch it across the page. Enabled buttons, selectable lists, dropdowns, spin controls and menu actions use a pointing-hand cursor; disabled actions use an arrow and text fields retain their editing cursor. `install_pointer_cursors` applies this convention at the application level, including dynamically created menus.

The «Автозапуск» switch reveals «Автоподключение» directly below it. Use a full-width checklist of saved system/window connections with profile names, native check indicators and a neutral contrast focus border. Show up to four 28px rows, scrolling longer lists internally; long names elide with full tooltips. Hide the entire group when autostart is off while preserving checked connections. Unassigned connections show guidance to choose a profile on Home and cannot be checked.

## Do's and Don'ts

- Extend the existing design by default; replace its visual direction only when the user requests it.
- Check keyboard navigation, visible focus, accessible names for icon actions, control labels and all relevant loading/empty/error/disabled states. These are verification goals, not assertions about current coverage.
- Keep UI work nonblocking; preserve worker threads and signals for connections and updates.
- Use synthetic profile content in screenshots and diagnostics. Never expose proxy credentials or private keys.
- Verify changes in the Qt render when possible and state any unverified behavior. Root screenshots are historical references unless their freshness is established against current source.
- Browser DOM, ARIA, CSS media queries, web vitals and browser Live Mode do not validate this Qt Widgets application. Do not introduce a web stack to use those tools.

## Window title bar

`outward_app/ui/window_chrome.py` owns a compact 32px title bar inspired by the Graphite concept: 16px app icon and a regular 12px Segoe UI title at the left, three 46px-wide vector caption buttons at the right, and a quiet bottom divider. The background follows the current Qt Button palette role; text follows WindowText. Hover and pressed feedback use translucent foreground fills; close uses conventional Windows red feedback. Keyboard focus is visible for keyboard navigation. The title and icon remain real native window metadata for the taskbar and Alt+Tab.

The Qt default size is 903x682 and minimum 900x592, including the title bar. Content below it keeps the previous 903x650 default and 900x560 minimum area. Windows owns dragging, resizing, system commands and monitor placement through native non-client hit tests. DWM owns shadows and corner rounding; do not use a transparent top-level window or rounded mask. Closing goes through MainWindow's existing tray/connection-cleanup policy. See `docs/validation/window-chrome.md` for verification and limitations.
