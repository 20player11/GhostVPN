# GhostVPN 👻

A rotating-IP VPN that routes your traffic through a pool of free SOCKS5 proxies and changes your public IP every N minutes. No paid APIs, no subscriptions.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-linux%20|%20macOS%20|%20windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

## How it works

```
                          ┌──────────────────────┐
Your browser ──▶ tun0 ──▶ │ iptables REDIRECT    │
      │                   │  → TCP → :12345      │
      │                   └──────────┬───────────┘
      │                              │
      │  ┌───────────────────────────▼───────────────┐
      └──│ SOCKS5 proxy pool (rotates every N s)     │
         │                                            │
         │   http://proxy1:1080 ──▶ internet (IP 1)   │
         │   http://proxy2:1080 ──▶ internet (IP 2)   │
         │   http://proxy3:1080 ──▶ internet (IP 3)   │
         └────────────────────────────────────────────┘
```

Two modes:

- **TUN mode** (Linux) — system-wide VPN using `tun` + `iptables`. All TCP traffic goes through the proxy automatically.
- **SOCKS mode** (Linux, macOS, Windows) — local SOCKS5 proxy on `127.0.0.1:1080`. Configure your apps or system proxy to use it.

## Quick start

### Linux (TUN mode — full system VPN)

```bash
# Install
cd GhostVPN
python3 -m venv .venv
source .venv/bin/activate
pip install PySocks==1.7.1

# Run (root required for TUN mode)
sudo .venv/bin/python3 vpn.py

# Rotate every 30 seconds
sudo .venv/bin/python3 vpn.py --interval 30

# Verbose debug output
sudo .venv/bin/python3 vpn.py --verbose
```

The TUN mode is **the default on Linux**. It creates a `tun0` interface and routes all TCP traffic through rotating proxies automatically.

### macOS (SOCKS mode)

```bash
# Install
cd GhostVPN
python3 -m venv .venv
source .venv/bin/activate
pip install PySocks==1.7.1

# Run in SOCKS mode (no root needed)
python3 vpn.py --mode socks

# Auto-configure system proxy (enables macOS network proxy)
python3 vpn.py --mode socks --sys-proxy

# Custom port
python3 vpn.py --mode socks --proxy-port 9090
```

Then configure your apps (or system):

- **System-wide**: `System Settings → Network → Proxies → SOCKS proxy → 127.0.0.1:1080`
- **Or automatically**: use `--sys-proxy` flag (runs `networksetup` for you)
- **Browser**: Firefox → Settings → Network → Proxy → Manual → SOCKS Host `127.0.0.1` Port `1080`
- **Terminal**: `export ALL_PROXY=socks5://127.0.0.1:1080`

To restore system proxy settings without restarting: `python3 vpn.py --mode socks --sys-proxy` and press Ctrl+C (it disables on exit).

### Windows (SOCKS mode)

```powershell
# Install
cd GhostVPN
python -m venv .venv
.venv\Scripts\activate
pip install PySocks==1.7.1

# Run (SOCKS mode is default on Windows)
python vpn.py --mode socks

# With automatic Windows system proxy
python vpn.py --mode socks --sys-proxy
```

Then configure your apps:

- **System-wide**: `Settings → Network & Internet → Proxy → Use a proxy server → Address: 127.0.0.1 Port: 1080`
- **Or automatically**: use `--sys-proxy` flag (sets Windows proxy registry)
- **Browser**: Firefox → Settings → Network → Proxy → Manual → SOCKS Host `127.0.0.1` Port `1080`
- **PowerShell**: `$env:ALL_PROXY="socks5://127.0.0.1:1080"`

## Usage

```
usage: vpn.py [-h] [--mode {tun,socks}] [--interval INTERVAL] [--verbose]
              [--proxies PROXIES] [--proxy-port PROXY_PORT] [--sys-proxy]

GhostVPN — rotating-IP VPN via SOCKS5 proxy pool
```

| Flag           | Default                       | Description                                             |
| -------------- | ----------------------------- | ------------------------------------------------------- |
| `--mode`       | `tun` (Linux), `socks` (else) | `tun` = system VPN (Linux), `socks` = local proxy       |
| `--interval`   | `180`                         | Seconds between IP rotations                            |
| `--proxies`    | `—`                           | Path to custom proxy list (`host:port` per line)        |
| `--proxy-port` | `1080`                        | Local SOCKS proxy port (socks mode)                     |
| `--sys-proxy`  | `off`                         | Automatically set system proxy settings (macOS/Windows) |
| `--verbose`    | `off`                         | Debug-level logs                                        |

### Custom proxy lists

```
# proxies.txt
1.2.3.4:1080
5.6.7.8:1080
```

```bash
python3 vpn.py --mode socks --proxies proxies.txt
```

## Platform comparison

| Feature             | Linux (TUN)      | macOS (SOCKS)        | Windows (SOCKS)      |
| ------------------- | ---------------- | -------------------- | -------------------- |
| System-wide routing | ✅ Automatic     | ⚠️ Manual app config | ⚠️ Manual app config |
| Root required       | ✅ Yes           | ❌ No                | ❌ No                |
| Proxy rotation      | ✅               | ✅                   | ✅                   |
| Auto system proxy   | ❌ (manual)      | ✅ `--sys-proxy`     | ✅ `--sys-proxy`     |
| UDP/ICMP            | ❌ Not supported | ❌ Not supported     | ❌ Not supported     |

## Verification

```bash
# Watch your IP change
watch -n 10 curl -s ifconfig.me
```

## Project structure

```
vpn/
├── vpn.py            # CLI entry, platform detection, mode selection
├── tun.py            # Linux TUN device, routing, iptables
├── transproxy.py     # Linux transparent TCP → SOCKS5 proxy
├── local_proxy.py    # Cross-platform SOCKS5 proxy server
├── proxy_pool.py     # Auto-fetch, health-check, rotation
├── utils.py          # Logging, IP lookup, helpers
├── requirements.txt  # PySocks==1.7.1
└── README.md
```

## Troubleshooting

### Linux: "Failed to create tun"

Make sure `tun` kernel module is loaded:

```bash
sudo modprobe tun
```

### macOS: "networksetup" errors with `--sys-proxy`

You may need to approve Terminal in `System Settings → Privacy & Security → Accessibility`.

### Windows: "python" not found

Use `py` or `python3` depending on your install. Ensure Python is in PATH.

### No working proxies found

Proxy lists may change. Try again later or use `--proxies` with your own list.

### Internet stops after Ctrl+C (Linux)

Run these to restore:

```bash
sudo iptables -t nat -F OUTPUT
sudo ip rule del pref 20000 2>/dev/null
sudo ip rule del pref 1000 2>/dev/null
sudo ip link del tun0 2>/dev/null
```

## Dependencies

- [PySocks](https://github.com/Anorov/PySocks) — SOCKS5 client protocol

## License

MIT
