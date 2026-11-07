# Outward App product context

## Platform

Windows desktop application using Python 3.11+ and PySide6 Qt Widgets, with optional PySide6-Fluent-Widgets controls. Graphite has explicit light and dark themes; dark is the default. This is a native desktop GUI, not a web frontend. Impeccable's web/iOS/Android platform enum does not describe this stack; use its project-specific Qt guidance.

## Product Purpose

Users save named server profiles, connect a system connection and/or independent local HTTP/SOCKS5 windows through sing-box, inspect each connection and optionally open Chrome or Edge through that window's SOCKS5 port. The system connection offers mutually exclusive TUN and Windows user-proxy modes. TUN requires a separately installed Windows service; the system proxy runs without that service and applies to applications that honor Windows user-proxy settings. Logs, client settings and updates live in a separate Settings route in the same app window; its sidebar button is below New profile. Home contains only connection controls.

This context comes from the existing repository and the user's request to preserve its current design while supporting further frontend development. A more specific audience or positioning has not been established; do not invent it.

## Workflows and Constraints

- The system mode selector is on its own row between header and metrics, without explanatory text to its right. Mode changes persist while offline and are locked during active operations. System proxy restores prior manual/PAC/autodetect settings on stop and has an independent recovery helper for GUI crashes; external proxy changes are preserved.
- Preserve the distinction between HTTP and SOCKS5 ports and the real connected, pending and disconnected states.
- Keep existing profile/settings compatibility and asynchronous connection/update workers.
- Settings → Client settings → General contains a keyboard-accessible Light/Dark theme selector. Appearance applies immediately and persists independently of unfinished network settings. Switching preserves sessions, the current page/tab, form drafts, and journal selection/scroll.
- Preserve stable window IDs, browser data and port ownership; stopping or failing one connection must not stop another.
- The portable data model and platform adapters prepare for future Android/iOS clients; those clients are not implemented by the Windows feature.
- Reflect the actual controls and supported input formats; do not imply that a protocol is selectable just because the backend can parse it.
- Support Russian (default) and English interface copy with established protocol terminology. Settings → Client settings → General offers a single-select language dropdown below appearance; it saves independently and applies after restart. User content and original engine diagnostics retain their language.
- Protect profile credentials and private keys in errors, screenshots and design examples.
- Follow `DESIGN.md` for current visual rules; new UI should belong to the existing application unless a redesign is explicitly requested.

## Source of Truth

Read `.codex/skills/outward-app-overview/SKILL.md` for the project map, then verify relevant files in `outward_app/ui/`. This document records existing behavior and constraints, not approval for additional product features.
