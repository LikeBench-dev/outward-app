# System connection: TUN and Windows user proxy

The pinned system card offers mutually exclusive `TUN` and `Системный прокси`
segments. The selected mode is persisted in `SavedConnection.system_mode` in
schema-1 connections; old files default to `tun`. It can change only while
offline, with no manager awaiting cleanup. Profile, auto-connect choice and
monthly traffic remain attached to the same system connection.

TUN retains its existing service implementation. Proxy mode starts an independent
sing-box process with loopback HTTP/SOCKS listeners under `sessions/system` and
reserves ports through the shared allocator. After listeners and a TLS-verified
HTTPS route probe succeed, it applies HTTP/HTTPS user proxy settings through
WinINet `INTERNET_OPTION_PER_CONNECTION_OPTION`. It does not configure WinHTTP,
create a TUN adapter, install a service, or change routes. Applications must honor
the user's Windows proxy settings to use this mode.

## Ownership and recovery

Before applying settings, `system-proxy.json` in app data records the original
manual proxy, bypass, PAC URL, mode flags, intended settings, PID, process creation
time and a random lease token. PAC/autodetection are disabled during the proxy
session and restored exactly on release. Local destinations bypass the proxy.
The journal is atomic and ignored by Git. Do not publish it: previous proxy/PAC
configuration can contain private network information.

The independent `--system-proxy-watchdog <token>` helper holds a verified handle
to the GUI process and acknowledges readiness before Windows settings change.
It waits on parent exit and a cooperative stop event. Parent death triggers
compare-before-restore recovery; normal disconnect restores first, then signals
the helper to exit, then stops listeners. A path-scoped Windows mutex serializes
recovery with a newly started GUI. Startup also recovers abandoned journals.

If another program changes the settings, release preserves those changes; the
health check stops the system proxy without automatically taking control again.
If restoration fails, the journal and live listeners remain available for retry.
System proxy traffic is recorded locally under `system-proxy` and added to the
service-owned `system` total, so changing modes does not reset or duplicate it.

## Automated verification (2026-11-07)

- `tests/test_system_proxy.py`: legacy defaults, persistence, mode locking,
  independent windows/ports, readiness failure, cancellation and activation
  failure, normal shutdown, traffic totals across modes, snapshot/restore of
  manual/PAC/autodetect values, external changes, live-owner refusal, disk and
  helper failure, partial apply, retryable restoration failure.
- Native WinINet snapshot read and pointer-size check; native write payload and
  refresh notifications are inspected with a fake API. Tests never write the
  machine's actual proxy settings.
- Two real Windows child-process/event tests exercise verified parent death and
  cooperative helper exit, with restoration directed to a file-backed fake API.
- `tests/test_system_mode_ui.py`: mouse/keyboard selection, checked accessibility
  state, saving, active-state locking, failed-save rollback, proxy-mode service
  suppression, and preservation of profile and window cards.
- `capture_system_mode.py`: native Windows Qt plugin, dark/light themes, Russian
  and English, both modes, offline/connected/connecting/error states, minimum,
  default and wider windows. Verified at 100%, 125%, 150% scaling. No outer-page
  or horizontal windows scrolling; the selector remains unclipped. Captures use
  synthetic profiles and no network sessions.

Example commands:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_system*.py'
.\.venv\Scripts\python.exe docs/validation/capture_system_mode.py
$env:QT_SCALE_FACTOR='1.25'
.\.venv\Scripts\python.exe docs/validation/capture_system_mode.py
```

## Remaining end-to-end acceptance

Use a dedicated Windows environment with a supplied working profile to verify
real Windows setting writes and browser adoption, restoration of pre-existing
manual/PAC/autodetect settings, reconnect after sleep/network changes, and forced
termination of both source and packaged GUI builds. Verify helper readiness and
cleanup in the one-file packaged build, service-free operation in proxy mode,
autostart with either saved mode, and coexistence with independent windows.
Existing privileged TUN acceptance remains separate. No installer was built and
no real proxy profile was activated during this implementation's automated checks.

API contract: [Microsoft: per-connection options](https://learn.microsoft.com/en-us/windows/win32/api/wininet/ns-wininet-internet_per_conn_optiona),
[setting and retrieving options](https://learn.microsoft.com/en-us/windows/win32/wininet/setting-and-retrieving-internet-options).
