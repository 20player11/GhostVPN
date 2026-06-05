import socket
import struct
import threading
import socks as sockslib
from utils import log
from tun import BYPASS_MARK

UPSTREAM = ("1.1.1.1", 53)


class DnsProxy:
    def __init__(self, pool, host: str = "127.0.0.1", port: int = 5353):
        self.pool = pool
        self.host = host
        self.port = port
        self._sock = None
        self._running = False

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._running = True
        log.info("DNS proxy listening on %s:%d", self.host, self.port)

    def serve(self):
        while self._running and self._sock:
            try:
                data, addr = self._sock.recvfrom(4096)
                threading.Thread(target=self._handle, args=(data, addr), daemon=True).start()
            except OSError:
                break

    def _handle(self, data: bytes, addr: tuple[str, int]):
        proxy = self.pool.get()
        if not proxy:
            log.debug("DNS: no proxy available")
            return
        try:
            up = sockslib.socksocket()
            up.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, BYPASS_MARK)
            up.settimeout(10)
            up.set_proxy(sockslib.SOCKS5, proxy[0], proxy[1])
            up.connect(UPSTREAM)
            up.sendall(struct.pack("!H", len(data)) + data)
            resp = b""
            while True:
                chunk = up.recv(4096)
                if not chunk:
                    break
                resp += chunk
                if len(resp) >= 2:
                    expected = 2 + struct.unpack("!H", resp[:2])[0]
                    if len(resp) >= expected:
                        break
            if resp:
                self._sock.sendto(resp[2:], addr)
        except Exception as e:
            log.debug("DNS error: %s", e)
        finally:
            try:
                up.close()
            except:
                pass

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
