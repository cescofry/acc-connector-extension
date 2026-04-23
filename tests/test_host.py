"""Tests for the native messaging host (host.py).

Tests cover:
- _read_message_sync / _write_message round-trip
- NativeHost.handle() for every action
- State management: add, remove, list, enable/disable discovery
- Error paths: invalid URI, unknown action
"""
from __future__ import annotations

import asyncio
import io
import json
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from host import NativeHost, _read_message_sync, _write_message
from models import ServerInfo


# ------------------------------------------------------------------
# Frame codec
# ------------------------------------------------------------------

def _encode(msg: dict) -> bytes:
    data = json.dumps(msg).encode()
    return struct.pack("<I", len(data)) + data


class TestReadMessage:
    def test_reads_valid_message(self):
        msg = _read_message_sync(io.BytesIO(_encode({"action": "list"})))
        assert msg == {"action": "list"}

    def test_returns_none_on_empty_stream(self):
        assert _read_message_sync(io.BytesIO(b"")) is None

    def test_returns_none_on_truncated_header(self):
        assert _read_message_sync(io.BytesIO(b"\x05\x00")) is None

    def test_returns_none_on_truncated_body(self):
        buf = io.BytesIO(struct.pack("<I", 100) + b"\x00" * 5)
        assert _read_message_sync(buf) is None

    def test_reads_message_with_unicode(self):
        payload = {"action": "add", "uri": "acc-connect://192.168.1.1:9911?name=Ünïcödé"}
        msg = _read_message_sync(io.BytesIO(_encode(payload)))
        assert msg["uri"] == payload["uri"]


class TestWriteMessage:
    def test_round_trip(self):
        buf = io.BytesIO()
        _write_message({"ok": True}, buf)
        buf.seek(0)
        length = struct.unpack("<I", buf.read(4))[0]
        body = json.loads(buf.read(length))
        assert body == {"ok": True}

    def test_length_prefix_matches_body(self):
        buf = io.BytesIO()
        _write_message({"servers": [], "discovery": False}, buf)
        buf.seek(0)
        length = struct.unpack("<I", buf.read(4))[0]
        assert length == len(buf.read())


# ------------------------------------------------------------------
# NativeHost.handle() — unit tests with mocked DiscoveryServer
# ------------------------------------------------------------------

@pytest.fixture
def native_host():
    h = NativeHost()
    mock_discovery = MagicMock()
    mock_discovery.running = False
    mock_discovery.servers = []
    h._discovery = mock_discovery
    return h


class TestHandleList:
    def test_returns_state(self, native_host):
        result = asyncio.run(native_host.handle({"action": "list"}))
        assert "servers" in result
        assert "discovery" in result

    def test_status_alias(self, native_host):
        result = asyncio.run(native_host.handle({"action": "status"}))
        assert "servers" in result


class TestHandleAdd:
    def test_adds_server(self, native_host):
        asyncio.run(native_host.handle({
            "action": "add",
            "uri": "acc-connect://127.0.0.1:9911?persistent=true",
        }))
        assert len(native_host._servers) == 1
        assert native_host._servers[0].host == "127.0.0.1"

    def test_returns_updated_state(self, native_host):
        result = asyncio.run(native_host.handle({
            "action": "add",
            "uri": "acc-connect://127.0.0.1:9911?persistent=true",
        }))
        assert len(result["servers"]) == 1

    def test_no_duplicate_on_same_host_port(self, native_host):
        uri = "acc-connect://127.0.0.1:9911?persistent=true"
        asyncio.run(native_host.handle({"action": "add", "uri": uri}))
        asyncio.run(native_host.handle({"action": "add", "uri": uri}))
        assert len(native_host._servers) == 1

    def test_invalid_uri_returns_error(self, native_host):
        result = asyncio.run(native_host.handle({"action": "add", "uri": "not-a-uri"}))
        assert "error" in result

    def test_updates_discovery_servers(self, native_host):
        asyncio.run(native_host.handle({
            "action": "add",
            "uri": "acc-connect://127.0.0.1:9911?persistent=false",
        }))
        assert native_host._discovery.servers is native_host._servers

    @patch("host.config")
    def test_saves_persistent_server(self, mock_config, native_host):
        asyncio.run(native_host.handle({
            "action": "add",
            "uri": "acc-connect://127.0.0.1:9911?persistent=true",
        }))
        mock_config.save_servers.assert_called_once()

    @patch("host.config")
    def test_does_not_save_non_persistent_server(self, mock_config, native_host):
        asyncio.run(native_host.handle({
            "action": "add",
            "uri": "acc-connect://127.0.0.1:9911?persistent=false",
        }))
        mock_config.save_servers.assert_not_called()


class TestHandleRemove:
    def _add(self, host_obj, uri):
        asyncio.run(host_obj.handle({"action": "add", "uri": uri}))

    def test_removes_matching_server(self, native_host):
        self._add(native_host, "acc-connect://127.0.0.1:9911?persistent=false")
        asyncio.run(native_host.handle({"action": "remove", "host": "127.0.0.1", "port": 9911}))
        assert len(native_host._servers) == 0

    def test_no_error_on_missing_server(self, native_host):
        result = asyncio.run(native_host.handle({"action": "remove", "host": "1.2.3.4", "port": 9911}))
        assert "error" not in result

    def test_returns_updated_state(self, native_host):
        self._add(native_host, "acc-connect://127.0.0.1:9911?persistent=false")
        result = asyncio.run(native_host.handle({"action": "remove", "host": "127.0.0.1", "port": 9911}))
        assert result["servers"] == []

    def test_only_removes_matching(self, native_host):
        self._add(native_host, "acc-connect://127.0.0.1:9911?persistent=false")
        self._add(native_host, "acc-connect://127.0.0.1:9912?persistent=false")
        asyncio.run(native_host.handle({"action": "remove", "host": "127.0.0.1", "port": 9911}))
        assert len(native_host._servers) == 1
        assert native_host._servers[0].port == 9912


class TestHandleDiscovery:
    def test_enable_discovery_calls_start(self, native_host):
        native_host._discovery.start = AsyncMock()
        asyncio.run(native_host.handle({"action": "enable_discovery"}))
        native_host._discovery.start.assert_awaited_once()

    def test_enable_discovery_returns_state(self, native_host):
        native_host._discovery.start = AsyncMock()
        native_host._discovery.running = True
        result = asyncio.run(native_host.handle({"action": "enable_discovery"}))
        assert result["discovery"] is True

    def test_enable_discovery_oserror_returns_error(self, native_host):
        native_host._discovery.start = AsyncMock(side_effect=OSError("port in use"))
        result = asyncio.run(native_host.handle({"action": "enable_discovery"}))
        assert "error" in result

    def test_disable_discovery_calls_stop(self, native_host):
        asyncio.run(native_host.handle({"action": "disable_discovery"}))
        native_host._discovery.stop.assert_called_once()

    def test_disable_discovery_returns_state(self, native_host):
        result = asyncio.run(native_host.handle({"action": "disable_discovery"}))
        assert "discovery" in result


class TestHandleUnknownAction:
    def test_returns_error(self, native_host):
        result = asyncio.run(native_host.handle({"action": "frobulate"}))
        assert "error" in result
        assert "frobulate" in result["error"]
