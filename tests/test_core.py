import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from outward_app.core.browser import browser_launch_args, normalize_launch_url
from outward_app.core.connections import (
    detect_protocol,
    parse_connection,
    parse_shadowsocks_link,
    parse_wireguard_config,
    sanitize_connection_error,
)
from outward_app.core.models import AppSettings, ConnectionProfile, DEFAULT_HTTP_PORT, DEFAULT_SOCKS_PORT
from outward_app.core.singbox import (
    SingBoxManager,
    build_sing_box_config,
    is_port_open,
    rotate_logs_on_app_start,
    sing_box_process_uses_outward_config,
    sing_box_session_matches_process,
    stop_managed_sing_box_processes,
)
from outward_app.core.storage import JsonStore
from outward_app.core.updater import UpdateManager, is_newer_version
from outward_app.core.vless import parse_vless_link


VLESS_LINK = (
    "vless://123e4567-e89b-12d3-a456-426614174000@example.com:443"
    "?encryption=none&security=reality&sni=example.com&fp=chrome"
    "&pbk=publickey&sid=abcd&flow=xtls-rprx-vision&type=tcp#Main"
)
SHADOWSOCKS_LINK = "ss://YWVzLTI1Ni1nY206c2VjcmV0@example.net:8388#SSMain"
WIREGUARD_CONFIG = """
[Interface]
PrivateKey = privatekey=
Address = 10.2.0.2/32
DNS = 1.1.1.1
MTU = 1408

[Peer]
PublicKey = publickey=
PresharedKey = preshared=
Endpoint = wg.example.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""


class CoreTests(unittest.TestCase):
    def test_parse_vless_link(self):
        parsed = parse_vless_link(VLESS_LINK)
        self.assertEqual(parsed["uuid"], "123e4567-e89b-12d3-a456-426614174000")
        self.assertEqual(parsed["server"], "example.com")
        self.assertEqual(parsed["port"], 443)
        self.assertEqual(parsed["public_key"], "publickey")
        self.assertEqual(parsed["remark"], "Main")

    def test_detect_protocol(self):
        self.assertEqual(detect_protocol(VLESS_LINK), "vless")
        self.assertEqual(detect_protocol(SHADOWSOCKS_LINK), "shadowsocks")
        self.assertEqual(detect_protocol(WIREGUARD_CONFIG), "wireguard")

    def test_parse_connection_wraps_vless(self):
        parsed = parse_connection(VLESS_LINK)
        self.assertEqual(parsed.protocol, "vless")
        self.assertEqual(parsed.server, "example.com")
        self.assertEqual(parsed.protocol_label, "VLESS")

    def test_parse_shadowsocks_link(self):
        parsed = parse_shadowsocks_link(SHADOWSOCKS_LINK)
        self.assertEqual(parsed.protocol, "shadowsocks")
        self.assertEqual(parsed.server, "example.net")
        self.assertEqual(parsed.port, 8388)
        self.assertEqual(parsed.data["method"], "aes-256-gcm")
        self.assertEqual(parsed.data["password"], "secret")
        self.assertEqual(parsed.remark, "SSMain")

    def test_parse_wireguard_config(self):
        parsed = parse_wireguard_config(WIREGUARD_CONFIG)
        self.assertEqual(parsed.protocol, "wireguard")
        self.assertEqual(parsed.server, "wg.example.com")
        self.assertEqual(parsed.port, 51820)
        self.assertEqual(parsed.data["address"], ["10.2.0.2/32"])
        self.assertEqual(parsed.data["peers"][0]["allowed_ips"], ["0.0.0.0/0", "::/0"])
        self.assertEqual(parsed.data["peers"][0]["persistent_keepalive_interval"], 25)

    def test_build_sing_box_config(self):
        parsed = parse_vless_link(VLESS_LINK)
        config = build_sing_box_config(parsed, 10810, 10811, "1.1.1.1, 8.8.8.8")
        self.assertEqual(config["inbounds"][0]["type"], "http")
        self.assertEqual(config["inbounds"][0]["listen_port"], 10810)
        self.assertEqual(config["inbounds"][1]["type"], "socks")
        self.assertEqual(config["inbounds"][1]["listen_port"], 10811)
        self.assertEqual(config["outbounds"][0]["server"], "example.com")
        self.assertEqual(config["outbounds"][0]["tls"]["reality"]["short_id"], "abcd")
        self.assertEqual(config["dns"]["servers"][0]["type"], "udp")
        self.assertEqual(config["dns"]["servers"][0]["server"], "1.1.1.1")
        self.assertEqual(config["route"]["final"], "proxy")
        self.assertEqual(config["route"]["default_domain_resolver"], "custom-dns-0")

    def test_build_sing_box_config_keeps_mixed_inbound_compatibility(self):
        parsed = parse_vless_link(VLESS_LINK)
        config = build_sing_box_config(parsed, 10808)
        self.assertEqual(config["inbounds"][0]["type"], "mixed")
        self.assertEqual(config["inbounds"][0]["listen_port"], 10808)

    def test_build_sing_box_config_for_shadowsocks(self):
        parsed = parse_connection(SHADOWSOCKS_LINK)
        config = build_sing_box_config(parsed, 10810, 10811)
        self.assertEqual(config["outbounds"][0]["type"], "shadowsocks")
        self.assertEqual(config["outbounds"][0]["server"], "example.net")
        self.assertEqual(config["outbounds"][0]["server_port"], 8388)
        self.assertEqual(config["outbounds"][0]["method"], "aes-256-gcm")

    def test_build_sing_box_config_for_wireguard_endpoint(self):
        parsed = parse_connection(WIREGUARD_CONFIG)
        config = build_sing_box_config(parsed, 10810, 10811, "")
        self.assertEqual(config["endpoints"][0]["type"], "wireguard")
        self.assertEqual(config["endpoints"][0]["tag"], "proxy")
        self.assertEqual(config["endpoints"][0]["peers"][0]["address"], "wg.example.com")
        self.assertEqual(config["route"]["final"], "proxy")
        self.assertEqual(config["route"]["default_domain_resolver"], "custom-dns-0")
        self.assertEqual(config["dns"]["servers"][0]["type"], "udp")

    def test_sanitize_connection_error_masks_secrets(self):
        message = '{"password":"secret-value","private_key":"private-value","pre_shared_key":"psk-value"}\nPrivateKey = wg-private\nPresharedKey = wg-psk'
        sanitized = sanitize_connection_error(message)
        self.assertNotIn("secret-value", sanitized)
        self.assertNotIn("private-value", sanitized)
        self.assertNotIn("psk-value", sanitized)
        self.assertNotIn("wg-private", sanitized)
        self.assertNotIn("wg-psk", sanitized)
        self.assertIn("***", sanitized)

    def test_settings_loads_legacy_keys(self):
        settings = AppSettings.from_dict({"default_port": 10808, "auto_open_discord": False})
        self.assertEqual(settings.http_port, 10808)
        self.assertEqual(settings.socks_port, 10809)
        self.assertFalse(settings.auto_open_browser)
        self.assertFalse(settings.auto_open_discord)
        self.assertFalse(settings.auto_connect_on_startup)
        self.assertFalse(settings.disable_browser_extensions)

    def test_settings_loads_default_browser_toggles_off(self):
        settings = AppSettings.from_dict({})
        self.assertEqual(settings.http_port, DEFAULT_HTTP_PORT)
        self.assertEqual(settings.socks_port, DEFAULT_SOCKS_PORT)
        self.assertFalse(settings.auto_open_browser)
        self.assertFalse(settings.auto_connect_on_startup)
        self.assertFalse(settings.disable_browser_extensions)

    def test_settings_loads_auto_connect_on_startup(self):
        settings = AppSettings.from_dict({"auto_connect_on_startup": True})
        self.assertTrue(settings.auto_connect_on_startup)

    def test_settings_loads_disable_browser_extensions(self):
        settings = AppSettings.from_dict({"disable_browser_extensions": True})
        self.assertTrue(settings.disable_browser_extensions)

    def test_normalize_launch_url(self):
        self.assertEqual(normalize_launch_url("example.com"), "https://example.com")
        self.assertEqual(normalize_launch_url("https://example.com"), "https://example.com")

    def test_browser_launch_args_can_disable_extensions(self):
        args = browser_launch_args("chrome.exe", Path("profile"), 10811, "https://example.com", True)
        self.assertIn("--disable-extensions", args)
        self.assertLess(args.index("--disable-extensions"), args.index("https://example.com"))

    def test_json_store_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = JsonStore(tmp_path / "profiles.json", tmp_path / "settings.json")
            profile = ConnectionProfile.create("Main", VLESS_LINK, remark="Main", server="example.com", protocol="vless")
            store.upsert_profile(profile)
            loaded = store.load_profiles()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].name, "Main")
            self.assertEqual(loaded[0].server, "example.com")
            self.assertEqual(loaded[0].protocol, "vless")

    def test_connection_profile_loads_legacy_without_protocol(self):
        profile = ConnectionProfile.from_dict({"name": "Legacy", "link": VLESS_LINK})
        self.assertEqual(profile.protocol, "")
        self.assertEqual(profile.name, "Legacy")


    def test_sing_box_session_match_requires_outward_metadata(self):
        session = {
            "pid": "1234",
            "creation_date": "2026-09-26T12:00:00.0000000+03:00",
            "config_path": r"C:\Users\user\AppData\Local\OutwardApp\config.json",
            "sing_box": r"C:\Program Files\Outward App\sing-box.exe",
        }
        process = {
            "pid": "1234",
            "creation_date": "2026-09-26T12:00:00.0000000+03:00",
            "command_line": r'"C:\Program Files\Outward App\sing-box.exe" run -c "C:\Users\user\AppData\Local\OutwardApp\config.json"',
            "executable_path": r"C:\Program Files\Outward App\sing-box.exe",
        }
        self.assertTrue(sing_box_session_matches_process(session, process))

        reused_pid = dict(process, creation_date="2026-09-26T12:05:00.0000000+03:00")
        self.assertFalse(sing_box_session_matches_process(session, reused_pid))

        user_process = dict(process, command_line=r'"C:\Tools\sing-box.exe" run -c "C:\Users\user\own-config.json"')
        self.assertFalse(sing_box_session_matches_process(session, user_process))

    def test_sing_box_process_uses_outward_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / 'config.json'
            process = {
                'pid': '4321',
                'command_line': f'"C:\\Program Files\\Outward App\\sing-box.exe" run -c "{config_file}"',
            }

            with patch('outward_app.core.singbox.config_path', return_value=config_file):
                self.assertTrue(sing_box_process_uses_outward_config(process))
                self.assertFalse(sing_box_process_uses_outward_config({'pid': '4322', 'command_line': r'sing-box run -c C:\Users\user\own-config.json'}))

    def test_stop_managed_sing_box_processes_finds_outward_config_without_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / 'config.json'
            process = {
                'pid': '4321',
                'creation_date': '2026-09-27T12:00:00.0000000+03:00',
                'executable_path': r'C:\Program Files\Outward App\sing-box.exe',
                'command_line': f'"C:\\Program Files\\Outward App\\sing-box.exe" run -c "{config_file}"',
            }

            with (
                patch('outward_app.core.singbox.config_path', return_value=config_file),
                patch('outward_app.core.singbox._read_sing_box_sessions', return_value=[]),
                patch('outward_app.core.singbox.running_sing_box_processes', side_effect=[[process], [], []]),
                patch('outward_app.core.singbox.stop_pids', return_value=[]) as stop_pids,
                patch('outward_app.core.singbox._write_sing_box_sessions') as write_sessions,
            ):
                stopped_pids, errors = stop_managed_sing_box_processes()

            self.assertEqual(stopped_pids, ['4321'])
            self.assertEqual(errors, [])
            stop_pids.assert_called_once_with(['4321'])
            write_sessions.assert_called_once_with([])

    def test_manager_stop_waits_for_tracked_ports_to_close(self):
        class DummyProcess:
            pid = 4321

            def __init__(self):
                self.terminated = False
                self.waited = False

            def poll(self):
                return 0 if self.waited else None

            def terminate(self):
                self.terminated = True

            def wait(self, timeout):
                self.waited = True
                return 0

        process = DummyProcess()
        manager = SingBoxManager()
        manager.process = process
        manager.ports = [10810, 10811]

        with (
            patch('outward_app.core.singbox.wait_for_ports_to_close', return_value=[]) as wait_ports,
            patch('outward_app.core.singbox.unregister_managed_sing_box_process') as unregister,
        ):
            manager.stop()

        self.assertTrue(process.terminated)
        wait_ports.assert_called_once_with([10810, 10811])
        unregister.assert_called_once_with(4321)
        self.assertEqual(manager.ports, [])

    def test_rotate_logs_on_app_start_keeps_current_and_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            current_log = tmp_path / "sing-box.log"
            previous_log = tmp_path / "sing-box.log.1"
            current_log.write_text("old current log", encoding="utf-8")
            previous_log.write_text("older previous log", encoding="utf-8")

            with (
                patch("outward_app.core.singbox.log_path", return_value=current_log),
                patch("outward_app.core.singbox.previous_log_path", return_value=previous_log),
            ):
                rotate_logs_on_app_start()

            self.assertEqual(previous_log.read_text(encoding="utf-8"), "old current log")
            current_text = current_log.read_text(encoding="utf-8")
            self.assertIn("Outward App session started", current_text)
            self.assertNotIn("old current log", current_text)

            current_log.write_text("second session log", encoding="utf-8")
            with (
                patch("outward_app.core.singbox.log_path", return_value=current_log),
                patch("outward_app.core.singbox.previous_log_path", return_value=previous_log),
            ):
                rotate_logs_on_app_start()

            self.assertEqual(previous_log.read_text(encoding="utf-8"), "second session log")
            self.assertIn("Outward App session started", current_log.read_text(encoding="utf-8"))



    def test_is_port_open_checks_bind_availability_without_proxy_connection(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]

            with patch("outward_app.core.singbox.socket.create_connection") as create_connection:
                self.assertTrue(is_port_open(port))

            create_connection.assert_not_called()
    def test_wait_for_port_checks_listener_without_proxy_connection(self):
        class DummyProcess:
            def poll(self):
                return None

        manager = SingBoxManager()
        manager.process = DummyProcess()

        with (
            patch("outward_app.core.singbox.tcp_port_has_listener", return_value=True) as listener,
            patch("outward_app.core.singbox.socket.create_connection") as create_connection,
        ):
            manager.wait_for_port(10810, timeout=0.1)

        listener.assert_called_once_with(10810)
        create_connection.assert_not_called()
    def test_update_version_comparison(self):
        self.assertTrue(is_newer_version("0.1.8", "0.1.7"))
        self.assertTrue(is_newer_version("v1.0.0", "0.9.9"))
        self.assertFalse(is_newer_version("0.1.7", "0.1.7"))
        self.assertFalse(is_newer_version("0.1.7", "0.1.8"))

    def test_update_manager_parses_github_release(self):
        checksum = "a" * 64
        payload = {
            "tag_name": "v0.2.0",
            "name": "Outward App 0.2.0",
            "html_url": "https://github.com/LikeBench-dev/outward-app/releases/tag/v0.2.0",
            "body": f"SHA256: {checksum}  Outward App Setup-0.2.0.exe",
            "published_at": "2026-09-26T00:00:00Z",
            "assets": [
                {
                    "name": "Outward App Setup-0.2.0.exe",
                    "browser_download_url": "https://example.com/Outward%20App%20Setup-0.2.0.exe",
                }
            ],
        }
        manager = UpdateManager("0.1.7", repository="LikeBench-dev/outward-app")
        release = manager._release_from_payload(payload)
        self.assertEqual(release.version, "0.2.0")
        self.assertEqual(release.installer_name, "Outward App Setup-0.2.0.exe")
        self.assertEqual(release.sha256, checksum)
        self.assertTrue(is_newer_version(release.version, manager.current_version))


if __name__ == "__main__":
    unittest.main()




