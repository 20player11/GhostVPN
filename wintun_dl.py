import os
import ssl
import urllib.request
import zipfile
import shutil

WINTUN_URL = "https://www.wintun.net/builds/wintun-0.14.1.zip"
WINTUN_DIR = os.path.expanduser("~/.ghostvpn")
WINTUN_PATH = os.path.join(WINTUN_DIR, "wintun.dll")

ARCH_MAP = {"amd64": "amd64", "x86_64": "amd64", "i386": "x86", "aarch64": "arm64", "arm64": "arm64"}


def _arch():
    import platform
    m = platform.machine().lower()
    return ARCH_MAP.get(m, "amd64")


def ensure():
    if os.path.isfile(WINTUN_PATH):
        return WINTUN_PATH
    os.makedirs(WINTUN_DIR, exist_ok=True)
    ctx = ssl.create_default_context()
    zip_path = os.path.join(WINTUN_DIR, "wintun.zip")
    try:
        req = urllib.request.Request(WINTUN_URL, headers={"User-Agent": "GhostVPN/1.0"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            with open(zip_path, "wb") as f:
                shutil.copyfileobj(r, f)
        a = _arch()
        with zipfile.ZipFile(zip_path) as z:
            src = f"wintun/bin/{a}/wintun.dll"
            with z.open(src) as s:
                with open(WINTUN_PATH, "wb") as d:
                    shutil.copyfileobj(s, d)
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass
    return WINTUN_PATH
