import select
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import time
import socks
from utils import log, get_orig_dst
from tun import BYPASS_MARK
from proxy_pool import PROXY_TYPE_MAP, SOCKS5

MAX_WORKERS = 100

class RateLimiter:
    def __init__(self, max_per_sec: int = 50):
        self._max = max_per_sec
        self._times = defaultdict(list)
        self._lock = threading.Lock()

    def allow(self, key: str = "") -> bool:
        now = time.monotonic()
        with self._lock:
            times = self._times[key]
            times[:] = [t for t in times if now - t < 1]
            if len(times) >= self._max:
                return False
            times.append(now)
            return True

class TransProxy:
    def __init__(self, pool, bind_port: int = 12345, bind_host: str = "127.0.0.1", allowed_ips: set | None = None, kill_switch: bool = False):
        self.pool = pool
        self.bind_port = bind_port
        self.bind_host = bind_host
        self.kill_switch = kill_switch
        self._srv = None
        self._running = False
        self._pool_exec = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self._limiter = RateLimiter()
        self._allowed = allowed_ips
        self._stats_lock = threading.Lock()
        self._start = time.monotonic()
        self._connections = 0
        self._bytes_up = 0
        self._bytes_down = 0

    def stats_line(self) -> str:
        with self._stats_lock:
            n = self._connections
            bu = self._bytes_up
            bd = self._bytes_down
        elapsed = int(time.monotonic() - self._start)
        total = bu + bd
        unit = "B"
        if total > 1024 ** 3:
            total, unit = total / 1024 ** 3, "GB"
        elif total > 1024 ** 2:
            total, unit = total / 1024 ** 2, "MB"
        elif total > 1024:
            total, unit = total / 1024, "KB"
        return f"{elapsed // 60}m{elapsed % 60:02d}s • {n} conn • {total:.1f} {unit}"

    def start(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.bind_host, self.bind_port))
        self._srv.listen(128)
        self._running = True
        log.info("Transparent proxy listening on %s:%d", self.bind_host, self.bind_port)

    def serve(self):
        while self._running and self._srv:
            try:
                conn, addr = self._srv.accept()
            except OSError:
                break
            if self._allowed and addr[0] not in self._allowed:
                conn.close()
                continue
            if not self._limiter.allow(addr[0]):
                conn.close()
                continue
            self._pool_exec.submit(self._handle, conn)

    def stop(self):
        self._running = False
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
        self._pool_exec.shutdown(wait=False)

    def _pipe(self, a: socket.socket, b: socket.socket):
        try:
            while True:
                r, _, _ = select.select([a, b], [], [])
                if a in r:
                    data = a.recv(65536)
                    if not data:
                        break
                    b.sendall(data)
                    with self._stats_lock:
                        self._bytes_up += len(data)
                if b in r:
                    data = b.recv(65536)
                    if not data:
                        break
                    a.sendall(data)
                    with self._stats_lock:
                        self._bytes_down += len(data)
        except:
            pass
        finally:
            for s in (a, b):
                try:
                    s.close()
                except:
                    pass

    def _handle(self, conn: socket.socket):
        with self._stats_lock:
            self._connections += 1
        try:
            dst_host, dst_port = get_orig_dst(conn)
            log.debug("Proxying %s -> %s:%d", conn.getpeername(), dst_host, dst_port)
            proxy = self.pool.get()
            if not proxy:
                log.warning("No proxy available for %s:%d", dst_host, dst_port)
                conn.close()
                return
            max_attempts = min(self.pool.size() or 5, 5)
            for _ in range(max_attempts):
                up = None
                try:
                    up = socks.socksocket()
                    up.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, BYPASS_MARK)
                    up.settimeout(15)
                    ptype = proxy[2] if len(proxy) > 2 else SOCKS5
                    up.set_proxy(PROXY_TYPE_MAP[ptype], proxy[0], proxy[1])
                    log.debug("Trying proxy %s:%d for %s:%d", proxy[0], proxy[1], dst_host, dst_port)
                    up.connect((dst_host, dst_port))
                    self._pipe(conn, up)
                    self.pool.record_success()
                    return
                except Exception:
                    if up:
                        try:
                            up.close()
                        except:
                            pass
                    proxy = self.pool.mark_failed()
                    if not proxy:
                        break
            if self.kill_switch:
                log.warning("Kill-switch active, dropping %s:%d", dst_host, dst_port)
                return
            log.warning("All proxies failed for %s:%d, connecting directly", dst_host, dst_port)
            up = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            up.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, BYPASS_MARK)
            up.settimeout(15)
            up.connect((dst_host, dst_port))
            self._pipe(conn, up)
        except Exception as e:
            log.debug("Proxy error: %s", e)
        finally:
            try:
                conn.close()
            except:
                pass
