# GhostVPN 👻

A system-wide rotating-IP VPN that routes all TCP traffic through a pool of free SOCKS5 proxies and changes your public IP every N minutes. No paid APIs, no subscriptions — just Python and free public proxy lists.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Platform](https://img.shields.io/badge/platform-linux-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

## How it works

```
                          ┌──────────────────────┐
Your browser ──▶ tun0 ──▶ │ iptables REDIRECT    │
                          │  → TCP → :12345      │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │ Local transparent    │
                          │ proxy (transproxy.py)│
                          │ → reads original dst │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼───────────┐
                          │ SOCKS5 proxy pool    │
                          │ (rotates every N s)  │
                          └──────────┬───────────┘
                                     ▼
                                  Internet
                              (exit IP changes
                               on rotation)
```

1. **tun0** — virtual network interface created by the kernel
2. **Policy routing** — all unmarked TCP traffic is routed through `tun0`
3. **iptables REDIRECT** — intercepts TCP before it enters `tun0`, sends to local proxy
4. **Transproxy** — reads the original destination via `SO_ORIGINAL_DST`, forwards through a SOCKS5 proxy
5. **Proxy pool** — auto-fetches free SOCKS5 proxies from public lists, health-checks them, rotates the active one on a timer
6. **Bypass routing** — the proxy's own upstream connections are `fwmark`-ed to use the original network (no loops)

## Requirements

| Dependency                         | Why                                                               |
| ---------------------------------- | ----------------------------------------------------------------- |
| Linux (Mint, Ubuntu, Debian, etc.) | Uses `tun`, `iptables`, `ip`                                      |
| Root access                        | Creating tun devices and modifying routing tables requires `sudo` |
| Python 3.10+                       | f-strings, type hints                                             |
| `PySocks`                          | SOCKS5 client protocol                                            |

## Installation

```bash
# Clone or enter the project
cd ~/Programming/Python/vpn

# Create virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install the only dependency
pip install PySocks==1.7.1
```

## Usage

```bash
sudo .venv/bin/python3 vpn.py
```

### Options

| Flag         | Default | Description                                            |
| ------------ | ------- | ------------------------------------------------------ |
| `--interval` | `180`   | Seconds between IP rotations                           |
| `--proxies`  | `—`     | Path to a custom proxy list (one `host:port` per line) |
| `--verbose`  | `off`   | Show debug-level logs                                  |

### Examples

```bash
# Default — rotate every 3 minutes
sudo .venv/bin/python3 vpn.py

# Rotate every 30 seconds
sudo .venv/bin/python3 vpn.py --interval 30

# Use your own proxy list (bypasses auto-fetch)
sudo .venv/bin/python3 vpn.py --proxies my_proxies.txt

# Verbose mode for debugging
sudo .venv/bin/python3 vpn.py --verbose
```

### Stopping

Press **Ctrl+C**. The cleanup handler automatically:

- Flushes iptables rules
- Removes routing rules
- Brings down `tun0`
- Closes the proxy

## Verification

While the VPN is running, open another terminal:

```bash
# Check your public IP
curl ifconfig.me

# It should show the proxy's IP, not yours.
# Wait for rotation and run again — IP should change.
```

Or watch it live:

```bash
watch -n 10 curl -s ifconfig.me
```

## Architecture

```
vpn/
├── vpn.py            # CLI entry, daemon lifecycle, rotation timer
├── tun.py            # tun0 creation, policy routing, iptables rules
├── transproxy.py     # Transparent TCP → SOCKS5 proxy
├── proxy_pool.py     # Auto-fetch, health-check, proxy rotation
├── utils.py          # Logging, SO_ORIGINAL_DST, IP lookup
├── requirements.txt  # PySocks==1.7.1
└── README.md
```

### proxy_pool.py

- Fetches SOCKS5 proxies from 3 public GitHub proxy lists (~6000 raw entries)
- Randomly samples and tests up to 200 with threaded SOCKS5 handshakes
- Maintains a pool of working proxies
- `switch()` picks the next one; `start_auto_rotate()` runs it on a timer
- Supports callbacks via `on_switch` for logging IP changes

### tun.py

- Opens `/dev/net/tun`, configures it as `tun0`
- Assigns IP `10.0.0.1/24`
- Creates routing table 100 with default via `tun0`
- Policy routing: `fwmark 1` → main table (bypass), everything else → table 100
- iptables OUTPUT REDIRECT: all TCP (except `127.*` and marked packets) → port 12345

### transproxy.py

- Listens on `0.0.0.0:12345`
- Reads original destination via `SO_ORIGINAL_DST` (Linux conntrack)
- Creates a SOCKS5 connection through the active proxy
- Pipes data bidirectionally with threads

## Limitations

| Limitation                 | Reason                                                                                         |
| -------------------------- | ---------------------------------------------------------------------------------------------- |
| **TCP only**               | Free SOCKS5 proxies rarely support UDP ASSOCIATE. DNS, ping, etc. won't route through the VPN. |
| **Free proxy reliability** | Public proxies are slow and drop frequently. The pool handles rotation gracefully.             |
| **Root required**          | `tun` devices, `iptables`, and routing changes need `sudo`.                                    |
| **Linux only**             | Uses Linux-specific features (`/dev/net/tun`, `iptables`, `ip`).                               |
| **DNS leaks**              | DNS over UDP bypasses the proxy. Use DNS-over-TCP or a browser with DoH if needed.             |

## Custom proxy lists

Format: one `host:port` per line, `#` for comments.

```
# my proxies
1.2.3.4:1080
5.6.7.8:1080
9.10.11.12:1080
```

```bash
sudo .venv/bin/python3 vpn.py --proxies my_proxies.txt
```

## Troubleshooting

### "File or stream is not seekable"

Python 3.12 incompatibility. Fixed in current code — uses raw `os.open`/`os.read`/`os.write`.

### "No working proxies found"

The auto-fetch timed out or the proxy lists changed. Try again, or provide your own list with `--proxies`.

### Internet stops after Ctrl+C

The cleanup should restore everything. If not:

```bash
sudo iptables -t nat -F OUTPUT
sudo ip rule del pref 20000
sudo ip rule del pref 1000
sudo ip link del tun0
```

## Project status

Educational project. Works for basic privacy use (hiding your IP for web browsing). Not suitable for high-security or streaming scenarios.

## License

MIT
