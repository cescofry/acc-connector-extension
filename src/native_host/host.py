#!/usr/bin/env python3
"""ACC Connector — Native Messaging Host.

Communicates with the browser extension via stdin/stdout using the
Native Messaging protocol: 4-byte little-endian length prefix + UTF-8 JSON.

The browser spawns this process on the first connectNative() call and keeps
it alive while the extension port is held open.
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import sys
from typing import Any

try:
    # Installed as a package (normal runtime path).
    from native_host import config
    from native_host.discovery import DiscoveryServer
    from native_host.models import ServerInfo
except ImportError:
    # Running with src/native_host on sys.path (tests / direct invocation).
    import config  # type: ignore[no-redef]
    from discovery import DiscoveryServer  # type: ignore[no-redef]
    from models import ServerInfo  # type: ignore[no-redef]

log = logging.getLogger(__name__)


def _read_message_sync(stream=None) -> dict | None:
    """Read one native messaging frame from stdin (blocking).

    ``stream`` defaults to ``sys.stdin.buffer``; pass an explicit file-like
    object to make this function testable without touching sys.stdin.
    """
    if stream is None:
        stream = sys.stdin.buffer
    raw_len = stream.read(4)
    if len(raw_len) < 4:
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    data = stream.read(msg_len)
    if len(data) < msg_len:
        return None
    return json.loads(data.decode("utf-8"))


def _write_message(msg: dict, stream=None) -> None:
    """Write one native messaging frame to stdout.

    ``stream`` defaults to ``sys.stdout.buffer``; pass an explicit file-like
    object to make this function testable without touching sys.stdout.
    """
    if stream is None:
        stream = sys.stdout.buffer
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    stream.write(struct.pack("<I", len(data)))
    stream.write(data)
    stream.flush()


class NativeHost:
    def __init__(self, servers: list[ServerInfo] | None = None) -> None:
        self._servers: list[ServerInfo] = servers or []
        self._discovery = DiscoveryServer()
        self._discovery.servers = self._servers

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _state(self) -> dict:
        return {
            "servers": [s.to_dict() for s in self._servers],
            "discovery": self._discovery.running,
        }

    def _has_server(self, host: str, port: int) -> bool:
        return any(s.host == host and s.port == port for s in self._servers)

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def handle(self, msg: dict) -> dict:
        action = msg.get("action")

        if action in ("list", "status"):
            return self._state()

        if action == "add":
            uri = msg.get("uri", "")
            try:
                srv = ServerInfo.from_uri(uri)
            except Exception as exc:
                return {"error": f"Invalid URI: {exc}"}
            if not srv.host:
                return {"error": f"Invalid URI: missing host in {uri!r}"}
            if not self._has_server(srv.host, srv.port):
                self._servers.append(srv)
                self._discovery.servers = self._servers
                if srv.persistent:
                    config.save_servers(self._servers)
            return self._state()

        if action == "remove":
            host = msg.get("host", "")
            port = int(msg.get("port", 0))
            before = len(self._servers)
            self._servers = [
                s for s in self._servers
                if not (s.host == host and s.port == port)
            ]
            self._discovery.servers = self._servers
            if len(self._servers) < before:
                config.save_servers(self._servers)
            return self._state()

        if action == "enable_discovery":
            try:
                await self._discovery.start()
            except OSError as exc:
                return {"error": str(exc)}
            return self._state()

        if action == "disable_discovery":
            self._discovery.stop()
            return self._state()

        return {"error": f"Unknown action: {action!r}"}

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                msg = await loop.run_in_executor(None, _read_message_sync)
                if msg is None:
                    break
                log.debug("Received: %s", msg)
                response = await self.handle(msg)
                log.debug("Sending: %s", response)
                _write_message(response)
        finally:
            self._discovery.stop()


def main() -> None:
    config.setup_logging()
    servers = config.load_servers()
    host = NativeHost(servers)
    asyncio.run(host.run())


if __name__ == "__main__":
    main()
