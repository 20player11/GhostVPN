import atexit
import ctypes
import ctypes.wintypes
import os
import random
import socket
import struct
import subprocess
import threading
import time
import socks as sockslib
from utils import log
from proxy_pool import PROXY_TYPE_MAP, SOCKS5

# ── Wintun ctypes bindings ────────────────────────────────────────────

ADAPTER_HANDLE = ctypes.c_void_p
SESSION_HANDLE = ctypes.c_void_p

_wintun = None

def _wintun_load():
    global _wintun
    if _wintun is not None:
        return _wintun
    from wintun_dl import ensure
    dll = ensure()
    _wintun = ctypes.CDLL(dll, use_last_error=True)

    _wintun.WintunCreateAdapter.restype = ADAPTER_HANDLE
    _wintun.WintunCreateAdapter.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_void_p]

    _wintun.WintunDeleteAdapter.restype = None
    _wintun.WintunDeleteAdapter.argtypes = [ADAPTER_HANDLE, ctypes.c_bool]

    _wintun.WintunOpenAdapter.restype = ADAPTER_HANDLE
    _wintun.WintunOpenAdapter.argtypes = [ctypes.c_wchar_p]

    _wintun.WintunStartSession.restype = SESSION_HANDLE
    _wintun.WintunStartSession.argtypes = [ADAPTER_HANDLE, ctypes.c_uint32]

    _wintun.WintunEndSession.restype = None
    _wintun.WintunEndSession.argtypes = [SESSION_HANDLE]

    _wintun.WintunGetReadPacket.restype = ctypes.c_bool
    _wintun.WintunGetReadPacket.argtypes = [SESSION_HANDLE, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32)]

    _wintun.WintunReleaseReadPacket.restype = None
    _wintun.WintunReleaseReadPacket.argtypes = [SESSION_HANDLE, ctypes.c_void_p]

    _wintun.WintunAllocateSendPacket.restype = ctypes.c_void_p
    _wintun.WintunAllocateSendPacket.argtypes = [SESSION_HANDLE, ctypes.c_uint32]

    _wintun.WintunSendPacket.restype = None
    _wintun.WintunSendPacket.argtypes = [SESSION_HANDLE, ctypes.c_void_p]

    return _wintun


# ── Packet helpers ────────────────────────────────────────────────────

TCP_PROTO = 6
UDP_PROTO = 17

def parse_ip(pkt):
    vhl = pkt[0]
    hdr = (vhl & 0x0F) * 4
    total = struct.unpack("!H", pkt[2:4])[0]
    proto = pkt[9]
    src = socket.inet_ntoa(pkt[12:16])
    dst = socket.inet_ntoa(pkt[16:20])
    return hdr, total, proto, src, dst, pkt[hdr:total]

_ip_id = random.randint(0, 65535)

def build_ip(src, dst, proto, pay):
    global _ip_id
    _ip_id = (_ip_id + 1) & 0xFFFF
    total = 20 + len(pay)
    hdr = struct.pack("!BBHHHBBH", 0x45, 0, total, _ip_id, 0, 64, proto, 0)
    hdr += socket.inet_aton(src) + socket.inet_aton(dst)
    chk = _ip_checksum(hdr)
    hdr = hdr[:10] + struct.pack("!H", chk) + hdr[12:]
    return hdr + pay

def _ip_checksum(data):
    if len(data) % 2:
        data += b"\0"
    s = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF

def parse_tcp(seg):
    sp, dp = struct.unpack("!HH", seg[0:4])
    seq, ack = struct.unpack("!II", seg[4:12])
    off = ((seg[12] & 0xF0) >> 4) * 4
    flags = seg[13]
    pay = seg[off:]
    return sp, dp, seq, ack, flags, pay

def _tcp_checksum(src, dst, seg):
    psh = socket.inet_aton(src) + socket.inet_aton(dst)
    psh += struct.pack("!BBH", 0, TCP_PROTO, len(seg))
    if len(seg) % 2:
        seg += b"\0"
    data = psh + seg
    s = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return ~s & 0xFFFF

def build_tcp(src_ip, dst_ip, sp, dp, seq, ack, flags, pay):
    off = 5
    hdr = struct.pack("!HHIIBBHHH", sp, dp, seq, ack, off << 4, flags, 65535, 0, 0)
    chk = _tcp_checksum(src_ip, dst_ip, hdr + pay)
    hdr = hdr[:16] + struct.pack("!H", chk) + hdr[18:]
    return hdr + pay

FLAG_SYN = 0x02
FLAG_ACK = 0x10
FLAG_PSH = 0x08
FLAG_FIN = 0x01
FLAG_RST = 0x04
FLAG_SYNACK = FLAG_SYN | FLAG_ACK
FLAG_PSHACK = FLAG_PSH | FLAG_ACK
FLAG_FINACK = FLAG_FIN | FLAG_ACK


# ── Proxy route bypass manager ────────────────────────────────────────

class RouteBypass:
    def __init__(self):
        self._orig_gw = None
        self._added = set()

    def save_gw(self):
        if self._orig_gw:
            return
        r = subprocess.run(["route", "print", "0.0.0.0", "mask", "0.0.0.0"],
                           capture_output=True, text=True, check=False)
        for line in r.stdout.splitlines():
            if "0.0.0.0" in line and "0.0.0.0" in line.split()[:2]:
                parts = line.split()
                if len(parts) >= 3:
                    self._orig_gw = parts[2]
                    break

    def add(self, ip):
        if ip in self._added or not self._orig_gw:
            return
        subprocess.run(["route", "add", ip, "mask", "255.255.255.255", self._orig_gw, "metric", "5"],
                       capture_output=True, check=False)
        self._added.add(ip)

    def add_many(self, ips):
        for ip in ips:
            self.add(ip)

    def cleanup(self):
        for ip in list(self._added):
            subprocess.run(["route", "delete", ip, "mask", "255.255.255.255"],
                           capture_output=True, check=False)
        self._added.clear()


# ── TCP connection state ──────────────────────────────────────────────

class TcpConn:
    def __init__(self, src_ip, sp, dst_ip, dp, c_isn):
        self.src_ip = src_ip
        self.sp = sp
        self.dst_ip = dst_ip
        self.dp = dp
        self.key = (src_ip, sp, dst_ip, dp)
        self.c_isn = c_isn
        self.s_isn = random.randint(10000, 2 ** 31)
        self.c_next = c_isn + 1
        self.s_next = self.s_isn + 1
        self.up = None
        self.buf = b""
        self.closing = False
        self.created = time.monotonic()

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, o):
        return isinstance(o, TcpConn) and self.key == o.key


# ── Wintun adapter wrapper ────────────────────────────────────────────

ADAPTER_NAME = "GhostVPN"
TUN_IP = "10.0.85.1"
TUN_NET = "10.0.85.0/24"
TUN_MASK = "255.255.255.0"
DNS_UPSTREAM = ("1.1.1.1", 53)


class WinTun:
    def __init__(self):
        self._adapter = None
        self._session = None

    def create(self):
        w = _wintun_load()
        old = w.WintunOpenAdapter(ADAPTER_NAME)
        if old:
            w.WintunDeleteAdapter(old, True)
        self._adapter = w.WintunCreateAdapter(ADAPTER_NAME, "GhostVPN", None)
        if not self._adapter:
            raise OSError(f"WintunCreateAdapter failed (error {ctypes.get_last_error()})")
        self._session = w.WintunStartSession(self._adapter, 0x400000)
        if not self._session:
            self._destroy()
            raise OSError("WintunStartSession failed")
        self._configure_ip()

    def _destroy(self):
        w = _wintun_load()
        if self._session:
            w.WintunEndSession(self._session)
            self._session = None
        if self._adapter:
            w.WintunDeleteAdapter(self._adapter, False)
            self._adapter = None

    def _configure_ip(self):
        subprocess.run(["netsh", "interface", "ip", "set", "address",
                        f"name={ADAPTER_NAME}", "source=static",
                        f"addr={TUN_IP}", f"mask={TUN_MASK}"],
                       check=True, capture_output=True)

    def read(self):
        w = _wintun_load()
        pkt_ptr = ctypes.c_void_p()
        sz = ctypes.c_uint32()
        if w.WintunGetReadPacket(self._session, ctypes.byref(pkt_ptr), ctypes.byref(sz)):
            data = ctypes.string_at(pkt_ptr, sz.value)
            w.WintunReleaseReadPacket(self._session, pkt_ptr)
            return data
        return None

    def write(self, data):
        w = _wintun_load()
        pkt = w.WintunAllocateSendPacket(self._session, len(data))
        if not pkt:
            return
        ctypes.memmove(pkt, data, len(data))
        w.WintunSendPacket(self._session, pkt)

    def close(self):
        self._destroy()

    def fileno(self):
        return None


# ── Ctrl+C handler ────────────────────────────────────────────────────

_ctrl_handlers = []

def _ctrl_callback(c):
    if c == 0:
        for fn in _ctrl_handlers:
            fn()
        return True
    return False

_CTRL_TYPE = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
_ctrl_fn = _CTRL_TYPE(_ctrl_callback)

def set_ctrl_handler(fn):
    _ctrl_handlers.append(fn)
    if len(_ctrl_handlers) == 1:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleCtrlHandler(_ctrl_fn, True)


# ── Windows VPN orchestrator ──────────────────────────────────────────

class WindowsVPN:
    def __init__(self, pool, interval, kill_switch):
        self.pool = pool
        self.interval = interval
        self.kill_switch = kill_switch
        self._tun = None
        self._bypass = RouteBypass()
        self._conns = {}
        self._conns_lock = threading.Lock()
        self._running = False
        self._cleanup_done = False

    def _handle_tcp(self, src_ip, sp, dst_ip, dp, seq, ack, flags, pay, pkt):
        key = (src_ip, sp, dst_ip, dp)
        with self._conns_lock:
            conn = self._conns.get(key)

        if flags & FLAG_RST:
            if conn:
                self._close_conn(conn)
            return

        if flags & FLAG_SYN and not (flags & FLAG_ACK):
            if conn:
                self._close_conn(conn)
            conn = TcpConn(src_ip, sp, dst_ip, dp, seq)
            with self._conns_lock:
                self._conns[key] = conn
            synack = build_tcp(dst_ip, src_ip, dp, sp, conn.s_isn, conn.c_next,
                               FLAG_SYNACK, b"")
            ip_pkt = build_ip(TUN_IP, src_ip, TCP_PROTO, synack)
            self._tun.write(ip_pkt)
            return

        if not conn:
            rst = build_tcp(dst_ip, src_ip, dp, sp, 0, seq + len(pay) + 1, FLAG_RST, b"")
            self._tun.write(build_ip(TUN_IP, src_ip, TCP_PROTO, rst))
            return

        if conn.closing:
            return

        if flags & FLAG_FIN:
            finack = build_tcp(dst_ip, src_ip, dp, sp, conn.s_next, seq + len(pay) + 1,
                               FLAG_FINACK, b"")
            self._tun.write(build_ip(TUN_IP, src_ip, TCP_PROTO, finack))
            self._close_conn(conn)
            return

        if pay:
            conn.c_next = seq + len(pay)
            ack_pkt = build_tcp(dst_ip, src_ip, dp, sp, conn.s_next, conn.c_next,
                                FLAG_ACK, b"")
            self._tun.write(build_ip(TUN_IP, src_ip, TCP_PROTO, ack_pkt))

        if flags & FLAG_PSH or pay:
            conn.buf += pay
            if conn.up is None:
                proxy = self.pool.get()
                if not proxy:
                    return
                try:
                    up = sockslib.socksocket()
                    up.settimeout(30)
                    ptype = proxy[2] if len(proxy) > 2 else SOCKS5
                    up.set_proxy(PROXY_TYPE_MAP[ptype], proxy[0], proxy[1])
                    up.connect((dst_ip, dp))
                    conn.up = up
                    threading.Thread(target=self._up_relay, args=(key,), daemon=True).start()
                except Exception as e:
                    log.debug("SOCKS connect fail %s:%d: %s", dst_ip, dp, e)
                    if self.kill_switch:
                        rst = build_tcp(dst_ip, src_ip, dp, sp, conn.s_next, conn.c_next, FLAG_RST, b"")
                        self._tun.write(build_ip(TUN_IP, src_ip, TCP_PROTO, rst))
                    return
            if conn.up and conn.buf:
                try:
                    conn.up.sendall(conn.buf)
                except:
                    pass
                conn.buf = b""

    def _up_relay(self, key):
        with self._conns_lock:
            conn = self._conns.get(key)
        if not conn or not conn.up:
            return
        up = conn.up
        while self._running and not conn.closing:
            try:
                data = up.recv(65536)
            except:
                break
            if not data:
                break
            with self._conns_lock:
                c = self._conns.get(key)
                if not c:
                    break
                seg = build_tcp(c.dst_ip, c.src_ip, c.dp, c.sp, c.s_next, c.c_next,
                                FLAG_PSHACK, data)
                ip_pkt = build_ip(TUN_IP, c.src_ip, TCP_PROTO, seg)
                c.s_next += len(data)
            self._tun.write(ip_pkt)
        if not conn.closing:
            with self._conns_lock:
                c = self._conns.get(key)
                if c and not c.closing:
                    fin = build_tcp(c.dst_ip, c.src_ip, c.dp, c.sp, c.s_next, c.c_next,
                                    FLAG_FINACK, b"")
                    self._tun.write(build_ip(TUN_IP, c.src_ip, TCP_PROTO, fin))
                    self._close_conn(c)
        try:
            up.close()
        except:
            pass

    def _handle_udp(self, src_ip, sp, dst_ip, dp, pay, pkt):
        if dp == 53:
            threading.Thread(target=self._dns_forward,
                             args=(src_ip, sp, dst_ip, pay), daemon=True).start()

    def _dns_forward(self, src_ip, sp, dst_ip, query):
        proxy = self.pool.get_for_dns()
        try:
            if proxy:
                up = sockslib.socksocket()
                up.settimeout(10)
                ptype = proxy[2] if len(proxy) > 2 else SOCKS5
                up.set_proxy(PROXY_TYPE_MAP[ptype], proxy[0], proxy[1])
                up.connect(DNS_UPSTREAM)
                up.sendall(struct.pack("!H", len(query)) + query)
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
                    dns_resp = build_ip(dst_ip, src_ip, UDP_PROTO,
                                        self._udp_pkt(53, sp, resp[2:]))
                    self._tun.write(dns_resp)
                up.close()
            else:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(10)
                s.sendto(query, DNS_UPSTREAM)
                data, _ = s.recvfrom(4096)
                if data:
                    dns_resp = build_ip(dst_ip, src_ip, UDP_PROTO,
                                        self._udp_pkt(53, sp, data))
                    self._tun.write(dns_resp)
                s.close()
        except:
            pass

    def _udp_pkt(self, sp, dp, pay):
        hdr = struct.pack("!HHH", sp, dp, 8 + len(pay)) + struct.pack("!H", 0)
        return hdr + pay

    def _close_conn(self, conn):
        conn.closing = True
        if conn.up:
            try:
                conn.up.close()
            except:
                pass
        with self._conns_lock:
            self._conns.pop(conn.key, None)

    def _stale_check(self):
        while self._running:
            time.sleep(30)
            now = time.monotonic()
            stale = []
            with self._conns_lock:
                for k, c in self._conns.items():
                    if now - c.created > 300:
                        stale.append(k)
                for k in stale:
                    self._conns.pop(k, None)

    def _tun_route_add(self):
        subprocess.run(["route", "add", "0.0.0.0", "mask", "0.0.0.0",
                        TUN_IP, "metric", "1"], check=False, capture_output=True)

    def _tun_route_del(self):
        subprocess.run(["route", "delete", "0.0.0.0", "mask", "0.0.0.0",
                        TUN_IP], check=False, capture_output=True)

    def run(self):
        self._running = True
        self._tun = WinTun()
        self._tun.create()

        self._bypass.save_gw()
        proxy_ips = set()
        for h, p, pt in self.pool._pool:
            try:
                socket.inet_aton(h)
                proxy_ips.add(h)
            except OSError:
                pass
        active = self.pool.get()
        if active:
            try:
                socket.inet_aton(active[0])
                proxy_ips.add(active[0])
            except OSError:
                pass
        self._bypass.add_many(proxy_ips)
        self._bypass.add_many(["1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4"])

        def _on_switch(proxy):
            if proxy:
                try:
                    socket.inet_aton(proxy[0])
                    self._bypass.add(proxy[0])
                except OSError:
                    pass
        self.pool.on_switch.append(_on_switch)

        self._tun_route_add()

        def _cleanup():
            if self._cleanup_done:
                return
            self._cleanup_done = True
            self._running = False
            self._tun_route_del()
            self._bypass.cleanup()
            with self._conns_lock:
                for k, c in list(self._conns.items()):
                    if c.up:
                        try:
                            c.up.close()
                        except:
                            pass
                self._conns.clear()
            self._tun.close()

        atexit.register(_cleanup)
        set_ctrl_handler(_cleanup)

        threading.Thread(target=self._stale_check, daemon=True).start()

        log.info("Windows VPN running on %s", TUN_IP)
        while self._running:
            try:
                pkt = self._tun.read()
            except:
                break
            if pkt is None:
                time.sleep(0.01)
                continue
            try:
                hdr_len, total_len, proto, src, dst, pay = parse_ip(pkt)
                if proto == TCP_PROTO:
                    sp, dp, seq, ack, flags, tcp_pay = parse_tcp(pay)
                    self._handle_tcp(src, sp, dst, dp, seq, ack, flags, tcp_pay, pkt)
                elif proto == UDP_PROTO:
                    sp = struct.unpack("!H", pay[0:2])[0]
                    dp = struct.unpack("!H", pay[2:4])[0]
                    udp_pay = pay[8:]
                    if dp == 53:
                        self._handle_udp(src, sp, dst, dp, udp_pay, pkt)
            except Exception as e:
                log.debug("Packet error: %s", e)
        _cleanup()


def run(pool, interval, kill_switch):
    vpn = WindowsVPN(pool, interval, kill_switch)
    vpn.run()
