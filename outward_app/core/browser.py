from __future__ import annotations

import os
import shutil
import subprocess
import re
import json
from pathlib import Path
from urllib.parse import urlparse

from outward_app.paths import app_data_dir


def _browser_profiles_in_use() -> set[str] | None:
    if os.name != 'nt':
        return None
    from outward_app.core.singbox import hidden_startupinfo
    script = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); @(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='msedge.exe'\" | Select-Object -ExpandProperty CommandLine) | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10,
                            startupinfo=hidden_startupinfo(), creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        return None  # Unknown ownership: keep bindings conservatively.
    commands = json.loads(result.stdout or '[]') or []
    if isinstance(commands, str):
        commands = [commands]
    result = set()
    pattern = r'"--user-data-dir=([^\"]+)"|--user-data-dir="([^\"]+)"|--user-data-dir=([^\s]+)'
    for command in commands:
        if not command:
            continue
        for match in re.finditer(pattern, command):
            result.add(os.path.normcase(os.path.abspath(next(value for value in match.groups() if value))))
    return result


def browser_port_owners() -> dict[str, int]:
    markers = list(app_data_dir().glob('chrome_proxy_profile_*/outward-proxy.json'))
    if not markers:
        return {}
    try:
        active = _browser_profiles_in_use()
    except (OSError, ValueError):
        active = None
    owners = {}
    for marker in markers:
        try:
            value = json.loads(marker.read_text(encoding='utf-8'))
            if active is None or os.path.normcase(str(marker.parent.resolve())) in active:
                owners[value['connection_id']] = int(value['socks_port'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return owners

DEFAULT_LAUNCH_URL = "https://example.com"
CHROME_PROFILE_DIR_PREFIX = "chrome_proxy_profile"


def browser_candidates() -> dict[str, list[Path]]:
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    program_files_x86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))

    return {
        "chrome": [
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
        ],
        "edge": [
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ],
    }


def find_proxy_browser(preferred: str = "auto") -> str | None:
    candidates = browser_candidates()
    order = ["chrome", "edge"] if preferred == "auto" else [preferred, "chrome", "edge"]

    seen = set()
    for key in order:
        if key in seen:
            continue
        seen.add(key)
        for candidate in candidates.get(key, []):
            if candidate.exists():
                return str(candidate)

    commands = ["chrome.exe", "chrome", "msedge.exe", "msedge"]
    if preferred == "edge":
        commands = ["msedge.exe", "msedge", "chrome.exe", "chrome"]

    for command in commands:
        from_path = shutil.which(command)
        if from_path:
            return from_path

    return None


def normalize_launch_url(url: str) -> str:
    candidate = (url or DEFAULT_LAUNCH_URL).strip()
    if not candidate:
        return DEFAULT_LAUNCH_URL
    if not urlparse(candidate).scheme:
        candidate = f"https://{candidate}"
    return candidate


def browser_launch_args(
    browser: str,
    profile_dir: Path,
    socks_port: int,
    launch_url: str,
    disable_extensions: bool = False,
) -> list[str]:
    args = [
        browser,
        "--new-window",
        "--no-first-run",
        f"--user-data-dir={profile_dir}",
        f"--proxy-server=socks5://127.0.0.1:{socks_port}",
    ]
    if disable_extensions:
        args.append("--disable-extensions")
    args.append(launch_url)
    return args


def open_url_with_proxy(
    socks_port: int,
    preferred_browser: str = "auto",
    url: str = DEFAULT_LAUNCH_URL,
    disable_extensions: bool = False,
    *,
    connection_id: str = "",
    legacy_browser_dir: str = "",
    still_current=None,
) -> bool:
    launch_url = normalize_launch_url(url)
    browser = find_proxy_browser(preferred_browser)
    if not browser:
        return False

    if connection_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", connection_id):
        raise ValueError("Invalid browser connection id")
    legacy = app_data_dir() / legacy_browser_dir if re.fullmatch(r"chrome_proxy_profile_\d+", legacy_browser_dir) else None
    # Reusing the original directory avoids moving a live browser or losing its cookies/history.
    if legacy and legacy.is_dir():
        profile_dir = legacy
    else:
        profile_dir = app_data_dir() / f"{CHROME_PROFILE_DIR_PREFIX}_{connection_id or socks_port}"
    profile_dir.mkdir(exist_ok=True)
    if connection_id:
        from outward_app.core.storage import atomic_write_json
        marker = profile_dir / 'outward-proxy.json'
        previous = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else None
        if previous and previous.get('socks_port') != socks_port:
            active = _browser_profiles_in_use()
            if active is None or os.path.normcase(str(profile_dir.resolve())) in active:
                raise OSError('Порты окна изменились. Сначала закройте все окна его браузерного профиля, затем откройте браузер снова.')
        if still_current and not still_current():
            raise OSError('Подключение уже остановлено; браузер не запущен')
        atomic_write_json(marker, {'connection_id': connection_id, 'socks_port': socks_port})

    subprocess.Popen(
        browser_launch_args(browser, profile_dir, socks_port, launch_url, disable_extensions),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return True


