import fcntl
import os
import socket
import struct
import subprocess
from utils import log

TUNSETIFF = 0x400454CA
IFF_TUN = 0x0001
IFF_NO_PI = 0x1000
TUN_IP = "10.0.0.1"
TUN_NET = "10.0.0.0/24"
PROXY_PORT = 12345
BYPASS_MARK = 888

class TunManager:
    def __init__(self, name: str = "tun0"):
        self.name = name
        self._fd = -1
        self._orig_gw = None
        self._orig_iface = None
        self._rules_added = False
        self._iptables_added = False

    def create(self):
        if not os.path.exists("/dev/net/tun"):
            subprocess.run(["modprobe", "tun"], check=False, capture_output=True)
        self._fd = os.open("/dev/net/tun", os.O_RDWR)
        ifr = struct.pack("16sH", self.name.encode(), IFF_TUN | IFF_NO_PI)
        fcntl.ioctl(self._fd, TUNSETIFF, ifr)
        log.info("Created tun device %s", self.name)

    def fileno(self) -> int:
        return self._fd

    def read(self, n: int = 4096) -> bytes:
        return os.read(self._fd, n) if self._fd >= 0 else b""

    def write(self, data: bytes):
        if self._fd >= 0:
            os.write(self._fd, data)

    def _run(self, *cmd: str, check: bool = True):
        subprocess.run(cmd, check=check, capture_output=True, text=True)

    def setup_routing(self):
        self._save_orig_gw()
        try:
            self._run("ip", "addr", "add", TUN_IP + "/24", "dev", self.name)
            self._run("ip", "link", "set", self.name, "up")
            via = TUN_IP
            self._run("ip", "route", "add", TUN_NET, "dev", self.name, "table", "100")
            self._run("ip", "route", "add", "default", "via", via, "dev", self.name, "table", "100")
            self._run("ip", "rule", "add", "fwmark", str(BYPASS_MARK), "table", "main", "pref", "1000")
            self._run("ip", "rule", "add", "table", "100", "pref", "20000")
            self._rules_added = True
            self._run("ip", "route", "flush", "cache")
            log.info("Routing: default via %s dev %s (table 100), fwmark %d bypasses", via, self.name, BYPASS_MARK)
        except Exception:
            self.cleanup()
            raise

    def _save_orig_gw(self):
        r = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, check=False
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = r.stdout.strip().split()
            try:
                gw_idx = parts.index("via")
                dev_idx = parts.index("dev")
                self._orig_gw = parts[gw_idx + 1]
                self._orig_iface = parts[dev_idx + 1]
                log.info("Saved original gateway: %s via %s", self._orig_gw, self._orig_iface)
            except (ValueError, IndexError):
                log.warning("Could not parse default route: %s", r.stdout.strip())

    def setup_iptables(self):
        try:
            self._run("iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp",
                       "-d", "127.0.0.0/8", "-j", "RETURN")
            self._run("iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp",
                       "-m", "mark", "--mark", str(BYPASS_MARK), "-j", "RETURN")
            self._run("iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp",
                       "-j", "REDIRECT", "--to-port", str(PROXY_PORT))
            self._run("iptables", "-A", "OUTPUT", "-p", "udp", "--dport", "443",
                       "-j", "REJECT", "--reject-with", "icmp-port-unreachable")
            self._run("ip6tables", "-A", "OUTPUT", "-o", "lo", "-j", "ACCEPT", check=False)
            self._run("ip6tables", "-A", "OUTPUT", "-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset", check=False)
            self._run("ip6tables", "-A", "OUTPUT", "-j", "DROP", check=False)
            self._iptables_added = True
            log.info("iptables: redirect TCP -> %d, QUIC blocked, IPv6 blocked", PROXY_PORT)
        except Exception:
            self.cleanup()
            raise

    def cleanup(self):
        log.info("Cleaning up...")
        try:
            if self._iptables_added:
                self._run("ip6tables", "-D", "OUTPUT", "-o", "lo", "-j", "ACCEPT", check=False)
                self._run("ip6tables", "-D", "OUTPUT", "-p", "tcp", "-j", "REJECT", "--reject-with", "tcp-reset", check=False)
                self._run("ip6tables", "-D", "OUTPUT", "-j", "DROP", check=False)
            self._run("iptables", "-t", "nat", "-D", "OUTPUT", "-p", "tcp",
                       "-d", "127.0.0.0/8", "-j", "RETURN", check=False)
            self._run("iptables", "-t", "nat", "-D", "OUTPUT", "-p", "tcp",
                       "-m", "mark", "--mark", str(BYPASS_MARK), "-j", "RETURN", check=False)
            self._run("iptables", "-t", "nat", "-D", "OUTPUT", "-p", "tcp",
                       "-j", "REDIRECT", "--to-port", str(PROXY_PORT), check=False)
            self._run("iptables", "-D", "OUTPUT", "-p", "udp", "--dport", "443",
                       "-j", "REJECT", "--reject-with", "icmp-port-unreachable", check=False)
        except Exception as e:
            log.warning("iptables cleanup: %s", e)
        try:
            if self._rules_added:
                self._run("ip", "rule", "del", "pref", "20000", check=False)
                self._run("ip", "rule", "del", "pref", "1000", check=False)
                self._run("ip", "route", "flush", "cache", check=False)
        except Exception as e:
            log.warning("rule cleanup: %s", e)
        try:
            self._run("ip", "link", "set", self.name, "down", check=False)
            self._run("ip", "addr", "del", TUN_IP + "/24", "dev", self.name, check=False)
        except Exception as e:
            log.warning("link cleanup: %s", e)
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1
            log.info("Closed tun device")
