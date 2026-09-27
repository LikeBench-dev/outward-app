from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re
import urllib.error
import urllib.request

from outward_app.app_info import APP_NAME
from outward_app.paths import updates_dir

DEFAULT_GITHUB_REPOSITORY = "LikeBench-dev/outward-app"
USER_AGENT = f"{APP_NAME}/update-check"


@dataclass(frozen=True, slots=True)
class UpdateRelease:
    version: str
    name: str
    html_url: str
    installer_url: str
    installer_name: str
    notes: str = ""
    published_at: str = ""
    sha256: str = ""


@dataclass(frozen=True, slots=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str
    update_available: bool
    release: UpdateRelease | None = None


def normalize_version(value: str) -> str:
    version = str(value or "").strip()
    if version.lower().startswith("v"):
        version = version[1:]
    return version


def version_key(value: str) -> tuple[int, ...]:
    version = normalize_version(value)
    parts: list[int] = []
    for part in re.split(r"[.+-]", version):
        if not part:
            continue
        match = re.match(r"\d+", part)
        if match is None:
            break
        parts.append(int(match.group(0)))
    return tuple(parts or [0])


def is_newer_version(candidate: str, current: str) -> bool:
    left = list(version_key(candidate))
    right = list(version_key(current))
    width = max(len(left), len(right))
    left.extend([0] * (width - len(left)))
    right.extend([0] * (width - len(right)))
    return tuple(left) > tuple(right)


def _request_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub returned HTTP {exc.code} while checking updates.") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise RuntimeError(f"Could not reach GitHub to check updates: {reason}") from exc
    return json.loads(payload)


def _request_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(128 * 1024).decode("utf-8", errors="replace")


def _find_installer_asset(assets: list[dict]) -> dict | None:
    exe_assets = [asset for asset in assets if str(asset.get("name", "")).lower().endswith(".exe")]
    preferred = [asset for asset in exe_assets if "setup" in str(asset.get("name", "")).lower()]
    return (preferred or exe_assets or [None])[0]


def _extract_sha256_from_text(text: str, installer_name: str = "") -> str:
    normalized_name = installer_name.lower()
    for line in text.splitlines():
        match = re.search(r"\b[a-fA-F0-9]{64}\b", line)
        if not match:
            continue
        if normalized_name and normalized_name not in line.lower() and len(text.splitlines()) > 1:
            continue
        return match.group(0).lower()
    return ""


def _find_checksum_asset(assets: list[dict]) -> dict | None:
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if name.endswith((".sha256", ".sha256.txt", "sha256sums.txt", "checksums.txt")) or "checksum" in name:
            return asset
    return None


class UpdateManager:
    def __init__(self, current_version: str, repository: str = DEFAULT_GITHUB_REPOSITORY, download_dir: Path | None = None, timeout: float = 15.0) -> None:
        self.current_version = normalize_version(current_version)
        self.repository = repository.strip().strip("/")
        self.download_dir = download_dir or updates_dir()
        self.timeout = timeout

    @property
    def latest_release_url(self) -> str:
        if not self.repository or "/" not in self.repository:
            raise RuntimeError("GitHub update repository is not configured.")
        return f"https://api.github.com/repos/{self.repository}/releases/latest"

    def check_for_update(self) -> UpdateCheckResult:
        payload = _request_json(self.latest_release_url, self.timeout)
        release = self._release_from_payload(payload)
        return UpdateCheckResult(
            current_version=self.current_version,
            latest_version=release.version,
            update_available=is_newer_version(release.version, self.current_version),
            release=release,
        )

    def _release_from_payload(self, payload: dict) -> UpdateRelease:
        version = normalize_version(str(payload.get("tag_name") or payload.get("name") or ""))
        assets = payload.get("assets") or []
        if not isinstance(assets, list):
            assets = []
        installer = _find_installer_asset(assets)
        if not version:
            raise RuntimeError("GitHub release does not contain a version tag.")
        if not installer:
            raise RuntimeError("GitHub release does not contain a Windows installer asset.")
        installer_url = str(installer.get("browser_download_url") or "")
        installer_name = str(installer.get("name") or "")
        if not installer_url or not installer_name:
            raise RuntimeError("GitHub release installer asset is incomplete.")
        notes = str(payload.get("body") or "")
        sha256 = _extract_sha256_from_text(notes, installer_name)
        checksum_asset = _find_checksum_asset(assets)
        if not sha256 and checksum_asset:
            checksum_url = str(checksum_asset.get("browser_download_url") or "")
            if checksum_url:
                try:
                    sha256 = _extract_sha256_from_text(_request_text(checksum_url, self.timeout), installer_name)
                except Exception:
                    sha256 = ""
        return UpdateRelease(
            version=version,
            name=str(payload.get("name") or version),
            html_url=str(payload.get("html_url") or ""),
            installer_url=installer_url,
            installer_name=installer_name,
            notes=notes,
            published_at=str(payload.get("published_at") or ""),
            sha256=sha256,
        )

    def installer_path(self, release: UpdateRelease) -> Path:
        safe_name = re.sub(r"[^A-Za-z0-9._ ()-]", "_", release.installer_name).strip() or f"{APP_NAME} Setup-{release.version}.exe"
        return self.download_dir / safe_name

    def download_update(self, release: UpdateRelease, progress_callback=None) -> Path:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        target = self.installer_path(release)
        temporary = target.with_suffix(target.suffix + ".download")
        request = urllib.request.Request(release.installer_url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                hasher = hashlib.sha256()
                with temporary.open("wb") as file:
                    while True:
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        file.write(chunk)
                        hasher.update(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        digest = hasher.hexdigest().lower()
        if release.sha256 and digest != release.sha256.lower():
            temporary.unlink(missing_ok=True)
            raise RuntimeError("Downloaded installer checksum does not match the release checksum.")
        temporary.replace(target)
        return target
