from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal

from .hub_client import HubDaemonClient
from .session_manager import SessionManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="switch-daemon",
        description="Switch daemon — wraps AI coding sessions (Claude Code, Codex) on this machine",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=int(os.environ.get("SWITCH_DAEMON_PORT", "9340")),
        help="Deprecated; ignored in outbound mode",
    )
    parser.add_argument(
        "--hub",
        default=os.environ.get("SWITCH_HUB_URL", "http://localhost:9341"),
        help="Hub URL to register with (default: http://localhost:9341, env: SWITCH_HUB_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SWITCH_DAEMON_TOKEN"),
        help="Daemon auth token (env: SWITCH_DAEMON_TOKEN)",
    )
    parser.add_argument(
        "--hf-token",
        default=os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"),
        help="Hugging Face token for private Spaces (env: HF_TOKEN)",
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
    client = HubDaemonClient(manager, args.hub, name, token=args.token, hf_token=args.hf_token)
    client_task = asyncio.create_task(client.run_forever())

    logger.info("Ready — connecting outbound to hub at %s", args.hub)

    stop_event = asyncio.Event()

    def on_signal() -> None:
        logger.info("Shutting down...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, on_signal)

    await stop_event.wait()

    client.stop()
    client_task.cancel()
    try:
        await client_task
    except asyncio.CancelledError:
        pass
    manager.stop_all()


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
