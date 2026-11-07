from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from outward_app.core.models import AppSettings, ConnectionCollection, ConnectionProfile, normalize_language, normalize_theme, utc_now_iso
from outward_app.paths import connections_path, profiles_path, settings_path

STORE_LOCK = threading.RLock()


def atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp") as output:
            name = output.name
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


class JsonStore:
    def __init__(self, profiles_file: Path | None = None, settings_file: Path | None = None,
                 connections_file: Path | None = None) -> None:
        self.profiles_file = profiles_file or profiles_path()
        self.settings_file = settings_file or settings_path()
        self.connections_file = connections_file or (profiles_file.parent / "connections.json" if profiles_file else connections_path())

    def load_profiles(self) -> list[ConnectionProfile]:
        if not self.profiles_file.exists():
            return []
        data = json.loads(self.profiles_file.read_text(encoding="utf-8"))
        return [ConnectionProfile.from_dict(item) for item in data.get("profiles", [])]

    def save_profiles(self, profiles: list[ConnectionProfile]) -> None:
        self.profiles_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"profiles": [profile.to_dict() for profile in profiles]}
        with STORE_LOCK:
            atomic_write_json(self.profiles_file, data)

    def upsert_profile(self, profile: ConnectionProfile) -> list[ConnectionProfile]:
        with STORE_LOCK:
            return self._upsert_profile(profile)

    def _upsert_profile(self, profile: ConnectionProfile) -> list[ConnectionProfile]:
        profiles = self.load_profiles()
        for index, item in enumerate(profiles):
            if item.id == profile.id:
                profile.updated_at = utc_now_iso()
                profiles[index] = profile
                break
        else:
            profiles.insert(0, profile)
        self.save_profiles(profiles)
        return profiles

    def delete_profile(self, profile_id: str) -> list[ConnectionProfile]:
        with STORE_LOCK:
            profiles = [profile for profile in self.load_profiles() if profile.id != profile_id]
            self.save_profiles(profiles)
            return profiles

    def mark_used(self, profile_id: str) -> None:
        with STORE_LOCK:
            self._mark_used(profile_id)

    def _mark_used(self, profile_id: str) -> None:
        profiles = self.load_profiles()
        for profile in profiles:
            if profile.id == profile_id:
                profile.last_used_at = utc_now_iso()
                profile.updated_at = utc_now_iso()
                break
        self.save_profiles(profiles)

    def load_settings(self) -> AppSettings:
        data = json.loads(self.settings_file.read_text(encoding="utf-8")) if self.settings_file.exists() else {}
        if "launch_on_startup" not in data and self.connections_file.exists():
            collection = ConnectionCollection.from_dict(json.loads(self.connections_file.read_text(encoding="utf-8")))
            data["launch_on_startup"] = any(c.auto_connect for c in [collection.system, *collection.windows])
        return AppSettings.from_dict(data)

    def save_settings(self, settings: AppSettings) -> None:
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        with STORE_LOCK:
            atomic_write_json(self.settings_file, settings.to_dict())

    def save_theme(self, theme: str) -> None:
        """Persist appearance without committing the settings form's draft."""
        with STORE_LOCK:
            data = json.loads(self.settings_file.read_text(encoding="utf-8")) if self.settings_file.exists() else {}
            data["theme"] = normalize_theme(theme)
            atomic_write_json(self.settings_file, data)

    def save_language(self, language: str) -> None:
        """Persist language without applying unfinished network/startup settings."""
        with STORE_LOCK:
            data = json.loads(self.settings_file.read_text(encoding="utf-8")) if self.settings_file.exists() else {}
            data["language"] = normalize_language(language)
            atomic_write_json(self.settings_file, data)

    def load_connections(self, settings: AppSettings, profile_id: str = "") -> ConnectionCollection:
        with STORE_LOCK:
            if self.connections_file.exists():
                return ConnectionCollection.from_dict(json.loads(self.connections_file.read_text(encoding="utf-8")))
            # Back up before the first migration. Existing profiles/settings remain readable by older builds.
            for source in (self.profiles_file, self.settings_file):
                backup = source.with_name(source.name + ".pre-connections.bak")
                if source.exists() and not backup.exists():
                    shutil.copy2(source, backup)
            collection = ConnectionCollection()
            collection.system.profile_id = profile_id
            if profile_id:
                window = collection.add_window(profile_id, settings)
                window.auto_connect = settings.auto_connect_on_startup
                window.legacy_browser_dir = f"chrome_proxy_profile_{settings.socks_port}"
            self.save_connections(collection)
            return collection

    def save_connections(self, collection: ConnectionCollection) -> None:
        with STORE_LOCK:
            atomic_write_json(self.connections_file, collection.to_dict())
