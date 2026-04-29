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
    hub_p.add_argument("--local-daemon", action="store_true", help="Also launch a local daemon for this hub")
    hub_p.add_argument("--daemon-port", type=int, default=9340, help="Local daemon port with --local-daemon (default: 9340)")
    hub_p.add_argument("--daemon-name", default="local", help="Local daemon name with --local-daemon (default: local)")

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


def _detect_reachable_ip() -> str | None:
    """Best-effort local IP that another machine can use to reach this host."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    return None


def _display_host_for_daemons(bind_host: str) -> str:
    """Return the host to show in `switch daemon --hub ...` instructions."""
    if bind_host in {"0.0.0.0", "::"}:
        return _detect_reachable_ip() or "localhost"
    return bind_host


def _display_host_for_browser(bind_host: str) -> str:
    """Return the host to open from the same machine running the hub."""
    if bind_host in {"0.0.0.0", "::"}:
        return "localhost"
    return bind_host


def _local_hub_url(bind_host: str, port: int) -> str:
    """Return the hub URL a daemon process on the same machine should use."""
    return f"http://{_display_host_for_browser(bind_host)}:{port}"


def _kill_port(port: int) -> None:
    """Kill any process listening on the given port."""
    import os
    import signal
    import subprocess
    try:
        # Get PIDs on the port
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True, text=True, timeout=3,
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            pid = pid.strip()
            if pid.isdigit():
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except ProcessLookupError:
                    pass
    except Exception:
        pass


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

    # Kill stale processes on our ports
    for port in [9341, 9340, 5173]:
        _kill_port(port)
    import time
    time.sleep(0.5)

    procs: list[subprocess.Popen] = []
    try:
        # Hub with auto-reload
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "switch.hub.app:app",
             "--host", "0.0.0.0", "--port", "9341", "--reload", "--reload-dir", "switch"],
            start_new_session=True,
        ))
        # Wait for hub to be ready before starting daemon
        import time
        import httpx
        for _ in range(30):
            try:
                httpx.get("http://localhost:9341/api/daemons", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        # Daemon
        procs.append(subprocess.Popen(
            [sys.executable, "-c",
             "from switch.cli import _run_daemon; import argparse; "
             "args = argparse.Namespace(port=9340, hub='http://localhost:9341', name='local', verbose=False); "
             "_run_daemon(args)"],
            start_new_session=True,
        ))
        # Vite dev server
        procs.append(subprocess.Popen(
            ["npx", "vite", "--port", "5173"],
            cwd=web_dir,
            start_new_session=True,
        ))

        print("[switch dev] Starting hub (:9341), daemon, and frontend (:5173)")
        print("[switch dev] Press Ctrl+C to stop all")

        import webbrowser
        import time as _time
        _time.sleep(2)
        webbrowser.open("http://localhost:5173")

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
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:
                p.kill()


def _run_hub(args: argparse.Namespace) -> None:
    import logging
    import os
    import signal
    import subprocess
    import threading
    import time

    import httpx
    import uvicorn

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[switch hub] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    daemon_url = f"http://{_display_host_for_daemons(args.host)}:{args.port}"
    browser_url = f"http://{_display_host_for_browser(args.host)}:{args.port}"
    local_hub_url = _local_hub_url(args.host, args.port)
    local_daemon_proc: subprocess.Popen | None = None
    local_daemon_lock = threading.Lock()

    print()
    print(f"  [switch hub] To connect daemons:")
    print(f"    switch daemon --hub {daemon_url}")
    print()
    if args.dev:
        os.environ["SWITCH_DEV"] = "1"
        print(f"  [switch hub] Dev mode — Python auto-reload enabled")
        print(f"  [switch hub] Run 'cd switch/web && npm run dev' for frontend hot reload")
        print(f"  [switch hub] Open http://localhost:5173")
    else:
        print(f"  [switch hub] Open {browser_url}")
        if daemon_url != browser_url:
            print(f"  [switch hub] Network URL {daemon_url}")
    if args.local_daemon:
        print(f"  [switch hub] Local daemon will start on :{args.daemon_port} as '{args.daemon_name}'")
    print()

    import webbrowser
    open_url = "http://localhost:5173" if args.dev else browser_url
    threading.Timer(1.5, webbrowser.open, args=[open_url]).start()

    def start_local_daemon_when_ready() -> None:
        nonlocal local_daemon_proc
        for _ in range(60):
            try:
                httpx.get(f"{local_hub_url}/api/daemons", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
        else:
            print(f"  [switch hub] Local daemon was not started because {local_hub_url} did not become ready", file=sys.stderr)
            return

        cmd = [
            sys.executable,
            "-m",
            "switch.daemon",
            "--port",
            str(args.daemon_port),
            "--hub",
            local_hub_url,
            "--name",
            args.daemon_name,
        ]
        if args.verbose:
            cmd.append("--verbose")
        with local_daemon_lock:
            local_daemon_proc = subprocess.Popen(cmd, start_new_session=True)
        print(f"  [switch hub] Started local daemon pid={local_daemon_proc.pid}")

    def stop_local_daemon() -> None:
        with local_daemon_lock:
            proc = local_daemon_proc
        if not proc or proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    if args.local_daemon:
        threading.Thread(target=start_local_daemon_when_ready, daemon=True).start()

    try:
        uvicorn.run(
            "switch.hub.app:app",
            host=args.host,
            port=args.port,
            log_level="debug" if args.verbose else "info",
            reload=args.dev,
            reload_dirs=["switch"] if args.dev else None,
        )
    finally:
        stop_local_daemon()


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
