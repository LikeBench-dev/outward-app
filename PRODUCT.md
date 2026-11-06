# Outward App product context

## Platform

Windows desktop application using Python 3.11+ and PySide6 Qt Widgets, with an optional PySide6-Fluent-Widgets dark theme. This is a native desktop GUI, not a web frontend. Impeccable's web/iOS/Android platform enum does not describe this stack; use its project-specific Qt guidance.

## Product Purpose

Users save named connection profiles, select one, start a local sing-box proxy, inspect connection status and logs, and optionally open a configured site in Chrome or Edge through the SOCKS5 port. Settings and application updates are available in the same window.

This context comes from the existing repository and the user's request to preserve its current design while supporting further frontend development. A more specific audience or positioning has not been established; do not invent it.

## Workflows and Constraints

- Preserve the distinction between HTTP and SOCKS5 ports and the real connected, pending and disconnected states.
- Keep existing profile/settings compatibility and asynchronous connection/update workers.
- Reflect the actual controls and supported input formats; do not imply that a protocol is selectable just because the backend can parse it.
- Use predominantly Russian interface copy and established protocol terminology.
- Protect profile credentials and private keys in errors, screenshots and design examples.
- Follow `DESIGN.md` for current visual rules; new UI should belong to the existing application unless a redesign is explicitly requested.

## Source of Truth

Read `.codex/skills/outward-app-overview/SKILL.md` for the project map, then verify relevant files in `outward_app/ui/`. This document records existing behavior and constraints, not approval for additional product features.
