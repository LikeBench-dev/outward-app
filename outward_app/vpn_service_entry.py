"""Dedicated onedir service executable: no GUI and no privileged onefile extraction."""
import sys


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == '--signal-child':
        from outward_app.core.windows_process import signal_console_child
        raise SystemExit(signal_console_child(int(sys.argv[2]), int(sys.argv[3])))
    if "--check-runtime" in sys.argv:
        from outward_app.core.vpn_pipe import api
        from outward_app.core.network import ssl
        api()
        ssl.create_default_context()
        raise SystemExit(0)
    from outward_app.core.vpn_service import run_service
    raise SystemExit(run_service())
