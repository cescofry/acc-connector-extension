from __future__ import annotations

import json
import logging
from pathlib import Path

try:
    from native_host.models import ServerInfo
except ImportError:
    from models import ServerInfo  # type: ignore[no-redef]

CONFIG_DIR = Path.home() / ".config" / "acc-connector"
SERVERS_FILE = CONFIG_DIR / "servers.json"
LOG_FILE = CONFIG_DIR / "host.log"

log = logging.getLogger(__name__)


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    ensure_config_dir()
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_FILE)],
    )
    log.debug("Logging initialised — log file: %s", LOG_FILE)
    log.debug("Config dir: %s", CONFIG_DIR)
    log.debug("Servers file: %s", SERVERS_FILE)


def load_servers() -> list[ServerInfo]:
    log.debug("load_servers: checking %s", SERVERS_FILE)
    if not SERVERS_FILE.exists():
        log.debug("load_servers: file not found, returning empty list")
        return []
    try:
        text = SERVERS_FILE.read_text()
        log.debug("load_servers: raw content: %s", text)
        uris = json.loads(text)
        servers = [ServerInfo.from_uri(u) for u in uris]
        log.debug("load_servers: loaded %d server(s): %r", len(servers), uris)
        return servers
    except Exception:
        log.exception("Failed to load servers from %s", SERVERS_FILE)
        return []


def save_servers(servers: list[ServerInfo]) -> None:
    ensure_config_dir()
    persistent = [s for s in servers if s.persistent]
    uris = [s.to_uri() for s in persistent]
    log.debug("save_servers: saving %d persistent server(s): %r", len(uris), uris)
    SERVERS_FILE.write_text(json.dumps(uris, indent=2))
    log.debug("save_servers: written to %s", SERVERS_FILE)
