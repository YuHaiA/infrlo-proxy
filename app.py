"""VLESS over WebSocket with private subscription endpoints.

The hosting platform terminates public HTTPS. Xray is reachable only on loopback.
All deployment credentials are supplied through environment variables.
"""
import asyncio
import base64
import contextlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from urllib.parse import quote, urlencode

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web
import yaml

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8080"))
XRAY_PORT = int(os.environ.get("XRAY_PORT", "10000"))
WS_PATH = os.environ.get("WS_PATH", "/vless")
if not re.fullmatch(r"/[A-Za-z0-9/_-]+", WS_PATH):
    raise ValueError("WS_PATH must be an absolute URL path")
NODE_NAME = os.environ.get("NODE_NAME", "Infrlo-VLESS-WS")
SUB_TOKEN = os.environ.get("SUB_TOKEN", "")
VLESS_UUID = os.environ.get("VLESS_UUID", "")
if VLESS_UUID:
    VLESS_UUID = str(uuid.UUID(VLESS_UUID))
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "").strip().lower()
EXTRA = json.loads(os.environ.get("EXTRA_NODES_JSON", "{}"))


def hostname(request):
    host = PUBLIC_HOST or request.host.split(":", 1)[0].lower()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", host):
        raise web.HTTPBadRequest(text="Invalid service hostname")
    return host


def authorize(request):
    supplied = request.query.get("token", "")
    if not SUB_TOKEN or not hmac.compare_digest(supplied.encode(), SUB_TOKEN.encode()):
        raise web.HTTPUnauthorized(text="Unauthorized", headers={"Cache-Control": "no-store"})
    if not VLESS_UUID:
        raise web.HTTPServiceUnavailable(text="Proxy configuration is incomplete")


def native_proxy(host):
    return {"name": NODE_NAME, "type": "vless", "server": host, "port": 443,
            "uuid": VLESS_UUID, "udp": True, "tls": True, "servername": host,
            "network": "ws", "client-fingerprint": "chrome",
            "ws-opts": {"path": WS_PATH, "headers": {"Host": host}}}


def native_uri(host):
    query = urlencode({"encryption": "none", "security": "tls", "sni": host,
                       "fp": "chrome", "type": "ws", "host": host, "path": WS_PATH})
    return f"vless://{VLESS_UUID}@{host}:443?{query}#{quote(NODE_NAME)}"


async def clash(request):
    authorize(request)
    host = hostname(request)
    proxies = [native_proxy(host)]
    names = {NODE_NAME}
    for proxy in EXTRA.get("clash", []):
        if isinstance(proxy, dict) and proxy.get("name") and proxy["name"] not in names:
            proxies.append(proxy)
            names.add(proxy["name"])
    direct_hosts = [host] + [p["server"] for p in proxies[1:]
                            if p.get("name", "").startswith("NeoHeberg") and p.get("server")]
    config = {"mixed-port": 7890, "allow-lan": False, "mode": "rule", "log-level": "info",
              "ipv6": True, "proxies": proxies,
              "proxy-groups": [{"name": "PROXY", "type": "select", "proxies": [p["name"] for p in proxies] + ["DIRECT"]}],
              "rules": [f"DOMAIN,{domain},DIRECT" for domain in dict.fromkeys(direct_hosts)] + ["GEOIP,CN,DIRECT", "MATCH,PROXY"]}
    return web.Response(text=yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
                        content_type="text/yaml", headers={"Cache-Control": "no-store", "profile-update-interval": "24"})


async def v2ray(request):
    authorize(request)
    uris = list(dict.fromkeys([native_uri(hostname(request))] + EXTRA.get("v2ray", [])))
    data = base64.b64encode(("\n".join(uris) + "\n").encode()).decode()
    return web.Response(text=data, content_type="text/plain", headers={"Cache-Control": "no-store"})


async def health(request):
    process = request.app.get("xray")
    ready = process is not None and process.poll() is None
    return web.Response(text="ok\n" if ready else "setup required\n", status=200 if ready else 503,
                        headers={"Cache-Control": "no-store"})


async def websocket(request):
    process = request.app.get("xray")
    if process is None or process.poll() is not None:
        raise web.HTTPServiceUnavailable(text="Proxy unavailable")
    headers = {}
    if request.headers.get("Sec-WebSocket-Protocol"):
        headers["Sec-WebSocket-Protocol"] = request.headers["Sec-WebSocket-Protocol"]
    try:
        upstream = await request.app["session"].ws_connect(
            f"http://127.0.0.1:{XRAY_PORT}{WS_PATH}", headers=headers,
            compress=0, max_msg_size=8 * 1024 * 1024, heartbeat=30)
    except Exception:
        raise web.HTTPBadGateway(text="Proxy unavailable") from None
    downstream = web.WebSocketResponse(compress=False, max_msg_size=8 * 1024 * 1024, heartbeat=30)
    try:
        await downstream.prepare(request)

        async def pipe(source, destination):
            async for message in source:
                if message.type == WSMsgType.BINARY:
                    await destination.send_bytes(message.data)
                elif message.type == WSMsgType.TEXT:
                    await destination.send_str(message.data)
                elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                    break

        tasks = [asyncio.create_task(pipe(downstream, upstream)), asyncio.create_task(pipe(upstream, downstream))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await upstream.close()
        await downstream.close()
    return downstream


async def lifecycle(app):
    app["session"] = ClientSession(timeout=ClientTimeout(total=None, connect=10))
    process = None
    try:
        if VLESS_UUID and len(SUB_TOKEN) >= 24:
            runtime = ROOT / ".runtime"
            runtime.mkdir(exist_ok=True, mode=0o700)
            config = {"log": {"loglevel": "warning", "access": "none"},
                      "inbounds": [{"listen": "127.0.0.1", "port": XRAY_PORT, "protocol": "vless",
                                    "settings": {"clients": [{"id": VLESS_UUID}], "decryption": "none"},
                                    "streamSettings": {"network": "ws", "wsSettings": {"path": WS_PATH}}}],
                      "outbounds": [{"protocol": "freedom", "tag": "direct"}]}
            config_path = runtime / "xray.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            config_path.chmod(0o600)
            binary = os.environ.get("XRAY_BIN", str(ROOT / "bin" / ("xray.exe" if os.name == "nt" else "xray")))
            process = subprocess.Popen([binary, "run", "-config", str(config_path)],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
            app["xray"] = process
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("Xray exited during startup")
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", XRAY_PORT)
                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Xray did not start listening")
            print("VLESS WebSocket service is ready.", flush=True)
        else:
            print("Set VLESS_UUID and SUB_TOKEN (at least 24 characters), then restart.", flush=True)
        yield
    finally:
        await app["session"].close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 5)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)


def make_app():
    app = web.Application(client_max_size=1024 * 1024)
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.router.add_get("/clash", clash)
    app.router.add_get("/v2ray", v2ray)
    app.router.add_get(WS_PATH, websocket)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host="0.0.0.0", port=PORT, access_log=None,
                print=lambda _: print(f"HTTP service listening on port {PORT}.", flush=True))
