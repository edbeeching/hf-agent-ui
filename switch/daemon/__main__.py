from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal

from .registration import HubRegistration
from .session_manager import SessionManager
from .ws_server import DaemonWsServer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="switch-daemon",
        description="Switch daemon — wraps AI coding sessions (Claude Code, Codex) on this machine",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=int(os.environ.get("SWITCH_DAEMON_PORT", "9340")),
        help="WebSocket port to listen on (default: 9340, env: SWITCH_DAEMON_PORT)",
    )
    parser.add_argument(
        "--hub",
        default=os.environ.get("SWITCH_HUB_URL", "http://localhost:9341"),
        help="Hub URL to register with (default: http://localhost:9341, env: SWITCH_HUB_URL)",
    )
    parser.add_argument(
        "-n", "--name",
        default=os.environ.get("SWITCH_DAEMON_NAME"),
        help="Daemon display name (default: daemon-<port>, env: SWITCH_DAEMON_NAME)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    name = args.name or f"daemon-{args.port}"

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[switch-daemon] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    manager = SessionManager()
    ws_server = DaemonWsServer(manager, args.port)
    registration = HubRegistration(args.hub, name, args.port)

    await ws_server.start()

    await registration.register()
    await registration.start_heartbeat()

    logger.info("Ready — listening on :%d, registered with hub at %s", args.port, args.hub)

    stop_event = asyncio.Event()

    def on_signal() -> None:
        logger.info("Shutting down...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, on_signal)

    await stop_event.wait()

    manager.stop_all()
    await ws_server.stop()
    await registration.stop()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
