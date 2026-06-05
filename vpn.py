import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from utils import log, setup_log, current_ip
from proxy_pool import ProxyPool

PLATFORM = sys.platform
PLATFORM_OS = {"linux": "Linux", "darwin": "macOS", "win32": "Windows"}.get(PLATFORM, PLATFORM)

def detect_default_mode() -> str:
    return "tun" if PLATFORM == "linux" else "socks"

def set_system_proxy(host: str, port: int, enabled: bool):
    if PLATFORM == "darwin":
        for svc in _mac_network_services():
            state = "on" if enabled else "off"
            subprocess.run(["networksetup", "-setsocksfirewallproxystate", svc, state], check=False, capture_output=True)
            if enabled:
                subprocess.run(["networksetup", "-setsocksfirewallproxy", svc, host, str(port)], check=False, capture_output=True)
        log.info("macOS system proxy %s", "enabled" if enabled else "disabled")
    elif PLATFORM == "win32":
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings", 0, winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"socks={host}:{port}")
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        else:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        winreg.CloseKey(key)
        log.info("Windows system proxy %s", "enabled" if enabled else "disabled")

def _mac_network_services() -> list[str]:
    r = subprocess.run(["networksetup", "-listallnetworkservices"], capture_output=True, text=True, check=False)
    return [l.strip() for l in r.stdout.splitlines() if l.strip() and not l.startswith("*") and "disabled" not in l.lower()]

def _cls():
    os.system("cls" if PLATFORM == "win32" else "clear")

def _gradient(text: str, r1: int, g1: int, b1: int, r2: int, g2: int, b2: int) -> str:
    out = []
    chars = list(text)
    n = len(chars)
    for i, ch in enumerate(chars):
        t = i / max(n - 1, 1)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        out.append(f"\033[38;2;{r};{g};{b}m{ch}")
    out.append("\033[0m")
    return "".join(out)

def _print_logo():
    logo_lines = [
        "  ██████  ██   ██  ██████  ███████  ██████  ██    ██ ██████  ███    ██ ",
        " ██       ██   ██ ██    ██ ██      ██    ██ ██    ██ ██   ██ ████   ██ ",
        " ██   ███ ███████ ██    ██ █████   ██    ██ ██    ██ ██████  ██ ██  ██ ",
        " ██    ██ ██   ██ ██    ██ ██      ██    ██ ██    ██ ██   ██ ██  ██ ██ ",
        "  ██████  ██   ██  ██████  ██       ██████   ██████  ██   ██ ██   ████ ",
    ]
    for i, line in enumerate(logo_lines):
        t = i / max(len(logo_lines) - 1, 1)
        r = int(40 + (160 - 40) * t)
        g = int(200 + (50 - 200) * t)
        b = int(255 + (255 - 255) * t)
        print(f"\033[38;2;{r};{g};{b}m{line}\033[0m")
    print(_gradient("              👻  ROTATING IP VPN  👻", 0, 200, 255, 180, 50, 255))
    print()

class Config:
    def __init__(self):
        self.mode = detect_default_mode()
        self.interval = 180
        self.proxy_port = 1080
        self.proxy_file = None
        self.sys_proxy = False
        self.verbose = False

    def mode_label(self):
        return f"TUN (Linux)" if self.mode == "tun" else "SOCKS (cross-platform)"

def menu(header: str, opts: list[tuple[str, str]]) -> str:
    _cls()
    _print_logo()
    print(f"  {header}\n")
    for i, (label, desc) in enumerate(opts, 1):
        print(f"     [{i}] {label}")
        if desc:
            print(f"         {desc}")
    print()
    try:
        c = input("  └─ Choice: ").strip()
        return str(int(c))
    except (ValueError, IndexError):
        return ""

def main_menu(cfg: Config):
    basic_opts = [
        (f"▶  START VPN  ({cfg.mode_label()})", ""),
        ("Settings", f"interval={cfg.interval}s  port={cfg.proxy_port}"),
        ("About", ""),
        ("Exit", ""),
    ]
    while True:
        c = menu("MAIN MENU", basic_opts)
        if c == "1":
            run_vpn(cfg)
            input("\n  └─ Press Enter to return...")
        elif c == "2":
            settings_menu(cfg)
        elif c == "3":
            about()
        elif c == "4":
            _cls(); _print_logo(); print("\n  Goodbye! 👻\n"); sys.exit(0)

def settings_menu(cfg: Config):
    mode_opts = [("tun", "TUN — full system VPN (Linux only)"), ("socks", "SOCKS — local proxy, cross-platform")]
    while True:
        mode = cfg.mode_label()
        src = f"auto-fetch ({PLATFORM_OS})" if not cfg.proxy_file else f"custom ({cfg.proxy_file})"
        sp = "ON" if cfg.sys_proxy else "OFF"
        c = menu("SETTINGS", [
            (f"Mode:             {mode}", ""),
            (f"Rotation interval: {cfg.interval}s", ""),
            (f"Proxy port:        {cfg.proxy_port}", ""),
            (f"Proxy source:      {src}", ""),
            (f"System proxy:      {sp}", "(macOS/Windows only)"),
            ("Back", ""),
        ])
        if c == "1":
            n = menu("SELECT MODE", mode_opts)
            if n in ("1", "2"):
                cfg.mode = mode_opts[int(n) - 1][0]
                if cfg.mode == "tun" and PLATFORM != "linux":
                    input("  TUN mode is Linux-only. Press Enter...")
                    cfg.mode = "socks"
        elif c == "2":
            try:
                v = int(input(f"  Interval in seconds [{cfg.interval}]: ").strip() or cfg.interval)
                if v >= 10:
                    cfg.interval = v
            except ValueError:
                pass
        elif c == "3":
            try:
                v = int(input(f"  Proxy port [{cfg.proxy_port}]: ").strip() or cfg.proxy_port)
                if 0 < v < 65536:
                    cfg.proxy_port = v
            except ValueError:
                pass
        elif c == "4":
            p = input(f"  Proxy file path (empty = auto-fetch) [{cfg.proxy_file or ''}]: ").strip()
            cfg.proxy_file = p if p else None
        elif c == "5":
            cfg.sys_proxy = not cfg.sys_proxy
        elif c == "6":
            return

def about():
    _cls()
    _print_logo()
    print("""
  GhostVPN 👻

  A rotating-IP VPN that routes your traffic through a
  pool of free SOCKS5 proxies. No paid APIs.

  Mode      │  TUN (Linux)   — system-wide VPN
            │  SOCKS (all)   — local proxy, configure apps

  Version   │  v1.0.0
  License   │  MIT
  Repo      │  https://github.com/20player11/GhostVPN

  Press any key to return.
""")
    try:
        input()
    except:
        pass

def run_vpn(cfg: Config):
    if cfg.mode == "tun" and PLATFORM != "linux":
        input("  TUN mode not available on this platform. Press Enter...")
        return

    _cls()
    _print_logo()
    print(f"  Starting VPN in {cfg.mode_label()} mode...\n")

    setup_log(cfg.verbose)
    pool = ProxyPool(interval=cfg.interval)

    print(f"  [1/4] Building proxy pool...")
    if cfg.proxy_file:
        pool.load_file(cfg.proxy_file)
    else:
        pool.refresh()

    if pool.get() is None:
        input("  No working proxies found. Press Enter...")
        return

    ip = current_ip(pool.get())
    print(f"  [2/4] Exit IP through proxy: {ip or 'unknown'}")

    stop_event = threading.Event()

    def on_switch(proxy):
        ip = current_ip(proxy)
        log.info("New IP: %s", ip or "unknown")
    pool.on_switch.append(on_switch)

    if cfg.mode == "tun":
        from tun import TunManager
        from transproxy import TransProxy
        print(f"  [3/4] Setting up TUN device and routing...")
        tun = TunManager()
        try:
            tun.create()
        except Exception as e:
            input(f"  Failed to create tun: {e}. Press Enter...")
            return
        try:
            tun.setup_routing()
            tun.setup_iptables()
        except Exception as e:
            input(f"  Failed to set up routing: {e}. Press Enter...")
            tun.cleanup()
            return
        proxy = TransProxy(pool, bind_port=cfg.proxy_port)
        proxy.start()
        threading.Thread(target=proxy.serve, daemon=True).start()
        pool.start_auto_rotate()
        print(f"  [4/4] VPN is LIVE! Rotating every {cfg.interval}s")
        print(f"\n  ── Press Ctrl+C to stop ──\n")
        def cleanup(*_):
            pool.stop(); proxy.stop(); tun.cleanup(); stop_event.set()
        signal.signal(signal.SIGINT, cleanup)
        signal.signal(signal.SIGTERM, cleanup)
        stop_event.wait()

    else:
        from local_proxy import LocalSocksProxy
        print(f"  [3/4] Starting SOCKS5 proxy on 127.0.0.1:{cfg.proxy_port}...")
        local = LocalSocksProxy(pool, port=cfg.proxy_port)
        local.start()
        threading.Thread(target=local.serve, daemon=True).start()
        if cfg.sys_proxy:
            set_system_proxy("127.0.0.1", cfg.proxy_port, enabled=True)
            print(f"  [4/4] System proxy configured")
        else:
            print(f"  [4/4] Done")
        pool.start_auto_rotate()
        print(f"\n  VPN is LIVE! Rotating IP every {cfg.interval}s")
        print(f"  Configure your apps → SOCKS5 127.0.0.1:{cfg.proxy_port}")
        print(f"\n  ── Press Ctrl+C to stop ──\n")
        def cleanup(*_):
            pool.stop(); local.stop()
            if cfg.sys_proxy:
                set_system_proxy("127.0.0.1", cfg.proxy_port, enabled=False)
            stop_event.set()
        signal.signal(signal.SIGINT, cleanup)
        signal.signal(signal.SIGTERM, cleanup)
        stop_event.wait()

def main():
    ap = argparse.ArgumentParser(description="GhostVPN — rotating-IP VPN via SOCKS5 proxy pool", add_help=False)
    ap.add_argument("--cli", action="store_true", help="use CLI mode instead of interactive menu")
    ap.add_argument("--mode", choices=["tun", "socks"])
    ap.add_argument("--interval", type=int)
    ap.add_argument("--proxy-port", type=int)
    ap.add_argument("--proxies", type=str)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--sys-proxy", action="store_true")
    ap.add_argument("-h", "--help", action="store_true")
    args, _ = ap.parse_known_args()

    if args.help or args.cli:
        print("""GhostVPN — rotating-IP VPN

Usage:
  python vpn.py              Interactive menu (default)
  python vpn.py --cli ...    CLI mode (for scripts)

CLI options:
  --mode tun|socks           TUN (Linux) or SOCKS proxy
  --interval SECONDS         Rotation interval (default: 180)
  --proxy-port PORT          Local SOCKS port (default: 1080)
  --proxies FILE             Custom proxy list file
  --sys-proxy                Auto-set system proxy (macOS/Windows)
  --verbose                  Debug output
  -h, --help                 This help
""")
        return

    if args.cli:
        cfg = Config()
        if args.mode: cfg.mode = args.mode
        if args.interval: cfg.interval = args.interval
        if args.proxy_port: cfg.proxy_port = args.proxy_port
        if args.proxies: cfg.proxy_file = args.proxies
        if args.sys_proxy: cfg.sys_proxy = True
        if args.verbose: cfg.verbose = True
        run_vpn(cfg)
    else:
        cfg = Config()
        main_menu(cfg)

if __name__ == "__main__":
    main()
