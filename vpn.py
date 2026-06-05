import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import pyfiglet
from utils import log, setup_log, current_ip
from proxy_pool import ProxyPool

PLATFORM = sys.platform
CONFIG_PATH = os.path.expanduser("~/.ghostvpn_config")
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
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

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
    raw = pyfiglet.figlet_format("GHOSTVPN", font="slant")
    lines = raw.rstrip("\n").split("\n")
    for i, line in enumerate(lines):
        t = i / max(len(lines) - 1, 1)
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
        self.proxy_port = 10800
        self.proxy_file = None
        self.sys_proxy = False
        self.verbose = False
        self.kill_switch = False

    def save(self):
        data = {
            "mode": self.mode, "interval": self.interval,
            "proxy_port": self.proxy_port, "proxy_file": self.proxy_file,
            "sys_proxy": self.sys_proxy, "kill_switch": self.kill_switch,
            "verbose": self.verbose,
        }
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(data, f)
        except Exception as e:
            log.debug("Failed to save config: %s", e)

    def load(self):
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            self.mode = data.get("mode", self.mode)
            self.interval = data.get("interval", self.interval)
            self.proxy_port = data.get("proxy_port", self.proxy_port)
            self.proxy_file = data.get("proxy_file", self.proxy_file)
            self.sys_proxy = data.get("sys_proxy", self.sys_proxy)
            self.kill_switch = data.get("kill_switch", self.kill_switch)
            self.verbose = data.get("verbose", self.verbose)
        except:
            pass

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
        ks = "ON" if cfg.kill_switch else "OFF"
        c = menu("SETTINGS", [
            (f"Mode:             {mode}", ""),
            (f"Rotation interval: {cfg.interval}s", ""),
            (f"Proxy port:        {cfg.proxy_port}", ""),
            (f"Proxy source:      {src}", ""),
            (f"System proxy:      {sp}", "(macOS/Windows only)"),
            (f"Kill switch:       {ks}", "(block if no proxies work)"),
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
            cfg.kill_switch = not cfg.kill_switch
        elif c == "7":
            cfg.save()
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

  Version   │  v1.2.0
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

    pool.print_status()
    if pool.get() is None:
        input("  No working proxies found. Press Enter...")
        return

    ip = current_ip(pool.get())
    print(f"  [2/4] Exit IP through proxy: {ip or 'unknown'}")
    log.info("VPN ready — pool has %d proxies, active: %s", pool.size(), ip or "?")

    stop_event = threading.Event()

    pool.on_switch.append(lambda p: log.info("Switched proxy — %s:%d", *p))

    if cfg.mode == "tun":
        from tun import TunManager, PROXY_PORT
        from transproxy import TransProxy
        from dns import DnsProxy
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
            return
        proxy = TransProxy(pool, bind_port=PROXY_PORT, kill_switch=cfg.kill_switch)
        proxy.start()
        threading.Thread(target=proxy.serve, daemon=True).start()
        dns = DnsProxy(pool)
        dns.start()
        threading.Thread(target=dns.serve, daemon=True).start()
        pool.start_auto_rotate()
        CYAN = "\033[38;2;0;200;255m"
        YELLOW = "\033[38;2;255;220;80m"
        GREEN = "\033[38;2;100;255;100m"
        BOLD = "\033[1m"
        RESET = "\033[0m"

        def _status():
            cols = 80
            try:
                cols = os.get_terminal_size().columns
            except:
                pass
            while not stop_event.is_set():
                active = pool.get()
                host = "none"
                if active:
                    host = f"{active[0].split('.')[0]}.{active[0].split('.')[1]}.*.*"
                s = proxy.stats_line()
                bar = f"  {BOLD}GHOSTVPN{RESET}  {CYAN}│{RESET}  {s}  {CYAN}│{RESET}  pool {GREEN}{pool.size()}{RESET}  {CYAN}│{RESET}  proxy {YELLOW}{host}{RESET}  "
                if len(bar) >= cols:
                    bar = bar[:cols - 1]
                else:
                    bar = bar.ljust(cols - 1)
                sys.stdout.write(f"\r{RESET}{bar}")
                sys.stdout.flush()
                stop_event.wait(1)
            sys.stdout.write(f"\r\033[K")
            sys.stdout.flush()

        threading.Thread(target=_status, daemon=True).start()
        print(f"  [4/4] VPN is LIVE! Rotating every {cfg.interval}s")
        print(f"\n  ── Press Ctrl+C to stop ──\n")
        _orig = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
        def cleanup(*_):
            sys.stdout.write(f"\n")
            sys.stdout.flush()
            cfg.save(); pool.stop(); proxy.stop(); dns.stop(); tun.cleanup(); stop_event.set()
            signal.signal(signal.SIGINT, _orig[0])
            signal.signal(signal.SIGTERM, _orig[1])
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
        _orig = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
        def cleanup(*_):
            cfg.save(); pool.stop(); local.stop()
            if cfg.sys_proxy:
                set_system_proxy("127.0.0.1", cfg.proxy_port, enabled=False)
            signal.signal(signal.SIGINT, _orig[0])
            signal.signal(signal.SIGTERM, _orig[1])
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
    ap.add_argument("--kill-switch", action="store_true", help="drop connections when all proxies fail (prevent IP leak)")
    ap.add_argument("-h", "--help", action="store_true")
    args, _ = ap.parse_known_args()

    if args.help:
        print("""GhostVPN — rotating-IP VPN

Usage:
  python vpn.py              Interactive menu (default)
  python vpn.py --cli ...    CLI mode (for scripts)

CLI options:
  --mode tun|socks           TUN (Linux) or SOCKS proxy
  --interval SECONDS         Rotation interval (default: 180)
  --proxy-port PORT          Local SOCKS port (default: 10800)
  --proxies FILE             Custom proxy list file
  --sys-proxy                Auto-set system proxy (macOS/Windows)
  --kill-switch              Drop connections when all proxies fail
  --verbose                  Debug output
  -h, --help                 This help
""")
        return

    if args.cli:
        cfg = Config()
        cfg.load()
        if args.mode: cfg.mode = args.mode
        if args.interval: cfg.interval = args.interval
        if args.proxy_port: cfg.proxy_port = args.proxy_port
        if args.proxies: cfg.proxy_file = args.proxies
        if args.sys_proxy: cfg.sys_proxy = True
        if args.kill_switch: cfg.kill_switch = True
        if args.verbose: cfg.verbose = True
        run_vpn(cfg)
    else:
        cfg = Config()
        cfg.load()
        main_menu(cfg)

if __name__ == "__main__":
    main()
