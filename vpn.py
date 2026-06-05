import argparse
import os
import signal
import subprocess
import sys
import threading
from utils import log, setup_log, current_ip
from proxy_pool import ProxyPool

PLATFORM = sys.platform

def detect_default_mode() -> str:
    if PLATFORM == "linux":
        return "tun"
    return "socks"

def set_system_proxy(host: str, port: int, enabled: bool):
    if PLATFORM == "darwin":
        for svc in _mac_network_services():
            state = "on" if enabled else "off"
            subprocess.run(
                ["networksetup", "-setsocksfirewallproxystate", svc, state],
                check=False, capture_output=True
            )
            if enabled:
                subprocess.run(
                    ["networksetup", "-setsocksfirewallproxy", svc, host, str(port)],
                    check=False, capture_output=True
                )
        log.info("macOS system proxy %s", "enabled" if enabled else "disabled")
    elif PLATFORM == "win32":
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                              r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                              0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"socks={host}:{port}")
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        log.info("Windows system proxy %s", "enabled" if enabled else "disabled")

def _mac_network_services() -> list[str]:
    r = subprocess.run(
        ["networksetup", "-listallnetworkservices"],
        capture_output=True, text=True, check=False
    )
    services = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("*") and line != "An asterisk (*) denotes that a network service is disabled.":
            services.append(line)
    return services

def main():
    ap = argparse.ArgumentParser(description="GhostVPN — rotating-IP VPN via SOCKS5 proxy pool")
    ap.add_argument("--mode", choices=["tun", "socks"], default=detect_default_mode(),
                    help=f"VPN mode (default: {detect_default_mode()})")
    ap.add_argument("--interval", type=int, default=180, help="IP rotation interval in seconds (default: 180)")
    ap.add_argument("--verbose", action="store_true", help="verbose output")
    ap.add_argument("--proxies", type=str, help="path to custom proxy list (one per line, host:port)")
    ap.add_argument("--proxy-port", type=int, default=1080,
                    help="Local SOCKS proxy port (default: 1080, socks mode only)")
    ap.add_argument("--sys-proxy", action="store_true",
                    help="Automatically set system proxy settings (macOS/Windows)")
    args = ap.parse_args()

    if args.mode == "tun" and PLATFORM != "linux":
        log.error("TUN mode is Linux-only. Use --mode socks on this platform.")
        sys.exit(1)

    setup_log(args.verbose)
    pool = ProxyPool(interval=args.interval)

    log.info("Building proxy pool...")
    if args.proxies:
        pool.load_file(args.proxies)
    else:
        pool.refresh()

    if pool.get() is None:
        log.error("No working proxies found. Exiting.")
        sys.exit(1)

    ip = current_ip(pool.get())
    log.info("Current IP through proxy: %s", ip or "unknown")

    def on_switch(proxy):
        ip = current_ip(proxy)
        log.info("New IP: %s", ip or "unknown")
    pool.on_switch.append(on_switch)

    if args.mode == "tun":
        from tun import TunManager
        from transproxy import TransProxy

        tun = TunManager()
        try:
            tun.create()
        except Exception as e:
            log.error("Failed to create tun: %s", e)
            sys.exit(1)
        try:
            tun.setup_routing()
            tun.setup_iptables()
        except Exception as e:
            log.error("Failed to set up routing/iptables: %s", e)
            tun.cleanup()
            sys.exit(1)
        log.info("Routing and iptables configured")

        proxy = TransProxy(pool, bind_port=args.proxy_port)
        proxy.start()
        srv_thread = threading.Thread(target=proxy.serve, daemon=True)
        srv_thread.start()

        pool.start_auto_rotate()

        log.info("TUN mode — full system VPN running. Rotating IP every %d s. Ctrl+C to stop.", args.interval)

        stop = threading.Event()

        def cleanup(*_):
            log.info("Shutting down...")
            pool.stop()
            proxy.stop()
            tun.cleanup()
            stop.set()

        signal.signal(signal.SIGINT, cleanup)
        signal.signal(signal.SIGTERM, cleanup)

        try:
            stop.wait()
        except KeyboardInterrupt:
            cleanup()

    else:
        from local_proxy import LocalSocksProxy

        local = LocalSocksProxy(pool, port=args.proxy_port)
        local.start()
        srv_thread = threading.Thread(target=local.serve, daemon=True)
        srv_thread.start()

        if args.sys_proxy:
            set_system_proxy("127.0.0.1", args.proxy_port, enabled=True)

        pool.start_auto_rotate()
        log.info("SOCKS mode — proxy on 127.0.0.1:%d. Rotating IP every %d s. Ctrl+C to stop.",
                 args.proxy_port, args.interval)

        if args.sys_proxy:
            log.info("System proxy configured. Configure your OS or browser to use SOCKS5 127.0.0.1:%d", args.proxy_port)

        stop = threading.Event()

        def cleanup(*_):
            log.info("Shutting down...")
            pool.stop()
            local.stop()
            if args.sys_proxy:
                set_system_proxy("127.0.0.1", args.proxy_port, enabled=False)
            stop.set()

        signal.signal(signal.SIGINT, cleanup)
        signal.signal(signal.SIGTERM, cleanup)

        try:
            stop.wait()
        except KeyboardInterrupt:
            cleanup()

if __name__ == "__main__":
    main()
