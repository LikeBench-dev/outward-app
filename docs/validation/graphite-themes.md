# Graphite themes verification

Graphite replaces the violet interface with paired neutral light/dark palettes.
Dark is the default for old settings and new installations. The first General
setting contains explicit «Светлая / Тёмная» buttons. Choosing a theme applies
immediately and persists independently of the settings form.

## Implementation boundaries

- `ui/themes.py`: palette roles, QApplication-owned ThemeManager, QPalette and
  optional Fluent synchronization.
- `ui/styles.py`: QSS templates resolved from those roles, including controls,
  selection, focus, menus, tooltips and placeholders.
- Custom switches, connection progress/power and resource arrows resolve colors
  from the current palette. Plus/menu glyphs paint dynamically rather than
  retaining old-colored raster icons.
- Journal HTML is recolored even when its source text is unchanged, retaining
  selection and scroll. Existing connection widgets and sessions are not rebuilt.
- `AppSettings.theme` accepts light/dark and falls back to dark for absent/invalid
  stored values. `JsonStore.save_theme` atomically changes only this field, retaining
  other disk settings. General saves retain the selected theme.
- The palette-aware title bar and native frame follow the chosen theme. Its
  close-button Windows red feedback remains platform semantics.
- Real country flags and the logo retain their asset colors; the fallback globe
  uses a neutral gray with visible contrast in both themes.

## Verification

The full test suite passed (134 tests at the initial integration checkpoint).
After the final focus/placeholder and title-bar adjustments, targeted runs passed:
8 theme tests, 42 general UI tests, and 4 window-chrome tests.

`tests/test_themes.py` covers invalid/legacy theme values, storage round trips,
preservation of other disk fields, save failure, keyboard activation, general
save compatibility, active synthetic sessions, invalid form drafts, widget
identity, existing journal selection/scroll, newly created dialogs/cards,
plain-Qt fallback, and compact/expanded layouts.

The native Windows Qt renderer was exercised at scale factors 1, 1.25 and 1.5.
Both themes were checked at the minimum/default sizes (including the 32px title
bar) and a 1100px expanded window, on logs/settings/updates, with autostart
expanded, plus profile/resource/connection dialogs and a context menu.
This uses synthetic in-memory profiles and mocked startup/network/update
boundaries. It never reads/writes the user's settings or opens a proxy session.

Run from the repository root:

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -p test_themes.py
$env:QT_QPA_PLATFORM = 'windows'
$env:QT_SCALE_FACTOR = '1.25'
.venv/Scripts/python.exe docs/validation/capture_graphite.py
```

Add `--screenshots --output <directory>` for short-lived visible native windows
and widget PNGs. Omit it for hidden native layout checks. The script is a
repeatable QA helper, not the application launcher.

Reviewed native widget captures:
[dark home](assets/graphite-dark-home.png),
[light home](assets/graphite-light-home.png),
[dark settings](assets/graphite-dark-settings.png),
[light settings](assets/graphite-light-settings.png).

The captures show Qt widgets, not DWM shadows/corners. Scale-factor checks do not
prove physical monitor hot-plug or mixed-DPI dragging. Actual external VPN
connectivity was not needed to validate theme changes.

