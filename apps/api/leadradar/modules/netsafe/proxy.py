"""In-process egress filtering proxy.

All outbound traffic from workers (HTTPX, Playwright/Chromium, Lighthouse, provider
research) is forced through this proxy on 127.0.0.1. For every connection the proxy:

1. validates scheme/host/port with :mod:`policy`,
2. resolves DNS itself and rejects non-public addresses,
3. connects to the *validated IP* (the browser never resolves names itself, which
   defeats DNS rebinding between check and use),
4. enforces an idle timeout and a byte budget per connection.

Chromium is launched with ``--proxy-server`` pointing here and
``--proxy-bypass-list=<-loopback>`` so that even loopback is proxied (and refused).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from urllib.parse import urlsplit

from leadradar.modules.netsafe.policy import BlockedDestination, check_port, resolve_safe

log = logging.getLogger(__name__)

IDLE_TIMEOUT = 60
MAX_BYTES_PER_CONNECTION = 60 * 1024 * 1024


class EgressProxy:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.host = host
        self.port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: asyncio.AbstractServer | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self.blocked: list[str] = []  # recent blocked targets (bounded) for evidence/debugging

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> EgressProxy:
        self._thread = threading.Thread(target=self._run, name="egress-proxy", daemon=True)
        self._thread.start()
        if not self._ready.wait(10):
            raise RuntimeError("egress proxy failed to start")
        return self

    def stop(self) -> None:
        if self._loop and self._server:
            self._loop.call_soon_threadsafe(self._server.close)
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._server = self._loop.run_until_complete(asyncio.start_server(self._handle, self.host, self.port))
        self.port = self._server.sockets[0].getsockname()[1]
        self._ready.set()
        self._loop.run_forever()

    def _note_block(self, target: str) -> None:
        self.blocked.append(target)
        del self.blocked[:-50]

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
        except (TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        try:
            request_line, *header_lines = head.decode("latin-1").split("\r\n")
            method, target, version = request_line.split(" ", 2)
        except ValueError:
            await self._reply(writer, 400, "Bad Request")
            return
        try:
            if method.upper() == "CONNECT":
                host, _, port_s = target.rpartition(":")
                port = int(port_s)
                check_port(port)
                addrs = await asyncio.get_running_loop().run_in_executor(None, resolve_safe, host.strip("[]"), port)
                upstream_r, upstream_w = await asyncio.wait_for(asyncio.open_connection(addrs[0], port), 15)
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                await self._pipe_both(reader, writer, upstream_r, upstream_w)
            else:
                parts = urlsplit(target)
                if parts.scheme != "http" or not parts.hostname:
                    await self._reply(writer, 400, "Bad Request")
                    return
                port = parts.port or 80
                check_port(port)
                addrs = await asyncio.get_running_loop().run_in_executor(None, resolve_safe, parts.hostname, port)
                upstream_r, upstream_w = await asyncio.wait_for(asyncio.open_connection(addrs[0], port), 15)
                path = parts.path or "/"
                if parts.query:
                    path += "?" + parts.query
                kept = [
                    h
                    for h in header_lines
                    if h and not h.lower().startswith(("proxy-", "connection:", "keep-alive:"))
                ]
                new_head = f"{method} {path} {version}\r\n" + "\r\n".join(kept) + "\r\nConnection: close\r\n\r\n"
                upstream_w.write(new_head.encode("latin-1"))
                await upstream_w.drain()
                await self._pipe_both(reader, writer, upstream_r, upstream_w)
        except BlockedDestination as exc:
            self._note_block(f"{exc.reason}:{exc.target}")
            await self._reply(writer, 403, "Forbidden by LeadRadar egress policy")
        except (OSError, TimeoutError, ValueError):
            await self._reply(writer, 502, "Bad Gateway")

    async def _reply(self, writer: asyncio.StreamWriter, code: int, text: str) -> None:
        with contextlib.suppress(Exception):
            writer.write(f"HTTP/1.1 {code} {text}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
            await writer.drain()
            writer.close()

    async def _pipe_both(self, cr, cw, ur, uw) -> None:  # type: ignore[no-untyped-def]
        budget = [MAX_BYTES_PER_CONNECTION]

        async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await asyncio.wait_for(src.read(65536), IDLE_TIMEOUT)
                    if not data:
                        break
                    budget[0] -= len(data)
                    if budget[0] < 0:
                        break
                    dst.write(data)
                    await dst.drain()
            except (TimeoutError, OSError):
                pass
            finally:
                with contextlib.suppress(Exception):
                    dst.close()

        await asyncio.gather(pipe(cr, uw), pipe(ur, cw))


_proxy: EgressProxy | None = None
_lock = threading.Lock()


def get_egress_proxy() -> EgressProxy:
    global _proxy
    with _lock:
        if _proxy is None:
            _proxy = EgressProxy().start()
            log.info("egress proxy listening", extra={"data": {"port": _proxy.port}})
        return _proxy
