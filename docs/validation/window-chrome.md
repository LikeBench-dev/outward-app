# Custom Windows title bar

The 32px Qt title bar follows the Graphite reference: app icon/title on the left,
three compact vector caption controls on the right. Its colors follow the Qt
palette in both themes. The default Qt window is 903x682, preserving the previous
903x650 content area; minimum is 900x592 with a 900x560 content area.

`outward_app/ui/window_chrome.py` retains native Windows window styles and handles
non-client sizing and hit testing. Windows receives caption/resize/system-menu
regions and `HTMAXBUTTON` for Windows 11 Snap discovery. The maximize button uses
native hover detection and mouse capture, then activates its Qt action once.
Native maximize/restore and close commands continue through Qt; the real app's
close handler retains tray and asynchronous connection-shutdown behavior.

No top-level translucency, custom shadow or window mask is used. DWM owns the
native border, shadow and corner rounding. Unsupported DWM decoration attributes
may be ignored by Windows without changing basic window behavior.

## Automated checks

- `tests/test_window_chrome.py`: caption actions, Space activation and accessible
  names, restore glyph/state, content height, hit regions, and palette painting.
- A separate real Windows Qt process at 100%, 125% and 150% sends HWND messages
  and checks native styles, system-menu availability, signed negative screen
  coordinates, both resize corners, caption/maximize hit tests, native
  maximize/restore, native title double-click, cancel-on-release-outside,
  maximize button activation, work-area bounds, and native close dispatch.
- `tests/test_ui.py`: the application's caption close hides to tray when enabled;
  otherwise it initiates asynchronous connection shutdown. Default native and
  offscreen layouts preserve the content area and avoid outer scrolling.

Run from the repository root:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_window_chrome.py
.venv/Scripts/python.exe -m unittest discover -s tests -p test_ui.py
```

Native tests use synthetic windows without network connections or saved app data.
The native message test shows a short-lived window: `WA_DontShowOnScreen` cannot
validate HWND coordinates because that mode keeps the OS window at its old size.
Its normal size is capped to the current screen's logical work area, leaving a
32px margin for native frame metrics. On small CI desktops at 125/150%, Windows
can clamp an oversized window during maximize/restore. The test asserts the
chosen size before maximizing and after both restore paths, while default
903x682 sizing remains covered by the offscreen caption and app-layout tests.

## Visual verification and remaining manual checks

The actual Windows Qt render was inspected with synthetic profile/session data
in both themes. Captures: [dark](assets/window-chrome-dark.png) and
[light](assets/window-chrome-light.png). These are widget captures; they do not
show the system shadow or prove native corner rendering.

UI automation could not start because the local sandbox helper reported
`setup refresh had errors`. Therefore physical drag-to-snap, the Windows 11 Snap
Layout popup on hover/Win+Z, actual Alt+Space/Win+arrow keyboard gestures, and
moving between physical monitors with different DPI remain manual checks.
The native hit tests and system commands used by these features passed, but are
not a substitute for testing those complete gestures.

The existing 900px minimum content width still limits narrow Snap zones. Native
maximized bounds were checked against the current monitor work area; taskbars on
other screen edges and auto-hide strip handling need manual verification with
those configurations. No host display/taskbar settings were changed.
