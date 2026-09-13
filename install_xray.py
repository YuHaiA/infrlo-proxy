"""Install a pinned official Xray release and verify its SHA-256 digest."""
import hashlib
import io
import os
from pathlib import Path
import platform
import time
import urllib.request
import zipfile

VERSION = "v26.3.27"
ASSETS = {
    ("Linux", "x86_64"): ("Xray-linux-64.zip", "23cd9af937744d97776ee35ecad4972cf4b2109d1e0fe6be9930467608f7c8ae"),
    ("Linux", "aarch64"): ("Xray-linux-arm64-v8a.zip", "4d30283ae614e3057f730f67cd088a42be6fdf91f8639d82cb69e48cde80413c"),
    ("Windows", "amd64"): ("Xray-windows-64.zip", "d004c39288ce9ada487c6f398c7c545f7d749e44bdfdd59dbc9f865afba4e1ad"),
}


def main():
    machine = platform.machine().lower()
    machine = {"arm64": "aarch64"}.get(machine, machine) if platform.system() == "Linux" else machine
    asset, digest = ASSETS[(platform.system(), machine)]
    url = f"https://github.com/XTLS/Xray-core/releases/download/{VERSION}/{asset}"
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "infrlo-proxy-installer"})
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read(40 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != digest:
                raise RuntimeError("Xray release checksum mismatch")
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    name = "xray.exe" if os.name == "nt" else "xray"
    destination = Path(__file__).parent / "bin" / name
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        destination.write_bytes(archive.read(name))
    destination.chmod(0o755)
    print(f"Installed official Xray {VERSION}; SHA-256 verified.", flush=True)


if __name__ == "__main__":
    main()
