from __future__ import annotations

import re
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

QUERY_KEYS = (
    "encryption",
    "flow",
    "fp",
    "fingerprint",
    "pbk",
    "public_key",
    "security",
    "sid",
    "short_id",
    "sni",
    "server_name",
    "spx",
    "type",
    "alpn",
    "path",
    "host",
    "serviceName",
)
NETWORK_TYPES = ("httpupgrade", "grpc", "tcp", "ws", "http", "quic")


def require_value(name: str, value: Optional[str]) -> str:
    if not value:
        raise ValueError(f"Required VLESS value is missing: {name}")
    return value


def first_query_value(query: dict[str, list[str]], *names: str, default: Optional[str] = None) -> Optional[str]:
    for name in names:
        values = query.get(name)
        if values and values[0] != "":
            return values[0]
    return default


def fix_missing_userinfo_separator(link: str) -> str:
    if not link.lower().startswith("vless://"):
        return link

    rest = link[len("vless://") :]
    authority_end = len(rest)
    for separator in ("?", "#", "/"):
        index = rest.find(separator)
        if index != -1:
            authority_end = min(authority_end, index)

    authority = rest[:authority_end]
    if "@" in authority:
        return link

    match = re.match(
        r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(.+)$",
        rest,
    )
    if not match:
        return link

    return f"vless://{match.group(1)}@{match.group(2)}"


def parse_query_loose(query: str) -> tuple[dict[str, list[str]], str]:
    if not query:
        return {}, ""

    query_keys_pattern = "|".join(re.escape(key) for key in sorted(QUERY_KEYS, key=len, reverse=True))
    matches = list(re.finditer(rf"(?i)(?:^|&)?({query_keys_pattern})=", query))
    if not matches:
        return parse_qs(query, keep_blank_values=True), ""

    parsed: dict[str, list[str]] = {}
    inferred_fragment = ""

    for index, match in enumerate(matches):
        key = match.group(1)
        value_start = match.end()
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(query)
        value = query[value_start:value_end].lstrip("&")

        if key.lower() == "type":
            for network_type in NETWORK_TYPES:
                if value.lower().startswith(network_type):
                    tail = value[len(network_type) :]
                    value = network_type
                    if tail and not inferred_fragment:
                        inferred_fragment = tail.lstrip("#&")
                    break

        parsed.setdefault(key, []).append(value)

    return parsed, inferred_fragment


def parse_vless_link(link: str) -> dict:
    fixed_link = fix_missing_userinfo_separator(link.strip().replace("vless\\://", "vless://"))
    parsed = urlparse(fixed_link)
    if parsed.scheme.lower() != "vless":
        raise ValueError("The link must start with vless://")

    uuid = require_value("UUID", unquote(parsed.username or ""))
    server = require_value("server/IP", parsed.hostname)
    port = parsed.port
    if port is None:
        raise ValueError("VLESS server port is missing")

    query, inferred_fragment = parse_query_loose(parsed.query)

    public_key = first_query_value(query, "pbk", "public_key")
    short_id = first_query_value(query, "sid", "short_id", default="")
    server_name = first_query_value(query, "sni", "server_name", default=server)
    fingerprint = first_query_value(query, "fp", "fingerprint", default="chrome")
    flow = first_query_value(query, "flow")
    encryption = first_query_value(query, "encryption", default="none")

    require_value("public_key/pbk", public_key)

    return {
        "uuid": uuid,
        "server": server,
        "port": port,
        "public_key": public_key,
        "short_id": short_id or "",
        "server_name": server_name,
        "fingerprint": fingerprint or "chrome",
        "flow": flow,
        "encryption": encryption or "none",
        "remark": unquote(parsed.fragment or inferred_fragment or ""),
    }
