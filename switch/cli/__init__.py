from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="switch",
        description="agentic-ui — browser control for Claude Code and Codex sessions",
    )
    sub = parser.add_subparsers(dest="command")

    # --- hub ---
    hub_p = sub.add_parser("hub", help="Start the hub server (includes web UI)")
    hub_p.add_argument("-p", "--port", type=int, default=9341, help="Port (default: 9341)")
    hub_p.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    hub_p.add_argument("--allow-insecure", action="store_true", help="Allow a network-reachable hub without SWITCH_UI_TOKEN")
    hub_p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    hub_p.add_argument("--dev", action="store_true", help="Dev mode: auto-reload on Python changes, use Vite for frontend")
    hub_p.add_argument("--local-agent-host", "--local-daemon", dest="local_daemon", action="store_true", help="Also launch a local agent host for this hub")
    hub_p.add_argument("--agent-host-port", "--daemon-port", dest="daemon_port", type=int, default=9340, help="Local agent host port with --local-agent-host (default: 9340)")
    hub_p.add_argument("--agent-host-name", "--daemon-name", dest="daemon_name", default="local", help="Local agent host name with --local-agent-host (default: local)")

    # --- agent host ---
    daemon_p = sub.add_parser("host", aliases=["daemon"], help="Start an agent host on this machine")
    daemon_p.add_argument("-p", "--port", type=int, default=9340, help="Deprecated; ignored in outbound mode")
    daemon_p.add_argument("--hub", default="http://localhost:9341", help="Hub URL (default: http://localhost:9341)")
    daemon_p.add_argument("--token", default=None, help="Agent host auth token (env: SWITCH_DAEMON_TOKEN)")
    daemon_p.add_argument("--hf-token", default=None, help="Hugging Face token for private Spaces (env: HF_TOKEN)")
    daemon_p.add_argument("-n", "--name", default=None, help="Display name (default: hostname)")
    daemon_p.add_argument("-v", "--verbose", action="store_true", help="Debug logging")

    # --- dev ---
    sub.add_parser("dev", help="Start hub + agent host + frontend dev server (all-in-one)")

    # --- update ---
    sub.add_parser("update", help="Update agentic-ui to the latest version")

    args = parser.parse_args()

    if args.command == "hub":
        _run_hub(args)
    elif args.command in {"host", "daemon"}:
        _run_daemon(args)
    elif args.command == "dev":
        _run_dev()
    elif args.command == "update":
        _run_update()
    else:
        parser.print_help()
        sys.exit(1)


REPO_URL = "git+ssh://git@github.com/edbeeching/agentic-ui.git"


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
    """Return the host to show in `switch host --hub ...` instructions."""
    if bind_host in {"0.0.0.0", "::"}:
        return _detect_reachable_ip() or "localhost"
    return bind_host


def _is_public_bind_host(bind_host: str) -> bool:
    host = bind_host.strip().lower()
    return host not in {"127.0.0.1", "localhost", "::1"}


def _has_browser_auth_configured() -> bool:
    import os

    return bool(os.environ.get("SWITCH_UI_TOKEN")) or os.environ.get("SWITCH_TRUST_PROXY_AUTH") == "1"


def _display_host_for_browser(bind_host: str) -> str:
    """Return the host to open from the same machine running the hub."""
    if bind_host in {"0.0.0.0", "::"}:
        return "localhost"
    return bind_host


def _local_hub_url(bind_host: str, port: int) -> str:
    """Return the hub URL an agent host process on the same machine should use."""
    return f"http://{_display_host_for_browser(bind_host)}:{port}"


def _daemon_token(args: argparse.Namespace) -> str | None:
    import os

    return getattr(args, "token", None) or os.environ.get("SWITCH_DAEMON_TOKEN")


def _hf_token(args: argparse.Namespace) -> str | None:
    import os

    return getattr(args, "hf_token", None) or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def _ui_auth_headers() -> dict[str, str]:
    import os

    token = os.environ.get("SWITCH_UI_TOKEN")
    return {"X-Agentic-UI-Token": token} if token else {}


def _daemon_name(args: argparse.Namespace) -> str:
    import platform

    return getattr(args, "name", None) or platform.node() or f"daemon-{getattr(args, 'port', 9340)}"


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

    print(f"Updating agentic-ui from {REPO_URL} ...")
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
    os.environ["SWITCH_HUB_DAEMON_URL"] = "http://localhost:9341"
    web_dir = Path(__file__).parent.parent / "web"

    if not (web_dir / "package.json").exists():
        print("Error: switch/web not found — switch dev requires a repo checkout", file=sys.stderr)
        sys.exit(1)

    if not (web_dir / "node_modules").exists():
        print("[agentic-ui dev] Installing frontend dependencies...")
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
             "--host", "127.0.0.1", "--port", "9341", "--reload", "--reload-dir", "switch"],
            start_new_session=True,
        ))
        # Wait for hub to be ready before starting the agent host
        import time
        import httpx
        for _ in range(30):
            try:
                httpx.get("http://localhost:9341/api/daemons", timeout=1, headers=_ui_auth_headers())
                break
            except Exception:
                time.sleep(0.5)
        # Agent host
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

        print("[agentic-ui dev] Starting hub (:9341), agent host, and frontend (:5173)")
        print("[agentic-ui dev] Press Ctrl+C to stop all")

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
        print("\n[agentic-ui dev] Stopping...")
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
        format="[agentic-ui hub] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if _is_public_bind_host(args.host) and not _has_browser_auth_configured() and not getattr(args, "allow_insecure", False):
        print(
            "Error: refusing to bind a hub to a network-reachable address without browser auth.\n"
            "Set SWITCH_UI_TOKEN, set SWITCH_TRUST_PROXY_AUTH=1 behind a trusted private proxy, "
            "or pass --allow-insecure for local trusted-network use.",
            file=sys.stderr,
        )
        sys.exit(2)

    daemon_url = f"http://{_display_host_for_daemons(args.host)}:{args.port}"
    browser_url = f"http://{_display_host_for_browser(args.host)}:{args.port}"
    local_hub_url = _local_hub_url(args.host, args.port)
    os.environ["SWITCH_HUB_DAEMON_URL"] = daemon_url
    local_daemon_proc: subprocess.Popen | None = None
    local_daemon_lock = threading.Lock()

    print()
    print(f"  [agentic-ui hub] To connect agent hosts:")
    print(f"    switch host --hub {daemon_url}")
    print()
    if args.dev:
        os.environ["SWITCH_DEV"] = "1"
        print(f"  [agentic-ui hub] Dev mode — Python auto-reload enabled")
        print(f"  [agentic-ui hub] Run 'cd switch/web && npm run dev' for frontend hot reload")
        print(f"  [agentic-ui hub] Open http://localhost:5173")
    else:
        print(f"  [agentic-ui hub] Open {browser_url}")
        if daemon_url != browser_url:
            print(f"  [agentic-ui hub] Network URL {daemon_url}")
    if args.local_daemon:
        print(f"  [agentic-ui hub] Local agent host will start on :{args.daemon_port} as '{args.daemon_name}'")
    print()

    import webbrowser
    open_url = "http://localhost:5173" if args.dev else browser_url
    threading.Timer(1.5, webbrowser.open, args=[open_url]).start()

    def start_local_daemon_when_ready() -> None:
        nonlocal local_daemon_proc
        for _ in range(60):
            try:
                httpx.get(f"{local_hub_url}/api/daemons", timeout=1, headers=_ui_auth_headers())
                break
            except Exception:
                time.sleep(0.5)
        else:
            print(f"  [agentic-ui hub] Local agent host was not started because {local_hub_url} did not become ready", file=sys.stderr)
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
        print(f"  [agentic-ui hub] Started local agent host pid={local_daemon_proc.pid}")

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

    from switch.daemon.hub_client import HubDaemonClient
    from switch.daemon.session_manager import SessionManager

    name = _daemon_name(args)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[agentic-ui host] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger(__name__)

    async def run() -> None:
        manager = SessionManager()
        client = HubDaemonClient(manager, args.hub, name, token=_daemon_token(args), hf_token=_hf_token(args))
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

    asyncio.run(run())
