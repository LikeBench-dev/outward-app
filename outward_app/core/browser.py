from __future__ import annotations

import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from outward_app.paths import app_data_dir

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
) -> bool:
    launch_url = normalize_launch_url(url)
    browser = find_proxy_browser(preferred_browser)
    if not browser:
        webbrowser.open(launch_url)
        return False

    profile_dir = app_data_dir() / f"{CHROME_PROFILE_DIR_PREFIX}_{socks_port}"
    profile_dir.mkdir(exist_ok=True)

    subprocess.Popen(
        browser_launch_args(browser, profile_dir, socks_port, launch_url, disable_extensions),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return True


