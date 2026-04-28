from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="switch",
        description="Switch — AI session multiplexer for Claude Code and Codex",
    )
    sub = parser.add_subparsers(dest="command")

    # --- hub ---
    hub_p = sub.add_parser("hub", help="Start the hub server (includes web UI)")
    hub_p.add_argument("-p", "--port", type=int, default=9341, help="Port (default: 9341)")
    hub_p.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    hub_p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # --- daemon ---
    daemon_p = sub.add_parser("daemon", help="Start a daemon on this machine")
    daemon_p.add_argument("-p", "--port", type=int, default=9340, help="Port (default: 9340)")
    daemon_p.add_argument("--hub", default="http://localhost:9341", help="Hub URL (default: http://localhost:9341)")
    daemon_p.add_argument("-n", "--name", default=None, help="Display name (default: daemon-<port>)")
    daemon_p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # --- update ---
    sub.add_parser("update", help="Update switch to the latest version")

    args = parser.parse_args()

    if args.command == "hub":
        _run_hub(args)
    elif args.command == "daemon":
        _run_daemon(args)
    elif args.command == "update":
        _run_update()
    else:
        parser.print_help()
        sys.exit(1)


REPO_URL = "git+ssh://git@github.com/edbeeching/switch.git"


def _run_update() -> None:
    import shutil
    import subprocess

    uv = shutil.which("uv")
    if not uv:
        print("Error: uv not found on PATH", file=sys.stderr)
        sys.exit(1)

    print(f"Updating switch from {REPO_URL} ...")
    subprocess.run(
        [uv, "tool", "install", "--force", "--reinstall", REPO_URL],
        check=True,
    )
    print("Updated successfully.")


def _run_hub(args: argparse.Namespace) -> None:
    import logging

    import uvicorn

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[switch hub] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    uvicorn.run(
        "switch.hub.app:app",
        host=args.host,
        port=args.port,
        log_level="debug" if args.verbose else "info",
    )


def _run_daemon(args: argparse.Namespace) -> None:
    import asyncio
    import logging
    import signal

    from switch.daemon.registration import HubRegistration
    from switch.daemon.session_manager import SessionManager
    from switch.daemon.ws_server import DaemonWsServer

    name = args.name or f"daemon-{args.port}"

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[switch daemon] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    async def run() -> None:
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

    asyncio.run(run())
