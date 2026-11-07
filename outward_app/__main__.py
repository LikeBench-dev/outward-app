import sys


def main() -> int:
    if "--system-proxy-watchdog" in sys.argv:
        from outward_app.core.system_proxy import run_watchdog
        try:
            return run_watchdog(sys.argv[sys.argv.index("--system-proxy-watchdog") + 1])
        except (IndexError, OSError, ValueError):
            return 1
    if "--check-runtime" in sys.argv:
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from outward_app.ui.app import QApplication
        app = QApplication([])
        from outward_app.core.vpn_pipe import api
        api()
        import ssl
        ssl.create_default_context()
        return 0
    if "--uninstall-vpn-component" in sys.argv:
        from outward_app.core.vpn_pipe import service_status
        from outward_app.core.vpn_install import elevate_install
        if service_status()[0]:
            try:
                elevate_install(remove=True)
            except OSError:
                return 1
        return 0
    if "--vpn-service" in sys.argv:
        from outward_app.core.vpn_service import run_service
        return run_service()
    if "--install-vpn-service" in sys.argv or "--remove-vpn-service" in sys.argv:
        from outward_app.core.vpn_install import install, remove
        try:
            if "--remove-vpn-service" in sys.argv:
                remove(sys.argv[sys.argv.index("--remove-vpn-service") + 1])
            else:
                install(sys.argv[sys.argv.index("--install-vpn-service") + 1])
            return 0
        except Exception:
            return 1
    from outward_app.ui.app import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
