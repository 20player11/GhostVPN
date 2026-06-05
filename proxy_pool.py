import random
import threading
import socks
import socket
import ssl
import urllib.request
import urllib.error
import ipaddress
from utils import log

SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt",
]

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
]

def _is_private_ip(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in _PRIVATE_RANGES)
    except ValueError:
        return True

def _redact(host: str) -> str:
    parts = host.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.*.*"
    return host

class ProxyPool:
    def __init__(self, interval: int = 180):
        self.interval = interval
        self._pool: list[tuple[str, int]] = []
        self._active: tuple[str, int] | None = None
        self._idx = 0
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self.on_switch = []

    def _parse(self, text: str) -> list[tuple[str, int]]:
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                parts = line.split(":")
                if len(parts) == 2:
                    try:
                        host = parts[0]
                        if _is_private_ip(host):
                            log.debug("Skipping private proxy %s", _redact(host))
                            continue
                        out.append((host, int(parts[1])))
                    except ValueError:
                        pass
        return out

    def _fetch(self) -> list[tuple[str, int]]:
        ctx = ssl.create_default_context()
        all_proxies: list[tuple[str, int]] = []
        for url in SOURCES:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                    text = r.read().decode()
                parsed = self._parse(text)
                all_proxies.extend(parsed)
                log.info("Fetched %d proxies from %s", len(parsed), url.split("/")[2])
            except Exception as e:
                log.warning("Failed to fetch %s: %s", url.split("/")[2], e)
        return list(set(all_proxies))

    def _check(self, host: str, port: int, timeout: int = 8) -> bool:
        try:
            s = socks.socksocket()
            s.settimeout(timeout + random.uniform(0, 1))
            s.set_proxy(socks.SOCKS5, host, port)
            s.connect(("8.8.8.8", 53))
            s.close()
            return True
        except:
            return False

    def load_file(self, path: str):
        log.info("Loading proxies from %s", path)
        raw = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if ":" in line and not line.startswith("#"):
                    parts = line.split(":")
                    if len(parts) == 2:
                        try:
                            host = parts[0]
                            if _is_private_ip(host):
                                continue
                            raw.append((host, int(parts[1])))
                        except ValueError:
                            pass
        working = []
        for h, p in raw:
            if self._check(h, p, timeout=6):
                working.append((h, p))
        with self._lock:
            self._pool = working
            self._idx = 0
        log.info("Loaded %d working proxies from file", len(working))
        if self._active is None and working:
            self.switch()

    def refresh(self, max_check: int = 200):
        log.info("Refreshing proxy pool...")
        raw = self._fetch()
        log.info("Checking up to %d proxies (threaded)...", min(len(raw), max_check))
        to_check = random.sample(raw, min(len(raw), max_check))
        working = []
        lock = threading.Lock()
        def check(h, p):
            if self._check(h, p, timeout=6):
                with lock:
                    working.append((h, p))
                    log.debug("OK  %s", _redact(h))
        threads = []
        for h, p in to_check:
            t = threading.Thread(target=check, args=(h, p), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=10)
        with self._lock:
            self._pool = working
            self._idx = 0
        log.info("Pool has %d working proxies", len(working))
        if not working:
            log.warning("No working proxies found!")
        if self._active is None and working:
            self.switch()

    def switch(self) -> tuple[str, int] | None:
        with self._lock:
            if not self._pool:
                return None
            pool_copy = list(self._pool)
            start = self._idx
        n = len(pool_copy)
        for offset in range(1, n + 1):
            idx = (start + offset) % n
            h, p = pool_copy[idx]
            if self._check(h, p, timeout=4):
                with self._lock:
                    self._idx = idx
                    self._active = pool_copy[idx]
                log.info("Switched to proxy %s", _redact(h))
                for cb in self.on_switch:
                    try:
                        cb(self._active)
                    except Exception as e:
                        log.warning("on_switch callback error: %s", e)
                return self._active
        with self._lock:
            self._idx = (start + 1) % n
            self._active = pool_copy[self._idx]
        log.warning("No alive proxy found, using pool default %s", _redact(self._active[0]))
        for cb in self.on_switch:
            try:
                cb(self._active)
            except Exception as e:
                log.warning("on_switch callback error: %s", e)
        return self._active

    def get(self) -> tuple[str, int] | None:
        with self._lock:
            return self._active

    def start_auto_rotate(self):
        def _tick():
            self.switch()
            self._timer = threading.Timer(self.interval, _tick)
            self._timer.daemon = True
            self._timer.start()
        self._timer = threading.Timer(self.interval, _tick)
        self._timer.daemon = True
        self._timer.start()

    def stop(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
