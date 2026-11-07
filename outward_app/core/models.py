from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
import re


LEGACY_DEFAULT_CUSTOM_DNS = "1.1.1.1, 8.8.8.8"
DEFAULT_HTTP_PORT = 27182
DEFAULT_SOCKS_PORT = 27183


def normalize_theme(value: Any) -> str:
    return value if isinstance(value, str) and value in {"light", "dark"} else "dark"


def normalize_language(value: Any) -> str:
    return value if isinstance(value, str) and value in {"ru", "en"} else "ru"

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ConnectionProfile:
    id: str
    name: str
    link: str
    protocol: str = ""
    remark: str = ""
    server: str = ""
    country_code: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    last_used_at: str | None = None

    @classmethod
    def create(
        cls,
        name: str,
        link: str,
        remark: str = "",
        server: str = "",
        country_code: str = "",
        protocol: str = "",
    ) -> "ConnectionProfile":
        return cls(
            id=str(uuid4()),
            name=name,
            link=link,
            protocol=protocol,
            remark=remark,
            server=server,
            country_code=country_code,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConnectionProfile":
        return cls(
            id=str(data.get("id") or uuid4()),
            name=str(data.get("name") or "Connection"),
            link=str(data.get("link") or ""),
            protocol=str(data.get("protocol") or ""),
            remark=str(data.get("remark") or ""),
            server=str(data.get("server") or ""),
            country_code=str(data.get("country_code") or ""),
            created_at=str(data.get("created_at") or utc_now_iso()),
            updated_at=str(data.get("updated_at") or utc_now_iso()),
            last_used_at=data.get("last_used_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AppSettings:
    preferred_browser: str = "auto"
    http_port: int = DEFAULT_HTTP_PORT
    socks_port: int = DEFAULT_SOCKS_PORT
    launch_url: str = "example.com"
    launch_sites: list[str] = field(default_factory=lambda: ["example.com"])
    auto_open_browser: bool = False
    auto_connect_on_startup: bool = False
    launch_on_startup: bool = False
    disable_browser_extensions: bool = False
    stop_existing_sing_box: bool = True
    minimize_to_tray: bool = False
    auto_update_app: bool = False
    language: str = "ru"
    custom_dns: str = "1.1.1.1, 8.8.8.8"
    theme: str = "dark"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        legacy_port = int(data.get("default_port") or DEFAULT_HTTP_PORT)
        http_port = int(data.get("http_port") or legacy_port)
        socks_port = int(data.get("socks_port") or (http_port + 1))
        launch_url = str(data.get("launch_url") or "example.com").strip() or "example.com"
        raw_launch_sites = data.get("launch_sites") or ["example.com"]
        launch_sites = []
        if isinstance(raw_launch_sites, list):
            for item in raw_launch_sites:
                site = str(item).strip()
                if site and site not in launch_sites:
                    launch_sites.append(site)
        if launch_url not in launch_sites:
            launch_sites.insert(0, launch_url)
        return cls(
            preferred_browser=str(data.get("preferred_browser") or "auto"),
            http_port=http_port,
            socks_port=socks_port,
            launch_url=launch_url,
            launch_sites=launch_sites,
            auto_open_browser=bool(data.get("auto_open_browser", data.get("auto_open_discord", False))),
            auto_connect_on_startup=bool(data.get("auto_connect_on_startup", False)),
            launch_on_startup=bool(data.get("launch_on_startup", data.get("auto_connect_on_startup", False))),
            disable_browser_extensions=bool(data.get("disable_browser_extensions", False)),
            stop_existing_sing_box=bool(data.get("stop_existing_sing_box", True)),
            minimize_to_tray=bool(data.get("minimize_to_tray", False)),
            auto_update_app=bool(data.get("auto_update_app", data.get("automatic_app_updates", False))),
            language=normalize_language(data.get("language")),
            custom_dns=str(data.get("custom_dns") or "1.1.1.1, 8.8.8.8"),
            theme=normalize_theme(data.get("theme")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def default_port(self) -> int:
        return self.http_port

    @property
    def auto_open_discord(self) -> bool:
        return self.auto_open_browser


@dataclass(slots=True)
class RuntimeState:
    profile_id: str
    profile_name: str
    http_port: int
    socks_port: int
    http_proxy_url: str
    socks_proxy_url: str
    server: str = ""
    server_port: int = 0
    protocol: str = "vless"
    protocol_label: str = "VLESS"
    started_at: str = field(default_factory=utc_now_iso)
    connection_id: str = ""
    country_code: str = ""


@dataclass(slots=True)
class SavedConnection:
    """Portable user intent. Process handles and Qt objects never belong here."""

    id: str
    kind: str = "window"
    number: int = 0
    profile_id: str = ""
    http_port: int = DEFAULT_HTTP_PORT
    socks_port: int = DEFAULT_SOCKS_PORT
    fixed_ports: bool = False
    launch_url: str = "example.com"
    auto_open_browser: bool = False
    auto_connect: bool = False
    legacy_browser_dir: str = ""
    system_mode: str = "tun"

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.id):
            raise ValueError("Некорректный идентификатор подключения")
        if self.kind not in {"system", "window"}:
            raise ValueError("Неизвестный тип подключения")
        if (not isinstance(self.system_mode, str) or self.system_mode not in {"tun", "proxy"}
                or (self.kind == "window" and self.system_mode != "tun")):
            raise ValueError("Неизвестный режим системного подключения")
        if not isinstance(self.profile_id, str) or not isinstance(self.launch_url, str):
            raise ValueError("Некорректные параметры подключения")
        if any(not isinstance(value, bool) for value in (self.fixed_ports, self.auto_open_browser, self.auto_connect)):
            raise ValueError("Некорректные переключатели подключения")
        if self.kind == "window" or self.system_mode == "proxy":
            if any(type(value) is not int for value in (self.number, self.http_port, self.socks_port)):
                raise ValueError("Номер окна и порты должны быть целыми числами")
            if self.kind == "window" and self.number < 1:
                raise ValueError("Номер окна должен быть положительным")
            if not (1024 <= self.http_port <= 65535 and 1024 <= self.socks_port <= 65535):
                raise ValueError("Порт должен быть от 1024 до 65535")
            if self.http_port == self.socks_port:
                raise ValueError("HTTP и SOCKS5 должны использовать разные порты")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SavedConnection":
        fields = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in fields})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ConnectionCollection:
    system: SavedConnection = field(default_factory=lambda: SavedConnection(id="system", kind="system"))
    windows: list[SavedConnection] = field(default_factory=list)
    next_number: int = 1
    schema_version: int = 1

    def add_window(self, profile_id: str, settings: AppSettings) -> SavedConnection:
        number = self.next_number
        connection = SavedConnection(
            id=str(uuid4()), number=number, profile_id=profile_id,
            http_port=settings.http_port, socks_port=settings.socks_port,
            launch_url=settings.launch_url, auto_open_browser=settings.auto_open_browser,
        )
        self.next_number += 1
        self.windows.append(connection)
        return connection

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "next_number": self.next_number,
                "system": self.system.to_dict(), "windows": [item.to_dict() for item in self.windows]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConnectionCollection":
        if data.get("schema_version") != 1:
            raise ValueError("Версия connections.json не поддерживается. Данные не изменены.")
        system = SavedConnection.from_dict(data["system"])
        windows = [SavedConnection.from_dict(item) for item in data["windows"]]
        if system.id != "system" or system.kind != "system" or any(item.kind != "window" for item in windows):
            raise ValueError("Некорректный список подключений")
        if len({item.id for item in [system, *windows]}) != len(windows) + 1:
            raise ValueError("Повторяющиеся идентификаторы подключений")
        if len({item.number for item in windows}) != len(windows):
            raise ValueError("Повторяющиеся номера окон")
        return cls(system, windows, max(int(data["next_number"]), max((w.number for w in windows), default=0) + 1))

