import socket
import threading
import socks
from utils import log, get_orig_dst
from tun import BYPASS_MARK

POOL_SIZE = 20

class TransProxy:
    def __init__(self, pool, bind_port: int = 12345, bind_host: str = "0.0.0.0"):
        self.pool = pool
        self.bind_port = bind_port
        self.bind_host = bind_host
        self._srv = None
        self._running = False
        self._threads: list[threading.Thread] = []

    def start(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.bind_host, self.bind_port))
        self._srv.listen(POOL_SIZE)
        self._running = True
        log.info("Transparent proxy listening on %s:%d", self.bind_host, self.bind_port)

    def serve(self):
        while self._running and self._srv:
            try:
                conn, addr = self._srv.accept()
            except OSError:
                break
            t = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._running = False
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass

    def _pipe(self, src: socket.socket, dst: socket.socket):
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

    def _handle(self, conn: socket.socket):
        try:
            dst_host, dst_port = get_orig_dst(conn)
            log.debug("Proxying %s -> %s:%d", conn.getpeername(), dst_host, dst_port)
            proxy = self.pool.get()
            if not proxy:
                log.warning("No proxy available, dropping %s:%d", dst_host, dst_port)
                conn.close()
                return
            up = socks.socksocket()
            up.setsockopt(socket.SOL_SOCKET, socket.SO_MARK, BYPASS_MARK)
            up.settimeout(30)
            up.set_proxy(socks.SOCKS5, proxy[0], proxy[1])
            up.connect((dst_host, dst_port))
            t1 = threading.Thread(target=self._pipe, args=(conn, up), daemon=True)
            t2 = threading.Thread(target=self._pipe, args=(up, conn), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception as e:
            log.debug("Proxy error: %s", e)
        finally:
            try:
                conn.close()
            except:
                pass
