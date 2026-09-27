from __future__ import annotations

import base64
import configparser
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from outward_app.core.vless import parse_vless_link


@dataclass(slots=True)
class ParsedConnection:
    protocol: str
    server: str
    port: int | None
    remark: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def protocol_label(self) -> str:
        labels = {
            "vless": "VLESS",
            "shadowsocks": "Shadowsocks",
            "wireguard": "WireGuard",
        }
        return labels.get(self.protocol, self.protocol.upper())


def _b64_decode(value: str) -> str:
    candidate = value.strip()
    padding = "=" * (-len(candidate) % 4)
    errors: list[Exception] = []
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            return decoder((candidate + padding).encode("ascii")).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    raise ValueError(f"Invalid base64 value: {errors[-1]}")


def detect_protocol(raw: str) -> str:
    value = raw.strip()
    lower = value.lower()
    if lower.startswith("vless://") or lower.startswith("vless\\://"):
        return "vless"
    if lower.startswith("ss://"):
        return "shadowsocks"
    if "[interface]" in lower and "[peer]" in lower:
        return "wireguard"
    raise ValueError("Unsupported connection profile format")


def parse_connection(raw: str) -> ParsedConnection:
    protocol = detect_protocol(raw)
    if protocol == "vless":
        parsed = parse_vless_link(raw)
        return ParsedConnection(
            protocol="vless",
            server=parsed["server"],
            port=parsed["port"],
            remark=parsed.get("remark") or "",
            data=parsed,
        )
    if protocol == "shadowsocks":
        return parse_shadowsocks_link(raw)
    if protocol == "wireguard":
        return parse_wireguard_config(raw)
    raise ValueError(f"Unsupported protocol: {protocol}")


def _parse_host_port(endpoint: str) -> tuple[str, int]:
    value = endpoint.strip()
    if not value:
        raise ValueError("Endpoint is missing")
    if value.startswith("["):
        match = re.match(r"^\[(?P<host>[^\]]+)\]:(?P<port>\d+)$", value)
        if not match:
            raise ValueError("Endpoint must include host and port")
        return match.group("host"), int(match.group("port"))
    host, separator, port_text = value.rpartition(":")
    if not separator or not host or not port_text:
        raise ValueError("Endpoint must include host and port")
    return host, int(port_text)


def parse_shadowsocks_link(link: str) -> ParsedConnection:
    parsed = urlparse(link.strip())
    if parsed.scheme.lower() != "ss":
        raise ValueError("The link must start with ss://")

    method = ""
    password = ""
    server = parsed.hostname or ""
    port = parsed.port

    if server and port:
        if parsed.password is not None:
            method = unquote(parsed.username or "")
            password = unquote(parsed.password)
        else:
            userinfo = unquote(parsed.username or "")
            if ":" not in userinfo:
                userinfo = _b64_decode(userinfo)
            method, separator, password = userinfo.partition(":")
            if not separator:
                raise ValueError("Shadowsocks user info must include method and password")
    else:
        payload = link.strip()[len("ss://") :]
        payload = payload.split("#", 1)[0].split("?", 1)[0]
        decoded = _b64_decode(payload)
        userinfo, separator, endpoint = decoded.rpartition("@")
        if not separator:
            raise ValueError("Shadowsocks link must include server")
        method, separator, password = userinfo.partition(":")
        if not separator:
            raise ValueError("Shadowsocks user info must include method and password")
        server, port = _parse_host_port(endpoint)

    if not method:
        raise ValueError("Shadowsocks method is missing")
    if not password:
        raise ValueError("Shadowsocks password is missing")
    if not server:
        raise ValueError("Shadowsocks server is missing")
    if port is None:
        raise ValueError("Shadowsocks server port is missing")

    query = parse_qs(parsed.query, keep_blank_values=True)
    data: dict[str, Any] = {
        "server": server,
        "port": port,
        "method": method,
        "password": password,
        "remark": unquote(parsed.fragment or ""),
    }
    for key in ("plugin", "plugin_opts", "network"):
        values = query.get(key)
        if values and values[0]:
            data[key] = values[0]

    return ParsedConnection(
        protocol="shadowsocks",
        server=server,
        port=port,
        remark=data["remark"],
        data=data,
    )


def parse_wireguard_config(text: str) -> ParsedConnection:
    parser = configparser.ConfigParser(strict=False)
    parser.optionxform = str  # type: ignore[method-assign]
    try:
        parser.read_string(text.strip())
    except configparser.Error as exc:
        raise ValueError(f"Invalid WireGuard config: {exc}") from exc

    if not parser.has_section("Interface") or not parser.has_section("Peer"):
        raise ValueError("WireGuard config must include [Interface] and [Peer]")

    interface = parser["Interface"]
    peer = parser["Peer"]
    private_key = interface.get("PrivateKey", "").strip()
    address = _split_csv(interface.get("Address", ""))
    public_key = peer.get("PublicKey", "").strip()
    endpoint = peer.get("Endpoint", "").strip()
    allowed_ips = _split_csv(peer.get("AllowedIPs", "0.0.0.0/0"))

    if not private_key:
        raise ValueError("WireGuard PrivateKey is missing")
    if not address:
        raise ValueError("WireGuard Address is missing")
    if not public_key:
        raise ValueError("WireGuard peer PublicKey is missing")

    server, port = _parse_host_port(endpoint)
    data: dict[str, Any] = {
        "address": address,
        "private_key": private_key,
        "peers": [
            {
                "address": server,
                "port": port,
                "public_key": public_key,
                "allowed_ips": allowed_ips,
            }
        ],
    }

    dns = _split_csv(interface.get("DNS", ""))
    if dns:
        data["dns"] = dns
    mtu = interface.get("MTU", "").strip()
    if mtu:
        data["mtu"] = int(mtu)
    preshared_key = peer.get("PresharedKey", "").strip()
    if preshared_key:
        data["peers"][0]["pre_shared_key"] = preshared_key
    keepalive = peer.get("PersistentKeepalive", "").strip()
    if keepalive:
        data["peers"][0]["persistent_keepalive_interval"] = int(keepalive)

    return ParsedConnection(
        protocol="wireguard",
        server=server,
        port=port,
        remark="WireGuard",
        data=data,
    )


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def protocol_label_for_link(raw: str) -> str:
    try:
        return parse_connection(raw).protocol_label
    except Exception:  # noqa: BLE001
        try:
            return detect_protocol(raw).upper()
        except Exception:  # noqa: BLE001
            return "PROFILE"


def sanitize_connection_error(message: str) -> str:
    sanitized = message
    secret_patterns = (
        r'("password"\s*:\s*")[^"]+(")',
        r'("private_key"\s*:\s*")[^"]+(")',
        r'("pre_shared_key"\s*:\s*")[^"]+(")',
        r"(PrivateKey\s*=\s*)\S+",
        r"(PresharedKey\s*=\s*)\S+",
    )
    for pattern in secret_patterns:
        sanitized = re.sub(pattern, lambda match: match.group(1) + "***" + (match.group(2) if match.lastindex and match.lastindex > 1 else ""), sanitized, flags=re.IGNORECASE)
    return sanitized

