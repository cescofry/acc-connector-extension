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
    log.debug("_read_message_sync: waiting for 4-byte length prefix on %r", stream)
    raw_len = stream.read(4)
    log.debug("_read_message_sync: got %d byte(s) for length prefix", len(raw_len))
    if len(raw_len) < 4:
        log.warning("_read_message_sync: short read on length (%d bytes) — EOF or closed stdin", len(raw_len))
        return None
    msg_len = struct.unpack("<I", raw_len)[0]
    log.debug("_read_message_sync: expecting %d byte(s) of payload", msg_len)
    data = stream.read(msg_len)
    log.debug("_read_message_sync: got %d byte(s) of payload", len(data))
    if len(data) < msg_len:
        log.warning("_read_message_sync: short read on payload (%d/%d bytes)", len(data), msg_len)
        return None
    decoded = data.decode("utf-8")
    log.debug("_read_message_sync: decoded payload: %s", decoded)
    return json.loads(decoded)


def _write_message(msg: dict, stream=None) -> None:
    """Write one native messaging frame to stdout.

    ``stream`` defaults to ``sys.stdout.buffer``; pass an explicit file-like
    object to make this function testable without touching sys.stdout.
    """
    if stream is None:
        stream = sys.stdout.buffer
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    log.debug("_write_message: sending %d byte(s): %s", len(data), data[:500])
    stream.write(struct.pack("<I", len(data)))
    stream.write(data)
    stream.flush()
    log.debug("_write_message: flushed")


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
        log.debug("handle: action=%r full_msg=%r", action, msg)

        if action in ("list", "status"):
            state = self._state()
            log.debug("handle list/status: returning %r", state)
            return state

        if action == "add":
            uri = msg.get("uri", "")
            log.debug("handle add: uri=%r", uri)
            try:
                srv = ServerInfo.from_uri(uri)
            except Exception as exc:
                log.warning("handle add: invalid URI %r: %s", uri, exc)
                return {"error": f"Invalid URI: {exc}"}
            if not srv.host:
                log.warning("handle add: missing host in %r", uri)
                return {"error": f"Invalid URI: missing host in {uri!r}"}
            if not self._has_server(srv.host, srv.port):
                log.info("handle add: adding server %s:%d", srv.host, srv.port)
                self._servers.append(srv)
                self._discovery.servers = self._servers
                if srv.persistent:
                    config.save_servers(self._servers)
                    log.debug("handle add: saved persistent server")
            else:
                log.debug("handle add: server %s:%d already present", srv.host, srv.port)
            return self._state()

        if action == "remove":
            host = msg.get("host", "")
            port = int(msg.get("port", 0))
            log.debug("handle remove: host=%r port=%d", host, port)
            before = len(self._servers)
            self._servers = [
                s for s in self._servers
                if not (s.host == host and s.port == port)
            ]
            self._discovery.servers = self._servers
            if len(self._servers) < before:
                log.info("handle remove: removed %s:%d", host, port)
                config.save_servers(self._servers)
            else:
                log.debug("handle remove: server %s:%d not found", host, port)
            return self._state()

        if action == "enable_discovery":
            log.debug("handle enable_discovery")
            try:
                await self._discovery.start()
            except OSError as exc:
                log.error("handle enable_discovery: failed: %s", exc)
                return {"error": str(exc)}
            log.info("handle enable_discovery: started")
            return self._state()

        if action == "disable_discovery":
            log.debug("handle disable_discovery")
            self._discovery.stop()
            return self._state()

        if action == "get_log":
            lines = msg.get("lines", 100)
            log.debug("handle get_log: last %d lines from %s", lines, config.LOG_FILE)
            try:
                text = config.LOG_FILE.read_text(errors="replace")
                tail = "\n".join(text.splitlines()[-lines:])
            except FileNotFoundError:
                log.warning("handle get_log: log file not found at %s", config.LOG_FILE)
                tail = "(log file not found)"
            except Exception as exc:
                log.error("handle get_log: error reading log: %s", exc)
                tail = f"(error reading log: {exc})"
            return {"log": tail}

        log.warning("handle: unknown action %r", action)
        return {"error": f"Unknown action: {action!r}"}

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        log.info("Native host run loop started")
        loop = asyncio.get_running_loop()
        try:
            while True:
                msg = await loop.run_in_executor(None, _read_message_sync)
                if msg is None:
                    log.info("Native host stdin closed — exiting")
                    break
                log.debug("Received: %s", msg)
                response = await self.handle(msg)
                log.debug("Sending: %s", response)
                _write_message(response)
        except Exception:
            log.exception("Unhandled error in run loop")
            raise
        finally:
            self._discovery.stop()
            log.info("Native host stopped")


def main() -> None:
    config.setup_logging()
    import os
    log.info("=== Native host starting (pid=%d) ===", os.getpid())
    log.info("sys.executable: %s", sys.executable)
    log.info("sys.argv: %s", sys.argv)
    log.info("stdin fd=%d isatty=%s", sys.stdin.fileno(), sys.stdin.isatty())
    log.info("stdout fd=%d isatty=%s", sys.stdout.fileno(), sys.stdout.isatty())
    log.info("stderr fd=%d isatty=%s", sys.stderr.fileno(), sys.stderr.isatty())
    for key in ("FLATPAK_ID", "FLATPAK_SANDBOX_DIR", "DBUS_SESSION_BUS_ADDRESS",
                "HOME", "USER", "PATH", "XDG_RUNTIME_DIR"):
        log.info("env %s=%r", key, os.environ.get(key, "<not set>"))
    try:
        servers = config.load_servers()
        log.info("Loaded %d server(s) from config", len(servers))
        host = NativeHost(servers)
        asyncio.run(host.run())
    except Exception:
        log.exception("Fatal error in native host")
        raise


if __name__ == "__main__":
    main()
