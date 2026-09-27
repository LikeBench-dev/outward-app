from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


LEGACY_DEFAULT_CUSTOM_DNS = "1.1.1.1, 8.8.8.8"
DEFAULT_HTTP_PORT = 27182
DEFAULT_SOCKS_PORT = 27183

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
    disable_browser_extensions: bool = False
    stop_existing_sing_box: bool = True
    minimize_to_tray: bool = False
    auto_update_app: bool = False
    language: str = "ru"
    custom_dns: str = "1.1.1.1, 8.8.8.8"

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
            disable_browser_extensions=bool(data.get("disable_browser_extensions", False)),
            stop_existing_sing_box=bool(data.get("stop_existing_sing_box", True)),
            minimize_to_tray=bool(data.get("minimize_to_tray", False)),
            auto_update_app=bool(data.get("auto_update_app", data.get("automatic_app_updates", False))),
            language=str(data.get("language") or "ru"),
            custom_dns=str(data.get("custom_dns") or "1.1.1.1, 8.8.8.8"),
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
    protocol: str = "vless"
    protocol_label: str = "VLESS"
    started_at: str = field(default_factory=utc_now_iso)



