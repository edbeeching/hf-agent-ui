from __future__ import annotations

import argparse
import logging
import os

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="switch-hub",
        description="Switch hub — central server for AI session multiplexing",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=int(os.environ.get("SWITCH_HUB_PORT", "9341")),
        help="HTTP/WebSocket port to listen on (default: 9341, env: SWITCH_HUB_PORT)",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("SWITCH_HUB_HOST", "0.0.0.0"),
        help="Host to bind to (default: 0.0.0.0, env: SWITCH_HUB_HOST)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[switch-hub] %(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    uvicorn.run(
        "switch_hub.app:app",
        host=args.host,
        port=args.port,
        log_level="debug" if args.verbose else "info",
    )


if __name__ == "__main__":
    main()
