# GhostVPN 👻

A rotating-IP VPN that routes your traffic through a pool of free SOCKS5 proxies and changes your public IP every N minutes. No paid APIs, no subscriptions.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-linux%20|%20macOS%20|%20windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)
![Security](https://img.shields.io/badge/security-CodeQL%20|%20Dependabot-brightgreen)

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
         │   proxy1:1080 ──▶ internet (IP 1)          │
         │   proxy2:1080 ──▶ internet (IP 2)          │
         │   proxy3:1080 ──▶ internet (IP 3) ...      │
         └────────────────────────────────────────────┘
```

Two modes:

- **TUN mode** (Linux) — system-wide VPN using `tun` + `iptables`. All TCP traffic goes through the proxy automatically.
- **SOCKS mode** (Linux, macOS, Windows) — local SOCKS5 proxy on `127.0.0.1:1080`. Configure your apps or system proxy to use it.

## Quick start

### Linux (TUN mode — full system VPN)

```bash
cd GhostVPN
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Interactive menu (recommended)
sudo .venv/bin/python3 vpn.py

# CLI mode (for scripts)
sudo .venv/bin/python3 vpn.py --cli --interval 30
```

The interactive menu starts the VPN from option **[1]**. Configure settings via option **[2]**.

### macOS (SOCKS mode)

```bash
cd GhostVPN
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Interactive menu (no root needed)
python3 vpn.py

# Or use settings → enable system proxy, or run directly:
python3 vpn.py --cli --mode socks --sys-proxy
```

Configure your browser to use SOCKS5 `127.0.0.1:1080`, or let GhostVPN set the system proxy automatically.

### Windows (SOCKS mode)

```powershell
cd GhostVPN
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Interactive menu
python vpn.py

# CLI mode with system proxy
python vpn.py --cli --mode socks --sys-proxy
```

## Usage

### Interactive menu (default)

Run `python vpn.py` to see:

```
   ________  ______  ____________    ______  _   __
  / ____/ / / / __ \/ ___/_  __/ |  / / __ \/ | / /
 / / __/ /_/ / / / /\__ \ / /  | | / / /_/ /  || /
/ /_/ / __  / /_/ /___/ // /   | |/ / ____/ /|  /
\____/_/ /_/\____//____//_/    |___/_/   /_/ |_/

              👻  ROTATING IP VPN  👻

  MAIN MENU

     [1] ▶  START VPN  (TUN (Linux))
         interval=180s  port=1080

     [2] Settings
     [3] About
     [4] Exit

  └─ Choice:
```

- **[1]** — starts the VPN with current settings
- **[2]** — configure mode, interval, port, proxy source, system proxy
- **[3]** — version, license, repo link
- **[4]** — exit

### CLI mode (`--cli`)

```
python vpn.py --cli [options]
```

| Flag           | Default                       | Description                                       |
| -------------- | ----------------------------- | ------------------------------------------------- |
| `--mode`       | `tun` (Linux), `socks` (else) | `tun` = system VPN (Linux), `socks` = local proxy |
| `--interval`   | `180`                         | Seconds between IP rotations                      |
| `--proxies`    | `—`                           | Path to custom proxy list (`host:port` per line)  |
| `--proxy-port` | `1080`                        | Local SOCKS proxy port (socks mode)               |
| `--sys-proxy`  | `off`                         | Automatically set system proxy (macOS/Windows)    |
| `--verbose`    | `off`                         | Debug-level logs                                  |

### Custom proxy lists

```bash
python vpn.py --cli --mode socks --proxies proxies.txt
```

## Platform comparison

| Feature             | Linux (TUN)      | macOS (SOCKS)        | Windows (SOCKS)      |
| ------------------- | ---------------- | -------------------- | -------------------- |
| System-wide routing | ✅ Automatic     | ⚠️ Manual app config | ⚠️ Manual app config |
| Root required       | ✅ Yes           | ❌ No                | ❌ No                |
| Proxy rotation      | ✅               | ✅                   | ✅                   |
| Auto system proxy   | ❌               | ✅ `--sys-proxy`     | ✅ `--sys-proxy`     |
| UDP/ICMP            | ❌ Not supported | ❌ Not supported     | ❌ Not supported     |

## Verification

```bash
watch -n 10 curl -s ifconfig.me
```

## Security

GhostVPN has the following security features enabled:

- **Private vulnerability reporting** — report issues privately at https://github.com/20player11/GhostVPN/security/advisories
- **Dependabot alerts** — automatic notifications for vulnerable dependencies
- **Dependabot security fixes** — auto-generated PRs for patched dependencies
- **CodeQL code scanning** — runs on every push/PR via GitHub Actions
- **SECURITY.md** — disclosure policy with 24h/7d/30d response timeline

## Project structure

```
vpn/
├── vpn.py            # CLI entry — interactive menu or --cli mode
├── tun.py            # Linux TUN device, routing, iptables
├── transproxy.py     # Linux transparent TCP → SOCKS5 proxy
├── local_proxy.py    # Cross-platform SOCKS5 proxy server
├── proxy_pool.py     # Auto-fetch, health-check, rotation
├── utils.py          # Logging, IP lookup, helpers
├── requirements.txt  # PySocks + pyfiglet
├── SECURITY.md       # Disclosure policy
├── LICENSE           # MIT
└── README.md
```

## Troubleshooting

### Linux: "Failed to create tun"

```bash
sudo modprobe tun
```

### macOS: "networksetup" errors

Approve Terminal in `System Settings → Privacy & Security → Accessibility`.

### No working proxies found

Proxy lists change. Try again later or use `--proxies` with your own list.

### Internet stops after Ctrl+C (Linux)

```bash
sudo iptables -t nat -F OUTPUT
sudo ip rule del pref 20000 2>/dev/null
sudo ip rule del pref 1000 2>/dev/null
sudo ip link del tun0 2>/dev/null
```

## Dependencies

- [PySocks](https://github.com/Anorov/PySocks) — SOCKS5 client protocol
- [pyfiglet](https://github.com/pwaller/pyfiglet) — ASCII art generation

## License

MIT
