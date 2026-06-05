import socket
import threading
import struct
import socks as sockslib
from utils import log

SOCKS_VERSION = 5

class LocalSocksProxy:
    def __init__(self, pool, host: str = "127.0.0.1", port: int = 1080):
        self.pool = pool
        self.host = host
        self.port = port
        self._srv = None
        self._running = False

    def start(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.host, self.port))
        self._srv.listen(50)
        self._running = True
        log.info("SOCKS5 server listening on %s:%d", self.host, self.port)

    def serve(self):
        while self._running and self._srv:
            try:
                conn, addr = self._srv.accept()
            except OSError:
                break
            t = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            t.start()

    def stop(self):
        self._running = False
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass

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
                conn.sendall(struct.pack("BBB", SOCKS_VERSION, 1, 0))
                return
            up = sockslib.socksocket()
            up.settimeout(30)
            up.set_proxy(sockslib.SOCKS5, proxy[0], proxy[1])
            up.connect((dst_addr, dst_port))
            bnd = ("0.0.0.0", 0)
            resp = struct.pack("BBB", SOCKS_VERSION, 0, 0) + struct.pack("BBBB", 1, *socket.inet_aton(bnd[0])) + struct.pack("!H", bnd[1])
            conn.sendall(resp)
            self._pipe(conn, up)
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
        t1 = threading.Thread(target=self._relay, args=(a, b), daemon=True)
        t2 = threading.Thread(target=self._relay, args=(b, a), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    @staticmethod
    def _relay(src: socket.socket, dst: socket.socket):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.close()
                except:
                    pass
