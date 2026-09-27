from __future__ import annotations

import json
from pathlib import Path

from outward_app.core.models import AppSettings, ConnectionProfile, utc_now_iso
from outward_app.paths import profiles_path, settings_path


class JsonStore:
    def __init__(self, profiles_file: Path | None = None, settings_file: Path | None = None) -> None:
        self.profiles_file = profiles_file or profiles_path()
        self.settings_file = settings_file or settings_path()

    def load_profiles(self) -> list[ConnectionProfile]:
        if not self.profiles_file.exists():
            return []
        data = json.loads(self.profiles_file.read_text(encoding="utf-8"))
        return [ConnectionProfile.from_dict(item) for item in data.get("profiles", [])]

    def save_profiles(self, profiles: list[ConnectionProfile]) -> None:
        self.profiles_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"profiles": [profile.to_dict() for profile in profiles]}
        self.profiles_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert_profile(self, profile: ConnectionProfile) -> list[ConnectionProfile]:
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
        profiles = [profile for profile in self.load_profiles() if profile.id != profile_id]
        self.save_profiles(profiles)
        return profiles

    def mark_used(self, profile_id: str) -> None:
        profiles = self.load_profiles()
        for profile in profiles:
            if profile.id == profile_id:
                profile.last_used_at = utc_now_iso()
                profile.updated_at = utc_now_iso()
                break
        self.save_profiles(profiles)

    def load_settings(self) -> AppSettings:
        if not self.settings_file.exists():
            return AppSettings()
        data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        return AppSettings.from_dict(data)

    def save_settings(self, settings: AppSettings) -> None:
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        self.settings_file.write_text(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
