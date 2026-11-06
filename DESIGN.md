---
name: Outward App
description: Existing Windows desktop design system, recorded from PySide6 source.
colors:
  app-bg: "#11111d"
  sidebar-bg: "#0c0c16"
  content-bg: "#1a1a2c"
  panel-bg: "#303050"
  panel-border: "#47456f"
  input-bg: "#111120"
  primary: "#9B59FF"
  primary-hover: "#b975ff"
  fluent-accent: "#a84fff"
  text: "#f4f1ff"
  muted: "#9198ad"
  connected: "#26d98a"
  disconnected: "#ffbf32"
  success-button: "#1f9d62"
  danger: "#d14343"
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

Preserve the existing midnight/violet Windows desktop interface when adding or refining UI. This file records the implementation; it is not a redesign or a claim that all existing states meet accessibility targets. The user's explicit design request takes precedence.

Sources: `outward_app/ui/styles.py` (`APP_STYLE`), `ui/app.py` (Fluent theme), `ui/main_window.py` (layout, controls and state), `ui/widgets.py` (elided labels and active-page sizing), and `ui/dialogs.py` (forms). Paths starting with `ui/` here are relative to `outward_app/`. Recheck these sources before changing a token; update this document alongside intentional system changes.

## Colors

Use the recorded colors by role. Violet is the primary action, selection and pending-state accent; green indicates a connection or successful action; amber indicates the disconnected status dot; red is reserved for destructive actions. State also needs a readable label or control change.

`APP_STYLE` uses `#9B59FF`; the optional Fluent theme currently uses `#a84fff`. These are existing distinct values, not a request to consolidate them. Consult actual selectors for hover, pressed, disabled and secondary text variants. Check contrast in the rendered state rather than assuming an existing color pair passes.

## Typography

Keep Segoe UI and its existing fallbacks. Body text is 13px; section and metric captions use 11px; status and brand titles use 16px/700; dialog titles use 20px/700. Log styles declare Cascadia Mono/Consolas for `QPlainTextEdit`; the current log widget is `QTextEdit`, so verify its effective font instead of assuming that selector applies.

Visible copy is predominantly Russian. Preserve established labels and terminology, allow Cyrillic and long profile names, and keep protocol names such as VLESS and SOCKS5 recognizable.

## Layout

The main window has a profile sidebar and a scrollable working area with connection status, metrics, launch controls and tabs for logs, settings and updates. Use Qt layouts, stretch factors, size policies and the existing scroll area for resizing.

The initial 1100 by 750 window must show the entire active page, including the footer, without an outer vertical scrollbar. Verify this on the native Windows Qt plugin; offscreen font metrics alone missed this regression. Only the active tab may contribute size hints and height-for-width calculations. Logs scroll inside their own console when needed.

Below 760 logical pixels of usable content width (viewport width minus 50px of body insets), settings cards stack vertically and the connection action moves below the status details. Keep horizontal clipping out of both compact and wide layouts; allow vertical scrolling after an explicit reduction of the window to reach the save action. Long profile names elide visually while retaining the full label text and tooltip. Keep settings dropdowns compact so their columns do not unnecessarily wrap descriptions.

Current source sizes: initial window 1100 by 750, minimum 900 by 560; profile dialog width 460; launch-sites dialog width 440. These are existing constraints to verify against, not new mandatory fixed sizes for every component. Common gaps are 8, 12, 14, 16 and 18 logical pixels; panel insets are around 14–16, dialog insets 24. Match the relevant neighboring layout rather than forcing a new spacing scale.

Validate changed areas at minimum and initial window sizes, Windows display scaling (100%, 125%, 150%), and with long Russian labels or profile names. Keep actions reachable when content grows.

## Elevation & Depth

The current hierarchy uses flat dark surfaces and thin borders. Dialogs use the existing translucent background and `dialogOverlay`. Preserve this model for normal feature work.

## Shapes

Controls and profile rows generally have 4px corners; panels have 8px corners. Switches retain their rounded tracks and protocol choices retain their rounded pills. Preserve the 3px selected-profile accent and existing logo treatment. Generic recommendations about large radii, system fonts or avoiding violet do not override this established design.

## Components

Reuse `objectName` styles and existing construction patterns before adding another visual variant:

- Actions: `primaryButton`, `primaryButtonWide`, `outlineButton`, `ghostButton`, `successButton`, `dangerButton`, `iconButton`.
- Surfaces: `statusPanel`, `metricCard`, `settingsCard`, `updatePanel`, `profileDialogPanel`.
- Profiles: `profileRow[selected]`, `profileAccent`, `profileCountryBadge`, `profileName`, `profileProtocol`, and the drawn three-dot `profileMenuButton`; countries use text badges. The empty state offers a single add-profile action.
- Forms: `fieldLabel`, `inputShell[invalid]`, `flatLineEdit`, `protocolPill`; reuse `ProfileDialog` and `LaunchSitesDialog` conventions. Preserve the visible protocol list: VLESS and Shadowsocks are enabled; WireGuard import in this dialog, Trojan and VMess are disabled with explanatory tooltips. Pasting a valid link selects the detected protocol automatically. Show validation beside the input; the resources dialog commits the current edit on selection changes and on Done.
- Navigation and feedback: `pivotTab[selected]`, `contentStack`, `statusDot[connected]`, `LoadingButton` and `SwitchControl` in `main_window.py`.

Object names and dynamic properties participate in QSS matching; preserve their behavior when refactoring. Apply Qt stylesheet syntax rather than browser CSS. Some controls are custom painted or have inline styles, so inspect their Python implementation too.

The status panel shows progress/recovery text when relevant and a red error indicator. Keep routine idle/connected captions empty to preserve the compact resting height. Disconnected metadata describes the selected profile; connected metadata continues to describe the running session even if the user selects another profile. `SwitchControl` derives from Qt's check box for native keyboard/accessibility behavior while preserving its existing painted appearance, with a dotted violet focus outline.

The settings save action is a compact primary button, 36px tall and aligned to the right. Do not stretch it across the page. Enabled buttons, selectable lists, dropdowns, spin controls and menu actions use a pointing-hand cursor; disabled actions use an arrow and text fields retain their editing cursor. `install_pointer_cursors` applies this convention at the application level, including dynamically created menus.

## Do's and Don'ts

- Extend the existing design by default; replace its visual direction only when the user requests it.
- Check keyboard navigation, visible focus, accessible names for icon actions, control labels and all relevant loading/empty/error/disabled states. These are verification goals, not assertions about current coverage.
- Keep UI work nonblocking; preserve worker threads and signals for connections and updates.
- Use synthetic profile content in screenshots and diagnostics. Never expose proxy credentials or private keys.
- Verify changes in the Qt render when possible and state any unverified behavior. Root screenshots are historical references unless their freshness is established against current source.
- Browser DOM, ARIA, CSS media queries, web vitals and browser Live Mode do not validate this Qt Widgets application. Do not introduce a web stack to use those tools.
