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
    hub_p.add_argument("--dev", action="store_true", help="Dev mode: auto-reload on Python changes, use Vite for frontend")

    # --- daemon ---
    daemon_p = sub.add_parser("daemon", help="Start a daemon on this machine")
    daemon_p.add_argument("-p", "--port", type=int, default=9340, help="Port (default: 9340)")
    daemon_p.add_argument("--hub", default="http://localhost:9341", help="Hub URL (default: http://localhost:9341)")
    daemon_p.add_argument("-n", "--name", default=None, help="Display name (default: daemon-<port>)")
    daemon_p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # --- dev ---
    sub.add_parser("dev", help="Start hub + daemon + frontend dev server (all-in-one)")

    # --- update ---
    sub.add_parser("update", help="Update switch to the latest version")

    args = parser.parse_args()

    if args.command == "hub":
        _run_hub(args)
    elif args.command == "daemon":
        _run_daemon(args)
    elif args.command == "dev":
        _run_dev()
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


def _run_dev() -> None:
    import os
    import signal
    import subprocess
    from pathlib import Path

    os.environ["SWITCH_DEV"] = "1"
    web_dir = Path(__file__).parent.parent / "web"

    if not (web_dir / "package.json").exists():
        print("Error: switch/web not found — switch dev requires a repo checkout", file=sys.stderr)
        sys.exit(1)

    if not (web_dir / "node_modules").exists():
        print("[switch dev] Installing frontend dependencies...")
        subprocess.run(["npm", "install"], cwd=web_dir, check=True)

    procs: list[subprocess.Popen] = []
    try:
        # Hub with auto-reload
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "switch.hub.app:app",
             "--host", "0.0.0.0", "--port", "9341", "--reload", "--reload-dir", "switch"],
        ))
        # Daemon
        procs.append(subprocess.Popen(
            [sys.executable, "-c",
             "from switch.cli import _run_daemon; import argparse; "
             "args = argparse.Namespace(port=9340, hub='http://localhost:9341', name='local', verbose=False); "
             "_run_daemon(args)"],
        ))
        # Vite dev server
        procs.append(subprocess.Popen(
            ["npx", "vite", "--port", "5173"],
            cwd=web_dir,
        ))

        print("[switch dev] Starting hub (:9341), daemon, and frontend (:5173)")
        print("[switch dev] Open http://localhost:5173")
        print("[switch dev] Press Ctrl+C to stop all")

        # Wait for any process to exit
        while True:
            for p in procs:
                ret = p.poll()
                if ret is not None:
                    raise KeyboardInterrupt
            import time
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[switch dev] Stopping...")
        for p in procs:
            p.send_signal(signal.SIGTERM)
        for p in procs:
            p.wait(timeout=5)


def _run_hub(args: argparse.Namespace) -> None:
    import logging
    import os

    import uvicorn

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[switch hub] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.dev:
        os.environ["SWITCH_DEV"] = "1"
        print("[switch hub] Dev mode — Python auto-reload enabled")
        print("[switch hub] Run 'cd switch/web && npm run dev' in another terminal for frontend hot reload")
        print(f"[switch hub] Then open http://localhost:5173 (Vite proxies API/WS to :{args.port})")

    uvicorn.run(
        "switch.hub.app:app",
        host=args.host,
        port=args.port,
        log_level="debug" if args.verbose else "info",
        reload=args.dev,
        reload_dirs=["switch"] if args.dev else None,
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
