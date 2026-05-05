from __future__ import annotations

import argparse
import logging
import os
import sys

import uvicorn

from switch.cli import _has_browser_auth_configured, _is_public_bind_host


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="switch-hub",
        description="agentic-ui hub — central server for AI session multiplexing",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=int(os.environ.get("SWITCH_HUB_PORT", "9341")),
        help="HTTP/WebSocket port to listen on (default: 9341, env: SWITCH_HUB_PORT)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("SWITCH_HUB_HOST", "127.0.0.1"),
        help="Host to bind to (default: 127.0.0.1, env: SWITCH_HUB_HOST)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--allow-insecure",
        action="store_true",
        help="Allow a network-reachable hub without SWITCH_UI_TOKEN",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[agentic-ui hub] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if _is_public_bind_host(args.host) and not _has_browser_auth_configured() and not args.allow_insecure:
        print(
            "Error: refusing to bind a hub to a network-reachable address without browser auth.",
            file=sys.stderr,
        )
        sys.exit(2)

    uvicorn.run(
        "switch.hub.app:app",
        host=args.host,
        port=args.port,
        log_level="debug" if args.verbose else "info",
    )


if __name__ == "__main__":
    main()
