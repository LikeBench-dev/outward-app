---
name: outward-app-overview
description: Use when working in the Outward App repository or answering questions about its architecture, features, proxy protocols/sing-box/browser/profile flow, UI, storage, tests, or packaging.
---

# Outward App Overview

Outward App is a Windows desktop GUI that launches a configured site through a local HTTP/SOCKS proxy powered by `sing-box`. Users save named connection profiles, pick one, start local proxy ports on `127.0.0.1`, and optionally open Chrome or Edge with the SOCKS5 proxy applied.

Use this overview before broad source exploration. Read only the files relevant to the current request after this unless the task asks for a fresh full audit.

## Main Shape

- Runtime: Python 3.11+, PySide6 GUI.
- Entrypoint: `outward_app/__main__.py` calls `outward_app.ui.app.run`.
- UI app setup: `outward_app/ui/app.py` creates `QApplication`, sets the visible app name to `Outward App`, applies `APP_STYLE`, loads `outward.ico`, opens `MainWindow`.
- Runtime data lives in `%LOCALAPPDATA%\OutwardApp`; if `LOCALAPPDATA` is absent, it falls back to `~/.outwardapp`.
- Runtime files: `config.json`, `profiles.json`, `settings.json`, `sing-box.log` for the current app run, `sing-box.log.1` for the previous app run, `sing-box-sessions.json`, the managed `bin/sing-box.exe` runtime copy, downloaded update installers under `updates/`, and browser profile directories such as `chrome_proxy_profile_<port>`.
- App version is resolved by `outward_app/version.py`: frozen builds read the Windows file version from the executable first, then fall back to bundled/source `VERSION`.
- Visual assets: `assets/outward.png` for in-app avatar/logo and `assets/outward.ico` for window/tray/installer icons. Both are bundled by `OutwardApp.spec` along with `VERSION`.

## Core Modules

- `outward_app/paths.py`: centralizes source, bundled, asset, app data, config, log, profiles, and settings paths. It handles PyInstaller via `sys.frozen` and `_MEIPASS`.
- `outward_app/version.py`: displays the runtime app version from the frozen executable file version or the bundled/source `VERSION` file.
- `outward_app/core/models.py`: dataclasses for `ConnectionProfile`, `AppSettings`, and `RuntimeState`. Profiles include optional `protocol` and `country_code`; timestamps are ISO UTC strings. Missing `protocol` remains valid for legacy profiles.
- `outward_app/core/connections.py`: protocol-aware parsing and metadata. It detects and parses VLESS links, Shadowsocks `ss://` links, and WireGuard config text, returns `ParsedConnection`, provides protocol labels, and masks secrets in connection errors.
- `outward_app/core/countries.py`: provides all country codes/names from Qt `QLocale`, country-code normalization, and fallback country guessing from profile names/remarks/servers. The UI uses text badges for countries instead of emoji flags or image assets.
- `outward_app/core/storage.py`: `JsonStore` reads/writes profiles and settings as UTF-8 JSON. Profiles are stored as `{"profiles": [...]}` and new profiles are inserted at the top.
- `outward_app/core/updater.py`: checks GitHub Releases for `LikeBench-dev/outward-app`, compares release tags with the current app version, selects Windows installer assets, extracts optional SHA256 values from release notes or checksum assets, downloads installers to the runtime `updates/` folder, and verifies checksums when present.
- `outward_app/core/vless.py`: parses VLESS links into dicts used by the protocol layer. It tolerates `vless\://`, missing `@` after UUID, alternate query names such as `pbk/public_key`, `sid/short_id`, `sni/server_name`, `fp/fingerprint`, and loose query tails after `type=...`. It requires scheme `vless`, UUID, server, port, and Reality public key.
- `outward_app/core/singbox.py`: builds protocol-aware sing-box configs, writes `%LOCALAPPDATA%\OutwardApp\config.json`, rotates `sing-box.log` to `sing-box.log.1` once per app start, installs bundled `sing-box.exe` to `%LOCALAPPDATA%\OutwardApp\bin\sing-box.exe` before launch so frozen one-file temp directories are not held open by the proxy process, records managed process metadata in `sing-box-sessions.json`, stops only previous sing-box sessions launched by Outward App when asked, chooses nearby free ports, starts/stops the managed process, waits for local proxy ports, and tails the current `sing-box.log`.
- `outward_app/core/browser.py`: finds Chrome or Edge, normalizes launch URLs, creates a per-port app data browser profile directory, and opens the configured site with `--proxy-server=socks5://127.0.0.1:<port>`. It can add `--disable-extensions` when the user enables that browser setting. If no supported browser is found, it falls back to `webbrowser.open` without guaranteed proxy settings.
- `outward_app/core/autostart.py`: manages the per-user Windows startup entry under `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run` for the autoconnect setting. Frozen builds register the app executable; source runs register `python -m outward_app`.

## Supported Protocols

- VLESS: supported through existing VLESS/Reality parser and a `vless` outbound tagged `proxy`.
- Shadowsocks: supported through `ss://` parsing and a `shadowsocks` outbound tagged `proxy`.
- WireGuard: WireGuard config text is parsed and emitted as a modern `wireguard` endpoint tagged `proxy`. The old WireGuard outbound is intentionally not used because newer `sing-box` versions removed it.

## UI Flow

- Main UI: `outward_app/ui/main_window.py`.
- General settings include `auto_connect_on_startup`; when enabled, the app registers itself in Windows autostart and starts connecting to the selected profile shortly after the UI loads.
- Profile dialog: `outward_app/ui/dialogs.py`.
- Stylesheet: `outward_app/ui/styles.py`; the app uses a dark midnight/violet palette with orange, green, and muted slate accents. `outward_app/ui/app.py` applies `qfluentwidgets` dark theme when `PySide6-Fluent-Widgets` is installed, then layers the custom stylesheet on top. Visible UI text is mostly Russian.
- `MainWindow` owns `JsonStore`, `AppSettings`, `SingBoxManager`, the profile list, and current `RuntimeState`.
- `ConnectWorker` runs on a `QThread` so parsing, process control, config checks, and port waiting do not block the UI.
- `UpdateCheckWorker` and `UpdateDownloadWorker` run GitHub update checks and installer downloads on `QThread`s. Startup performs a silent background check; the settings button runs the same check manually. The auto-update toggle stores `auto_update_app` and downloads available installers in the background.

Connect flow:

1. Save current settings from the UI.
2. Parse the selected profile with `parse_connection`.
3. Stop the managed sing-box process if it is already running.
4. If `stop_existing_sing_box` is true, stop only old sing-box sessions recorded by Outward App after verifying PID, creation time, command line config path, and executable path; user-started `sing-box.exe` processes are left alone.
5. Choose configured HTTP/SOCKS ports or nearby free ports.
6. Build and write a protocol-aware sing-box config.
7. Locate `sing-box.exe`, run `sing-box check -c config.json`, start `sing-box run -c config.json`, and wait for both local proxy ports to open.
8. Create a `RuntimeState`, mark the profile as used, and open the configured launch URL if `auto_open_browser` is true.

Disconnect flow stops only the `SingBoxManager` process owned by this app instance and clears UI state.

## Sing-box Config Assumptions

- The generated UI/runtime config uses separate `http` and `socks` inbounds on configured local ports. `build_sing_box_config` still supports the old one-port mixed inbound when called without a SOCKS port.
- Route final is always `proxy`; there is also a `direct` outbound.
- VLESS and Shadowsocks use `outbounds` tagged `proxy`; WireGuard uses a modern `endpoints` entry tagged `proxy`.
- DNS servers are emitted in the new sing-box 1.12+ format, such as `{ "type": "udp", "server": "1.1.1.1" }`, not legacy `{ "address": "1.1.1.1" }`; when DNS is configured, `route.default_domain_resolver` points at `custom-dns-0`.
- The UI labels HTTP and SOCKS5 as distinct local ports and opens browsers through the SOCKS5 port.

## Tests And Commands

- Core tests live in `tests/test_core.py`.
- Run tests with `.\.venv\Scripts\python.exe -m unittest discover -s tests`.
- Run syntax checks with `.\.venv\Scripts\python.exe -m compileall outward_app tests`.
- Run the app with `.\.venv\Scripts\python.exe -m outward_app`.
- Install bundled runtime dependencies with `.\install-deps.ps1`; it reads `SING_BOX_VERSION`, downloads the matching Windows amd64 sing-box release, and writes `bin/sing-box.exe`. The binary is intentionally ignored by Git.
- Build a release installer with `build-installer.bat`; it bumps patch version in `VERSION`. Build a check installer without changing `VERSION` with `build-installer-check.bat` (PowerShell equivalent: `.\build-installer.ps1 -NoVersionBump`). PyInstaller spec is `OutwardApp.spec`, Inno Setup script is under `installer/`, and installer output goes to `installer-output/Outward App Setup-<version>.exe`. The script ensures sing-box is installed, reads root `release-notes.md` by default, writes `.sha256` and `installer-output/release-notes-<version>.md`, and the built executable is `dist/Outward App.exe`.
- Silent update installation launches the downloaded Inno Setup installer with `/SILENT /NORESTART`; the installer has a `skipifnotsilent` run entry so the updated app starts again after a silent update.
- GitHub Actions workflow `.github/workflows/release.yml` publishes releases automatically on push to `master` when `VERSION` changes. It installs Python deps, Inno Setup, sing-box via `install-deps.ps1`, runs tests, builds with `-NoVersionBump`, and publishes `v<version>` with installer and `.sha256`. Manual publishing remains available with `.\build-installer.ps1 -NoVersionBump -PublishRelease` when `gh` is authenticated.

Prefer unit tests for parser, config generation, storage, and path/data behavior. GUI behavior currently has no dedicated automated test harness, so verify high-risk UI changes manually or with focused tests around extracted logic.

## Change Guidance

- Treat this as a Windows-first app. `subprocess.STARTUPINFO`, `CREATE_NO_WINDOW`, PowerShell `Win32_Process` queries, `taskkill`, `.exe` discovery, and Chrome/Edge paths are intentional.
- Do not launch the GUI, kill processes, or start external proxy/browser processes unless the user explicitly requests it or the task requires a runtime check.
- Keep profile/settings JSON compatibility in mind when changing models or storage.
- Never log or display raw Shadowsocks passwords, WireGuard private keys, or WireGuard preshared keys when reporting connection errors.
- If a change materially alters architecture, runtime files, connect flow, packaging, or user-visible capabilities, update this skill in the same task so future Codex runs do not rediscover stale behavior.



