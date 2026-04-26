from __future__ import annotations

import asyncio
import logging
import pathlib
import socket
import subprocess

try:
    from native_host.models import ServerInfo, parse_discovery_request
except ImportError:
    from models import ServerInfo, parse_discovery_request  # type: ignore[no-redef]

DISCOVERY_PORT = 8999
log = logging.getLogger(__name__)

_HERE = pathlib.Path(__file__).resolve().parent

# Well-known install locations for the raw_send binary, checked in order.
_RAW_SEND_CANDIDATES = [
    _HERE / "raw_send",
    _HERE.parent / "raw_send",
    _HERE.parent.parent / "raw_send",
    pathlib.Path.home() / ".local" / "share" / "acc-connector" / "raw_send",
    pathlib.Path.home() / ".local" / "bin" / "acc-connector-raw-send",
]


def _locate_raw_send() -> pathlib.Path:
    for candidate in _RAW_SEND_CANDIDATES:
        if candidate.is_file():
            return candidate
    return pathlib.Path("raw_send")


def _send_spoofed(srv: ServerInfo, discovery_id: int, addr: tuple[str, int]) -> None:
    binary = _locate_raw_send()
    log.debug(
        "raw_send: binary=%s server=%s:%d dest=%s:%d id=%d",
        binary, srv.resolve_ip(), srv.port, addr[0], addr[1], discovery_id,
    )
    result = subprocess.run(
        [
            str(binary),
            srv.resolve_ip(),
            str(srv.port),
            srv.display_name(),
            str(discovery_id),
            addr[0],
            str(addr[1]),
        ],
        check=True,
        timeout=2,
        capture_output=True,
    )
    if result.stderr:
        log.warning("raw_send stderr: %s", result.stderr.decode(errors="replace").strip())


class DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, server: DiscoveryServer) -> None:
        self._server = server
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:  # type: ignore[override]
        self.transport = transport
        sock = transport.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        discovery_id = parse_discovery_request(data)
        if discovery_id is None:
            return
        log.info(
            "Discovery request from %s port=%d id=%d servers=%d",
            addr[0], addr[1], discovery_id, len(self._server.servers),
        )
        for srv in self._server.servers:
            try:
                _send_spoofed(srv, discovery_id, addr)
                log.debug("Sent response for %s to %s", srv.display_name(), addr)
            except Exception:
                log.exception("Failed to send response for %s", srv.display_name())

    def error_received(self, exc: Exception) -> None:
        log.error("UDP error: %s", exc)

    def connection_lost(self, exc: Exception | None) -> None:
        pass


class DiscoveryServer:
    def __init__(self) -> None:
        self.servers: list[ServerInfo] = []
        self._transport: asyncio.DatagramTransport | None = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        raw_send_path = _locate_raw_send()
        log.info("raw_send binary resolved to: %s (exists=%s)", raw_send_path, raw_send_path.is_file())
        loop = asyncio.get_running_loop()
        try:
            transport, _ = await loop.create_datagram_endpoint(
                lambda: DiscoveryProtocol(self),
                local_addr=("0.0.0.0", DISCOVERY_PORT),
                allow_broadcast=True,
                reuse_address=True,
            )
            self._transport = transport
            self._running = True
            log.info("Discovery server listening on UDP port %d", DISCOVERY_PORT)
        except OSError as e:
            log.error("Failed to bind port %d: %s", DISCOVERY_PORT, e)
            raise

    def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None
        self._running = False
        log.info("Discovery server stopped")
