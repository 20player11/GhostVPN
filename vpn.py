import argparse
import signal
import sys
import threading
from utils import log, setup_log, current_ip
from proxy_pool import ProxyPool
from tun import TunManager
from transproxy import TransProxy

def main():
    ap = argparse.ArgumentParser(description="Rotating-IP VPN via SOCKS5 proxy pool")
    ap.add_argument("--interval", type=int, default=180, help="IP rotation interval in seconds (default: 180)")
    ap.add_argument("--verbose", action="store_true", help="verbose output")
    ap.add_argument("--proxies", type=str, help="path to custom proxy list (one per line, host:port)")
    args = ap.parse_args()

    setup_log(args.verbose)
    pool = ProxyPool(interval=args.interval)

    log.info("Building proxy pool...")
    if args.proxies:
        pool.load_file(args.proxies)
    else:
        pool.refresh()

    if pool.get() is None:
        log.error("No working proxies found. Exiting.")
        sys.exit(1)

    ip = current_ip(pool.get())
    log.info("Current IP through proxy: %s", ip or "unknown")

    def on_switch(proxy):
        ip = current_ip(proxy)
        log.info("New IP: %s", ip or "unknown")
    pool.on_switch.append(on_switch)

    tun = TunManager()
    try:
        tun.create()
    except Exception as e:
        log.error("Failed to create tun: %s", e)
        sys.exit(1)
    try:
        tun.setup_routing()
        tun.setup_iptables()
    except Exception as e:
        log.error("Failed to set up routing/iptables: %s", e)
        tun.cleanup()
        sys.exit(1)

    log.info("Routing and iptables configured")

    proxy = TransProxy(pool)
    proxy.start()
    srv_thread = threading.Thread(target=proxy.serve, daemon=True)
    srv_thread.start()

    pool.start_auto_rotate()
    log.info("VPN running. Rotating IP every %d seconds. Press Ctrl+C to stop.", args.interval)

    stop = threading.Event()

    def cleanup(*_):
        log.info("Shutting down...")
        pool.stop()
        proxy.stop()
        tun.cleanup()
        stop.set()

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        stop.wait()
    except KeyboardInterrupt:
        cleanup()

if __name__ == "__main__":
    main()
