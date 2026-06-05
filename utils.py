import logging
import socket
import struct
import sys

log = logging.getLogger("vpn")
SO_ORIGINAL_DST = 80

def setup_log(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(h)
    log.setLevel(level)

def get_orig_dst(sock: socket.socket) -> tuple[str, int]:
    try:
        dst = sock.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
    except OSError:
        return sock.getpeername()
    port = struct.unpack("!H", dst[2:4])[0]
    ip = socket.inet_ntoa(dst[4:8])
    return ip, port

def current_ip(proxy: tuple[str, int] | None = None, timeout: int = 10) -> str | None:
    import socks
    s = None
    try:
        if proxy:
            s = socks.socksocket()
            s.set_proxy(socks.SOCKS5, proxy[0], proxy[1])
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(("ifconfig.me", 80))
        s.sendall(b"GET /ip HTTP/1.0\r\nHost: ifconfig.me\r\nConnection: close\r\n\r\n")
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        body = data.split(b"\r\n\r\n", 1)[-1]
        return body.decode().strip()
    except Exception as e:
        log.debug("IP lookup failed: %s", e)
        return None
    finally:
        if s:
            try:
                s.close()
            except:
                pass
