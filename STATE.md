# GhostVPN Session State

**Current version:** v1.3.1  
**Last commit:** UX: config persistence and live status bar (`e6bbce8`)  
**Remote:** origin/main at https://github.com/20player11/GhostVPN

## How to run

```bash
cd /home/ondrej/Programming/Python/vpn
sudo .venv/bin/python3 vpn.py --cli --mode tun --verbose
```

## Implemented

### v1.3.1 — UX

- Config persistence: saved to `~/.ghostvpn_config`
- Live ANSI status bar (uptime, connections, transfer, pool, proxy)
- Stats tracking in TransProxy (bytes up/down, connection count)

### v1.3.0 — Kill switch + DNS leak fix

- `--kill-switch` flag: drops connections when all proxies fail
- DNS leak fix: `dns.py` forwarder resolves via SOCKS5 TCP to 1.1.1.1
- iptables redirect UDP 53 → 5353
- Settings menu toggle for kill switch

### v1.2.3 — Core overhaul

- Proxy pool: 6 sources, HTTP validation, DNS fallback, disk cache, scoring
- `select()`-based `_pipe` (1 thread per connection instead of 2)
- Retry loop in `_handle` with direct fallback
- Port mismatch fixed (PROXY_PORT=12345 matches TransProxy)
- `--cli` flag fixed (no longer exits with help)
- QUIC blocked (iptables reject UDP 443)
- `switch()` simplified to pure round-robin (no TUN loop)
- Auto-rotate race fixed (`_running` flag)

## Files

| File               | Purpose                                              |
| ------------------ | ---------------------------------------------------- |
| `vpn.py`           | Entry point, CLI/menu, config persistence            |
| `tun.py`           | TUN device, routing, iptables (TCP/DNS/QUIC)         |
| `transproxy.py`    | Transparent TCP proxy with retry, kill switch, stats |
| `local_proxy.py`   | SOCKS5 proxy server (cross-platform)                 |
| `proxy_pool.py`    | Pool: fetch, check, cache, rotate, scoring           |
| `dns.py`           | DNS forwarder over SOCKS5 TCP to 1.1.1.1             |
| `utils.py`         | Logging, IP lookup, helpers                          |
| `requirements.txt` | PySocks, pyfiglet                                    |

## Issues

### Closed (#28, #29)

Status display and config persistence — done in v1.3.1.

### Open

- **#25** — Pre-emptive proxy health check
- **#26** — Adaptive rotation interval
- **#27** — Dead proxy eviction from pool
- **#30** — SOCKS4/HTTP proxy type support
- **#31** — Split tunneling (CIDR allowlist)
- **#32** — UDP relay over SOCKS5

## Release workflow

```bash
git add -A && git commit -m "message" && git push
rm -f ghostvpn-<ver>.zip && zip ghostvpn-<ver>.zip vpn.py proxy_pool.py transproxy.py local_proxy.py tun.py utils.py dns.py requirements.txt
gh release create v<ver> --title "v<ver>" --notes "..."
gh release upload v<ver> ghostvpn-<ver>.zip --clobber
```
