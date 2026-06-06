import json
import os
import random
import threading
import socks
import socket
import ssl
import urllib.request
import urllib.error
import ipaddress
from utils import log

SOCKS5 = "SOCKS5"
SOCKS4 = "SOCKS4"
HTTP = "HTTP"

PROXY_TYPE_MAP = {
    SOCKS5: socks.SOCKS5,
    SOCKS4: socks.SOCKS4,
    HTTP: socks.HTTP,
}

SOURCES = [
    (SOCKS5, "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"),
    (SOCKS5, "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt"),
    (SOCKS5, "https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt"),
    (SOCKS5, "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"),
    (SOCKS5, "https://raw.githubusercontent.com/vpei/Free-Proxy-Merge/main/socks5.txt"),
    (SOCKS5, "https://raw.githubusercontent.com/LLLBBKK/proxy-list/main/socks5.txt"),
    (SOCKS4, "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt"),
    (HTTP, "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"),
    (HTTP, "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"),
]

CACHE = os.path.expanduser("~/.ghostvpn_cache")

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
    def __init__(self, interval: int = 180, evict_threshold: int = 3):
        self.interval = interval
        self._pool: list[tuple[str, int, str]] = []
        self._active: tuple[str, int, str] | None = None
        self._idx = 0
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._health_timer: threading.Timer | None = None
        self._failures: dict[tuple[str, int, str], int] = {}
        self._evict_threshold = evict_threshold
        self.on_switch = []

    def _parse(self, text: str, ptype: str = SOCKS5) -> list[tuple[str, int, str]]:
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
                        out.append((host, int(parts[1]), ptype))
                    except ValueError:
                        pass
        return out

    def _fetch(self) -> list[tuple[str, int, str]]:
        ctx = ssl.create_default_context()
        all_proxies: list[tuple[str, int, str]] = []
        for ptype, url in SOURCES:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                    text = r.read().decode()
                parsed = self._parse(text, ptype)
                all_proxies.extend(parsed)
                log.debug("Fetched %d %s proxies from %s", len(parsed), ptype, url.split("/")[2])
            except Exception as e:
                log.warning("Failed to fetch %s: %s", url.split("/")[2], e)
        return list(set(all_proxies))

    def _check(self, host: str, port: int, ptype: str = SOCKS5, timeout: int = 8) -> bool:
        try:
            s = socks.socksocket()
            s.settimeout(timeout + random.uniform(0, 1))
            s.set_proxy(PROXY_TYPE_MAP[ptype], host, port)
            s.connect(("8.8.8.8", 53))
            s.close()
            return True
        except:
            return False

    def _check_http(self, host: str, port: int, ptype: str = SOCKS5, timeout: int = 10) -> bool:
        try:
            s = socks.socksocket()
            s.settimeout(timeout)
            s.set_proxy(PROXY_TYPE_MAP[ptype], host, port)
            s.connect(("httpbin.org", 80))
            s.sendall(b"GET /ip HTTP/1.0\r\nHost: httpbin.org\r\nConnection: close\r\n\r\n")
            data = s.recv(4096)
            s.close()
            return b"200" in data.split(b"\r\n")[0]
        except:
            return False

    def save_cache(self):
        with self._lock:
            data = list(self._pool)
        try:
            tmp = CACHE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.rename(tmp, CACHE)
        except Exception as e:
            log.debug("Failed to save cache: %s", e)

    def load_cache(self) -> list[tuple[str, int, str]]:
        try:
            with open(CACHE) as f:
                raw = json.load(f)
            out = []
            for p in raw:
                if len(p) == 2:
                    out.append((p[0], p[1], SOCKS5))
                elif len(p) == 3:
                    out.append((p[0], p[1], p[2]))
                else:
                    out.append((p[0], p[1], SOCKS5))
            return out
        except:
            return []

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
                            raw.append((host, int(parts[1]), SOCKS5))
                        except ValueError:
                            pass
        working = []
        for h, p, pt in raw:
            if self._check(h, p, pt, timeout=6):
                working.append((h, p, pt))
        with self._lock:
            self._pool = working
            self._idx = 0
        log.info("Loaded %d working proxies from file", len(working))
        if self._active is None and working:
            self.switch()

    def refresh(self, max_check: int = 200):
        log.info("Refreshing proxy pool...")
        cached = self.load_cache()
        working = []
        if cached:
            log.debug("Checking %d cached proxies...", len(cached))
            lock = threading.Lock()
            def check_cached(h, p, pt):
                if self._check_http(h, p, pt, timeout=8):
                    with lock:
                        working.append((h, p, pt))
            threads = [threading.Thread(target=check_cached, args=t, daemon=True) for t in cached]
            for t in threads: t.start()
            for t in threads: t.join(timeout=10)
            log.debug("Cached pool: %d working", len(working))

        raw = self._fetch()
        log.debug("Fetched %d raw proxies from %d sources", len(raw), len(SOURCES))
        fresh = [p for p in raw if p not in working]
        to_check = random.sample(fresh, min(len(fresh), max_check))
        log.debug("HTTP-checking %d fresh proxies...", len(to_check))
        http_working = []
        lock = threading.Lock()
        def check_http(h, p, pt):
            if self._check_http(h, p, pt, timeout=10):
                with lock:
                    http_working.append((h, p, pt))
        threads = [threading.Thread(target=check_http, args=t, daemon=True) for t in to_check]
        for t in threads: t.start()
        for t in threads: t.join(timeout=12)
        working.extend(http_working)
        log.debug("HTTP check passed: %d", len(http_working))

        if len(http_working) < 10:
            remaining = [t for t in to_check if t not in http_working]
            log.debug("Only %d HTTP-pass proxies, DNS-checking %d more...", len(http_working), len(remaining))
            dns_working = []
            def check_dns(h, p, pt):
                if self._check(h, p, pt, timeout=6):
                    with lock:
                        dns_working.append((h, p, pt))
            threads = [threading.Thread(target=check_dns, args=t, daemon=True) for t in remaining]
            for t in threads: t.start()
            for t in threads: t.join(timeout=8)
            working.extend(dns_working)
            log.debug("DNS fallback added: %d (total: %d)", len(dns_working), len(working))

        random.shuffle(working)
        with self._lock:
            self._pool = working
            self._idx = 0
        self.save_cache()
        log.info("Pool has %d working proxies", len(working))
        if not working:
            log.warning("No working proxies found!")
        if self._active is None and working:
            self.switch()

    def switch(self) -> tuple[str, int, str] | None:
        with self._lock:
            if not self._pool:
                return None
            self._idx = (self._idx + 1) % len(self._pool)
            self._active = self._pool[self._idx]
        log.debug("Switched to proxy %s (%s)", _redact(self._active[0]), self._active[2])
        for cb in self.on_switch:
            try:
                cb(self._active)
            except Exception as e:
                log.warning("on_switch callback error: %s", e)
        return self._active

    def get(self) -> tuple[str, int, str] | None:
        with self._lock:
            return self._active

    def get_for_dns(self) -> tuple[str, int, str] | None:
        with self._lock:
            if self._active and (len(self._active) < 3 or self._active[2] != HTTP):
                return self._active
            for p in self._pool:
                if len(p) < 3 or p[2] != HTTP:
                    return p
            return None

    def size(self) -> int:
        with self._lock:
            return len(self._pool)

    def mark_failed(self) -> tuple[str, int, str] | None:
        with self._lock:
            if not self._active or not self._pool:
                return None
            key = self._active
            self._failures[key] = self._failures.get(key, 0) + 1
            if self._failures[key] >= self._evict_threshold:
                log.debug("Evicting dead proxy %s:%d (%s)", key[0], key[1], key[2])
                self._pool = [p for p in self._pool if p != key]
                del self._failures[key]
            else:
                self._pool = [p for p in self._pool if p != key] + [key]
        return self.switch()

    def record_success(self):
        with self._lock:
            if self._active:
                self._failures.pop(self._active, None)
                if self._active in self._pool:
                    try:
                        self._pool.remove(self._active)
                        self._pool.insert(0, self._active)
                    except ValueError:
                        pass

    def print_status(self):
        with self._lock:
            size = len(self._pool)
            active = _redact(self._active[0]) if self._active else "none"
        log.info("Pool status: %d proxies, active: %s", size, active)

    def start_auto_rotate(self):
        self._running = True
        def _tick():
            if not self._running:
                return
            self.switch()
            if self._running:
                self._timer = threading.Timer(self.interval, _tick)
                self._timer.daemon = True
                self._timer.start()
        self._timer = threading.Timer(self.interval, _tick)
        self._timer.daemon = True
        self._timer.start()

    def start_health_checks(self, interval: int = 60):
        def _tick():
            if not self._running:
                return
            self._health_check()
            if self._running:
                self._health_timer = threading.Timer(interval, _tick)
                self._health_timer.daemon = True
                self._health_timer.start()
        self._health_timer = threading.Timer(interval, _tick)
        self._health_timer.daemon = True
        self._health_timer.start()

    def _health_check(self):
        with self._lock:
            pool = list(self._pool)
            active = self._active
        if not pool:
            return
        candidates = [p for p in pool if p != active]
        if not candidates:
            return
        n = min(len(candidates), 20)
        sample = random.sample(candidates, n)
        to_evict = []
        for h, p, pt in sample:
            key = (h, p, pt)
            if not self._check_http(h, p, pt, timeout=8):
                self._failures[key] = self._failures.get(key, 0) + 1
                if self._failures[key] >= self._evict_threshold:
                    to_evict.append(key)
            else:
                self._failures.pop(key, None)
        if not to_evict:
            return
        with self._lock:
            self._pool = [x for x in self._pool if x not in to_evict]
            for k in to_evict:
                self._failures.pop(k, None)
                log.debug("Evicted dead proxy %s:%d (%s) via health check", k[0], k[1], k[2])
            if self._active in to_evict:
                self._active = None
        if self._active is None:
            self.switch()

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._health_timer:
            self._health_timer.cancel()
            self._health_timer = None
