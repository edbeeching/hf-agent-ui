from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import signal

from switch.hf_auth import resolve_hf_token

from .hub_client import HubDaemonClient
from .session_manager import SessionManager


def default_daemon_name(args: argparse.Namespace) -> str:
    return args.name or platform.node() or f"daemon-{args.port}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="switch host",
        description="agentic-ui agent host — wraps AI coding sessions (Claude Code, Codex) on this machine",
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
        help="Agent host auth token (env: SWITCH_DAEMON_TOKEN)",
    )
    parser.add_argument(
        "--hf-token",
        default=None,
        help="Hugging Face token for private Spaces (env: HF_TOKEN, or local HF login cache)",
    )
    parser.add_argument(
        "-n", "--name",
        default=os.environ.get("SWITCH_DAEMON_NAME"),
        help="Agent host display name (default: hostname, env: SWITCH_DAEMON_NAME)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    name = default_daemon_name(args)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[agentic-ui host] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    manager = SessionManager()
    client = HubDaemonClient(manager, args.hub, name, token=args.token, hf_token=resolve_hf_token(args.hf_token))
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
