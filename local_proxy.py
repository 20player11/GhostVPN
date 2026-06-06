import select
import socket
import threading
import struct
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import time
import socks as sockslib
from utils import log
from proxy_pool import PROXY_TYPE_MAP, SOCKS5

SOCKS_VERSION = 5
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

class LocalSocksProxy:
    def __init__(self, pool, host: str = "127.0.0.1", port: int = 10800, allowed_ips: set | None = None, kill_switch: bool = False):
        self.pool = pool
        self.host = host
        self.port = port
        self.kill_switch = kill_switch
        self._srv = None
        self._running = False
        self._pool_exec = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        self._limiter = RateLimiter()
        self._allowed = allowed_ips

    def start(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.host, self.port))
        self._srv.listen(128)
        self._running = True
        log.info("SOCKS5 server listening on %s:%d", self.host, self.port)

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

    def _handle(self, conn: socket.socket):
        try:
            ver, nmethods = conn.recv(2)
            if ver != SOCKS_VERSION:
                return
            conn.recv(nmethods)
            conn.sendall(struct.pack("BB", SOCKS_VERSION, 0))
            data = conn.recv(4)
            if len(data) < 4:
                return
            ver, cmd, rsv, atyp = data
            if cmd != 1:
                conn.sendall(struct.pack("BBB", SOCKS_VERSION, 7, 0))
                return
            dst_addr = self._read_addr(conn, atyp)
            dst_port = struct.unpack("!H", conn.recv(2))[0]
            proxy = self.pool.get()
            if not proxy:
                log.warning("No proxy available")
                if self.kill_switch:
                    return
                conn.sendall(struct.pack("BBB", SOCKS_VERSION, 1, 0))
                return
            max_attempts = min(self.pool.size() or 5, 5)
            for _ in range(max_attempts):
                up = None
                try:
                    up = sockslib.socksocket()
                    up.settimeout(15)
                    ptype = proxy[2] if len(proxy) > 2 else SOCKS5
                    up.set_proxy(PROXY_TYPE_MAP[ptype], proxy[0], proxy[1])
                    up.connect((dst_addr, dst_port))
                    bnd = ("0.0.0.0", 0)
                    resp = struct.pack("BBB", SOCKS_VERSION, 0, 0) + struct.pack("BBBB", 1, *socket.inet_aton(bnd[0])) + struct.pack("!H", bnd[1])
                    conn.sendall(resp)
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
        except Exception as e:
            log.debug("SOCKS5 error: %s", e)
        finally:
            try:
                conn.close()
            except:
                pass

    def _read_addr(self, conn: socket.socket, atyp: int) -> str:
        if atyp == 1:
            return socket.inet_ntoa(conn.recv(4))
        elif atyp == 3:
            n = conn.recv(1)[0]
            return conn.recv(n).decode()
        elif atyp == 4:
            return socket.inet_ntop(socket.AF_INET6, conn.recv(16))
        return ""

    def _pipe(self, a: socket.socket, b: socket.socket):
        try:
            while True:
                r, _, _ = select.select([a, b], [], [])
                if a in r:
                    data = a.recv(65536)
                    if not data:
                        break
                    b.sendall(data)
                if b in r:
                    data = b.recv(65536)
                    if not data:
                        break
                    a.sendall(data)
        except:
            pass
        finally:
            for s in (a, b):
                try:
                    s.close()
                except:
                    pass
