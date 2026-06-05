import logging
import random
import socket
import struct
import sys

log = logging.getLogger("vpn")
SO_ORIGINAL_DST = 80

IP_SERVICES = [
    ("ifconfig.me", "/ip"),
    ("api.ipify.org", "/"),
    ("checkip.amazonaws.com", "/"),
    ("icanhazip.com", "/"),
]

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
    host, path = random.choice(IP_SERVICES)
    s = None
    try:
        if proxy:
            s = socks.socksocket()
            s.set_proxy(socks.SOCKS5, proxy[0], proxy[1])
        else:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, 80))
        s.sendall(f"GET {path} HTTP/1.0\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        body = data.split(b"\r\n\r\n", 1)[-1]
        return body.decode().strip()
    except Exception as e:
        log.debug("IP lookup via %s failed: %s", host, e)
        return None
    finally:
        if s:
            try:
                s.close()
            except:
                pass
