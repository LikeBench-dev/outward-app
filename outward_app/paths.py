import os
import sys
from pathlib import Path

from outward_app.app_info import APP_NAME


APP_DATA_DIR_NAME = ''.join(APP_NAME.split())


def source_root() -> Path:
    return Path(__file__).resolve().parents[1]


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return source_root()


def bundled_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", app_dir())).resolve()


def asset_path(name: str) -> Path:
    bundled_asset = bundled_dir() / "assets" / name
    if bundled_asset.exists():
        return bundled_asset
    return app_dir() / "assets" / name


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        path = Path(base) / APP_DATA_DIR_NAME
    else:
        path = Path.home() / f".{APP_DATA_DIR_NAME.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return app_data_dir() / "config.json"


def log_path() -> Path:
    return app_data_dir() / "sing-box.log"

def previous_log_path() -> Path:
    return app_data_dir() / "sing-box.log.1"


def profiles_path() -> Path:
    return app_data_dir() / "profiles.json"


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def sing_box_sessions_path() -> Path:
    return app_data_dir() / "sing-box-sessions.json"


def updates_dir() -> Path:
    path = app_data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path
